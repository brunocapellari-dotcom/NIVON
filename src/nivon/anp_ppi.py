"""Coletor oficial ANP PPI (semanal) para o ledger NIVON.

Parser adaptado da abordagem MIT de jmagomez/anp-ppi-dashboard.
Copyright (c) 2026 jmagomez; aviso integral em docs/licencas/anp-ppi-dashboard-MIT.txt.
Não utiliza o JSON derivado do dashboard como fonte primária.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .ingestao_fontes_reais import gravar_lote

XLSX_URL = (
    "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
    "precos/arq-ppi/ppi.xlsx"
)
FONTE_PAGINA = (
    "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
    "precos/precos-de-paridade-de-importacao"
)
DATASET = "BR_ANP_PPI_SEMANAL"
MAX_BYTES = 25_000_000
ABAS = {
    "Gasolina R$ semanal": ("gasolina", "Gasolina A", "R$/litro"),
    "Diesel R$ semanal": ("diesel", "Diesel A S10", "R$/litro"),
    "QAV R$ semanal": ("qav", "QAV", "R$/litro"),
    "GLP R$ kg semanal": ("glp", "GLP", "R$/13kg"),
}
DATAS = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


class ErroPPI(ValueError):
    """Planilha, dados ou transporte não atendem o contrato de origem."""


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def baixar_planilha(*, cliente=None) -> bytes:
    """Somente URL oficial fixa; não segue redirects nem URLs de terceiros."""
    abrir = cliente if cliente is not None else build_opener(_SemRedirect())
    req = Request(XLSX_URL, headers={
        "User-Agent": "NIVON/0.1 (coleta publica ANP PPI)",
        "Accept": "application/octet-stream,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    })
    try:
        with abrir.open(req, timeout=60) as resp:
            if int(resp.status) != 200 or resp.geturl() != XLSX_URL:
                raise ErroPPI("resposta ou redirecionamento inesperado")
            raw = resp.read(MAX_BYTES + 1)
    except ErroPPI:
        raise
    except Exception as exc:
        raise ErroPPI("falha na coleta oficial do PPI") from exc
    if not isinstance(raw, bytes) or not 100 <= len(raw) <= MAX_BYTES:
        raise ErroPPI("planilha vazia ou tamanho proibido")
    if raw[:4] != b"PK\x03\x04":
        raise ErroPPI("resposta não é XLSX (assinatura ZIP incorreta)")
    return raw


def _normalizar(s):
    if s is None:
        return ""
    txt = unicodedata.normalize("NFKD", str(s).replace("\xa0", " ").strip())
    return " ".join("".join(c for c in txt if not unicodedata.combining(c)).lower().split())


def _periodo(valor):
    if isinstance(valor, datetime):
        d = valor.date()
        return d, d
    if isinstance(valor, date):
        return valor, valor
    achados = DATAS.findall(str(valor or ""))
    if not achados:
        return None
    try:
        datas = [date(int(ano), int(mes), int(dia)) for dia, mes, ano in achados]
    except ValueError as exc:
        raise ErroPPI("data inválida em período ANP") from exc
    if datas[0] > datas[-1] or (datas[-1] - datas[0]).days > 14:
        raise ErroPPI("período ANP incompatível com semana")
    return datas[0], datas[-1]


def _decimal(valor):
    if valor is None or isinstance(valor, bool):
        return None
    texto = str(valor).strip()
    if not texto or _normalizar(texto) in {"-", "--", "...", "n/d", "nd", "*"}:
        return None
    texto = texto.replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        v = Decimal(texto)
    except InvalidOperation as exc:
        raise ErroPPI("preço ANP não numérico") from exc
    if not v.is_finite() or v <= 0 or v >= 1000:
        raise ErroPPI("preço ANP fora de faixa positiva plausível")
    return v


def normalizar_xlsx(raw: bytes, *, hoje=None):
    """Transforma as 4 abas semanais oficiais em registros NIVON com evidência.

    O segundo bloco das abas da ANP é variação percentual; só lê o primeiro,
    que contém preços. Nunca agrega terminais nem compara com revenda/tributos.
    """
    if not isinstance(raw, bytes) or not raw.startswith(b"PK\x03\x04"):
        raise ErroPPI("XLSX inválido")
    hoje = date.today() if hoje is None else hoje
    if not isinstance(hoje, date):
        raise ErroPPI("data de referência inválida")
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError('necessário instalar o extra NIVON "excel"') from exc
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise ErroPPI("XLSX oficial ilegível") from exc
    try:
        ausentes = set(ABAS) - set(wb.sheetnames)
        if ausentes:
            raise ErroPPI("abas PPI ausentes: " + ", ".join(sorted(ausentes)))
        observacoes, resumo = [], {}
        for aba, (produto, rotulo, unidade) in ABAS.items():
            ws = wb[aba]
            if ws.max_column and ws.max_column > 100:
                raise ErroPPI("colunas da planilha excedem limite")
            linhas = []
            for i, linha in enumerate(ws.iter_rows(values_only=True)):
                if i >= 5000:
                    raise ErroPPI("linhas da planilha excedem limite")
                linhas.append(linha)
            cabecalho = None
            for i, linha in enumerate(linhas[:15]):
                for j, celula in enumerate(linha):
                    if _normalizar(celula) in {"data", "semana"}:
                        cabecalho = i, j
                        break
                if cabecalho:
                    break
            if cabecalho is None:
                raise ErroPPI("cabeçalho não encontrado: " + aba)
            inicio_linhas, coluna_data = cabecalho
            locais = []
            for j in range(coluna_data + 1, len(linhas[inicio_linhas])):
                nome = str(linhas[inicio_linhas][j] or "").strip()
                if not nome:
                    break
                if len(nome) > 90 or nome in {item[1] for item in locais}:
                    raise ErroPPI("terminal duplicado ou inválido: " + aba)
                locais.append((j, nome))
            if not 1 <= len(locais) <= 32:
                raise ErroPPI("quantidade de terminais inválida: " + aba)
            semanas, ult_fim = set(), None
            antes = len(observacoes)
            for linha in linhas[inicio_linhas + 1:]:
                if coluna_data >= len(linha):
                    continue
                periodo = _periodo(linha[coluna_data])
                if periodo is None:
                    continue
                ini, fim = periodo
                if fim > hoje + timedelta(days=7):
                    raise ErroPPI("data futura inesperada na ANP")
                if fim in semanas:
                    raise ErroPPI("semana duplicada: " + aba)
                semanas.add(fim)
                ult_fim = max(ult_fim, fim) if ult_fim else fim
                for j, terminal in locais:
                    valor = _decimal(linha[j] if j < len(linha) else None)
                    if valor is None:
                        continue
                    observacoes.append({
                        "identidade": f"PPI|{produto}|{terminal}|{fim.isoformat()}",
                        "referencia": fim.isoformat(),
                        "competencia": ini.isoformat(),
                        "natureza": "INFORMADO",
                        "valor": format(valor, "f"),
                        "unidade": unidade,
                        "campos": {
                            "produto": produto,
                            "rotulo": rotulo,
                            "terminal": terminal,
                            "semana_inicio": ini.isoformat(),
                            "semana_fim": fim.isoformat(),
                            "indicador": "paridade_importacao",
                            "sem_tributos": True,
                            "fonte_primaria": "ANP",
                            "pagina_fonte": FONTE_PAGINA,
                            "arquivo_fonte": XLSX_URL,
                            "aba_original": aba,
                        },
                    })
            n = len(observacoes) - antes
            if n == 0 or not semanas:
                raise ErroPPI("aba sem preços utilizáveis: " + aba)
            resumo[produto] = {
                "observacoes": n,
                "terminais": len(locais),
                "semanas": len(semanas),
                "ultima_semana": ult_fim.isoformat(),
                "unidade": unidade,
            }
        return observacoes, resumo
    finally:
        wb.close()


def coletar_anp_ppi(*, banco, raw_dir, executar=False, cliente=None,
                    instante=None, hoje=None):
    if executar is not True:
        raise PermissionError("ANP_PPI_COLETA_DESABILITADA")
    instante = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(instante, datetime) or instante.utcoffset() is None:
        raise ErroPPI("instante precisa de timezone")
    raw = baixar_planilha(cliente=cliente)
    observacoes, resumo = normalizar_xlsx(raw, hoje=hoje)
    resultado = gravar_lote(
        banco=banco,
        diretorio_bruto=raw_dir,
        dataset_id=DATASET,
        origem=XLSX_URL,
        raw=raw,
        tipo="application/octet-stream",
        coletado_em=instante,
        registros=observacoes,
        estado="NORMALIZED",
    )
    ultima = max(date.fromisoformat(r["ultima_semana"]) for r in resumo.values())
    data_hoje = date.today() if hoje is None else hoje
    resultado.update({
        "fonte": "ANP_PPI_OFICIAL",
        "resumo": resumo,
        "ultima_semana": ultima.isoformat(),
        "dias_desde_referencia": (data_hoje - ultima).days,
        "frescor": "AVALIAR" if (data_hoje - ultima).days > 14 else "REGULAR",
        "hash_arquivo_oficial": hashlib.sha256(raw).hexdigest(),
        "publicado_no_terminal": False,
        "bigquery_executado": False,
    })
    return resultado


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: coleta oficial PPI ANP com ledger RAW")
    p.add_argument("--banco", default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir", default="data/nivon/raw")
    p.add_argument("--executar", action="store_true")
    args = p.parse_args(argv)
    out = coletar_anp_ppi(banco=args.banco, raw_dir=args.raw_dir, executar=args.executar)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
