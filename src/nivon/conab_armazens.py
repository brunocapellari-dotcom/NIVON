"""Importador offline SICARM/CONAB; exige mapeamento explícito e auditado.

Não presume layout do TXT remoto. Não baixa dados, não armazena cadastro
individual nem libera redistribuição. Capacidade estática != estoque/ocupação.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

_UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
_MAX_BYTES = 120_000_000
_MAX_ROWS = 400_000


class ErroArmazens(ValueError):
    """Arquivo/layout inconsistente, não apto a alimentar indicador."""


@dataclass(frozen=True)
class LayoutArmazens:
    """Cabeçalhos reais devem ser copiados de amostra oficial, não inferidos."""
    separador: str
    codificacao: str
    coluna_id_armazem: str
    coluna_uf: str
    coluna_municipio: str
    coluna_capacidade: str
    unidade_capacidade: str
    decimal: str
    milhar: str
    coluna_codigo_ibge: str | None = None

    def validar(self) -> None:
        if self.separador not in (";", "|", "\t", ",") or self.codificacao not in ("utf-8-sig", "utf-8", "cp1252"):
            raise ErroArmazens("separador/codificação fora do contrato")
        if (self.decimal, self.milhar) not in ((",", "."), (".", ","), (",", ""), (".", "")):
            raise ErroArmazens("convenção decimal/milhar não autorizada")
        if self.unidade_capacidade not in ("t", "kg"):
            raise ErroArmazens("unidade de capacidade não documentada")
        nomes = [self.coluna_id_armazem, self.coluna_uf, self.coluna_municipio,
                 self.coluna_capacidade]
        if self.coluna_codigo_ibge is not None:
            nomes.append(self.coluna_codigo_ibge)
        if any(not isinstance(x, str) or not x.strip() or len(x)>130 for x in nomes):
            raise ErroArmazens("nomes de coluna obrigatórios")
        if len(set(nomes)) != len(nomes):
            raise ErroArmazens("colunas de significados diferentes repetidas")


# Layout confirmado apenas por INSPEÇÃO DO CABEÇALHO (não homologação do dataset).
LAYOUT_CONAB_SICARM_HEADER_V1 = LayoutArmazens(
    separador=";", codificacao="cp1252",
    coluna_id_armazem="identificacao_armazem",
    coluna_uf="uf", coluna_municipio="nom_municipio",
    coluna_capacidade="qtd_capacidade_estatica(t)",
    unidade_capacidade="t", decimal=",", milhar=".",
    coluna_codigo_ibge="cod_ibge",
)


def _chave_nome(nome: str) -> str:
    base = unicodedata.normalize("NFKD", nome)
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.upper().split())


def _instante(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroArmazens("data de coleta ISO obrigatória")
    try:
        data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroArmazens("data de coleta ISO inválida") from exc
    if data.tzinfo is None or data.utcoffset() is None:
        raise ErroArmazens("coleta exige timezone")
    return data.astimezone(timezone.utc).isoformat()


def _arquivo(path: str | Path) -> Path:
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.suffix.lower() not in (".txt", ".csv"):
        raise ErroArmazens("arquivo TXT/CSV local regular obrigatório")
    if not 0 < p.stat().st_size <= _MAX_BYTES:
        raise ErroArmazens("tamanho de arquivo fora dos limites")
    return p


def _valor(raw: str, layout: LayoutArmazens) -> Decimal:
    if not isinstance(raw, str) or not raw.strip():
        raise ErroArmazens("capacidade nula")
    s = raw.strip()
    d, m = re.escape(layout.decimal), re.escape(layout.milhar)
    # Permitimos agrupamento de milhares somente em grupos corretos de 3.
    padrao = (rf"(?:[0-9]{{1,3}}(?:{m}[0-9]{{3}})+|[0-9]+)"
              if m else r"[0-9]+")
    if not re.fullmatch(padrao + rf"(?:{d}[0-9]{{1,3}})?", s):
        raise ErroArmazens("capacidade fora do formato decimal declarado")
    try:
        numero = Decimal(s.replace(layout.milhar, "").replace(layout.decimal, "."))
    except InvalidOperation as exc:
        raise ErroArmazens("capacidade decimal inválida") from exc
    if numero <= 0 or numero > 100_000_000:
        raise ErroArmazens("capacidade zero, negativa ou acima do limite técnico")
    return numero if layout.unidade_capacidade == "t" else numero / 1000


def inspecionar_cabecalho_local(path: str | Path, *, codificacao="utf-8-sig") -> dict:
    """Somente linha de cabeçalho: não mostra indivíduos nem baixa a fonte."""
    p = _arquivo(path)
    if codificacao not in ("utf-8-sig", "utf-8", "cp1252"):
        raise ErroArmazens("codificação inválida")
    with p.open("rb") as stream:
        amostra = stream.read(32768)
    try:
        primeira = amostra.decode(codificacao, errors="strict").splitlines()[0]
    except (UnicodeError, IndexError) as exc:
        raise ErroArmazens("cabeçalho ausente ou inválido") from exc
    if len(primeira) > 16384 or "<html" in primeira.lower() or "<!doctype" in primeira.lower():
        raise ErroArmazens("arquivo não parece TXT tabular")
    opcoes = {}
    for sep in (";", "|", "\t", ","):
        opcoes[{";":"ponto_e_virgula","|":"pipe","\t":"tab",",":"virgula"}[sep]] = len(next(csv.reader([primeira], delimiter=sep)))
    return {"bytes_amostra":len(amostra),"sha256_amostra":hashlib.sha256(amostra).hexdigest(),
            "colunas_por_separador":opcoes,"tipo":"CABECALHO_SEM_MAPEAMENTO_HOMOLOGADO",
            "colunas_nao_expostas_por_privacidade":True}


def agregar_capacidade_local(path: str | Path, layout: LayoutArmazens, *,
                             coletado_em: str, referencia: str | None = None,
                             publicacao: str | None = None,
                             municipios_ibge: list[dict] | None = None) -> dict:
    """Agrupa armazéns por UF/município sem reter identificadores individuais.

    Exige identidade única por armazém: sem prova do grão do arquivo, não somar.
    Município por texto é provisório; código IBGE só com lista validada.
    """
    p = _arquivo(path)
    if not isinstance(layout, LayoutArmazens):
        raise ErroArmazens("layout explícito obrigatório")
    layout.validar()
    coleta = _instante(coletado_em)
    for x in (referencia, publicacao):
        if x is not None:
            try:
                from datetime import date
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", x):
                    raise ValueError()
                date.fromisoformat(x)
            except (ValueError, TypeError) as exc:
                raise ErroArmazens("referência/publicação só com data verificada") from exc
    if publicacao and publicacao > coleta[:10]:
        raise ErroArmazens("publicação não pode ocorrer depois da coleta")
    municipios = {}
    if municipios_ibge is not None:
        if not isinstance(municipios_ibge, list):
            raise ErroArmazens("base municipal IBGE inválida")
        for item in municipios_ibge:
            if not isinstance(item, dict):
                raise ErroArmazens("item IBGE inválido")
            ch = (item.get("uf"), _chave_nome(item.get("nome","")))
            codigo = item.get("codigo_ibge")
            if ch in municipios or not isinstance(codigo, str) or not re.fullmatch(r"\d{7}", codigo):
                raise ErroArmazens("base IBGE ambígua ou inválida")
            municipios[ch] = codigo
    sha = hashlib.sha256()
    with p.open("rb") as stream:
        for chunk in iter(lambda: stream.read(262144), b""):
            sha.update(chunk)
    grupos = defaultdict(lambda: [Decimal("0"), 0, None])
    ids = set()
    linhas = 0
    try:
        with p.open("r", encoding=layout.codificacao, errors="strict", newline="") as stream:
            reader = csv.DictReader(stream, delimiter=layout.separador)
            header = reader.fieldnames or []
            requer = [layout.coluna_id_armazem,layout.coluna_uf,layout.coluna_municipio,
                      layout.coluna_capacidade]
            if layout.coluna_codigo_ibge:
                requer.append(layout.coluna_codigo_ibge)
            if len(header) != len(set(header)) or not set(requer).issubset(header):
                raise ErroArmazens("schema diferente do layout auditado")
            for linha in reader:
                linhas += 1
                if linhas > _MAX_ROWS:
                    raise ErroArmazens("limite de registros excedido")
                if None in linha or any(v is None for v in linha.values()):
                    raise ErroArmazens("registro desalinhado")
                identidade = linha[layout.coluna_id_armazem].strip()
                if not identidade or len(identidade)>130 or identidade in ids:
                    raise ErroArmazens("identificador ausente/duplicado: grão do arquivo não comprovado")
                ids.add(identidade)
                uf = linha[layout.coluna_uf].strip().upper()
                nome = " ".join(linha[layout.coluna_municipio].strip().split())
                if uf not in _UFS or not nome or len(nome)>130 or any(ord(c)<32 for c in nome):
                    raise ErroArmazens("UF/município inválido")
                chave = (uf, _chave_nome(nome))
                codigo = municipios.get(chave)
                informado = (linha[layout.coluna_codigo_ibge].strip()
                             if layout.coluna_codigo_ibge else None)
                if informado and not re.fullmatch(r"\d{7}", informado):
                    raise ErroArmazens("código IBGE inválido")
                if municipios_ibge is not None and (codigo is None or (informado and informado != codigo)):
                    raise ErroArmazens("código/município divergente da base IBGE")
                if municipios_ibge is None:
                    codigo = None  # jamais promover código não cruzado a canônico
                cap = _valor(linha[layout.coluna_capacidade], layout)
                grupo = grupos[chave]
                if grupo[2] is not None and grupo[2] != codigo:
                    raise ErroArmazens("conflito de código municipal")
                grupo[0] += cap
                grupo[1] += 1
                grupo[2] = codigo
    except UnicodeError as exc:
        raise ErroArmazens("codificação não corresponde ao contrato") from exc
    if not linhas:
        raise ErroArmazens("sem linhas: não tratar como capacidade zero")
    saida = []
    for (uf,nome),(total,n,codigo) in sorted(grupos.items()):
        saida.append({"uf":uf,"municipio_normalizado":nome,"codigo_ibge":codigo,
                      "armazens_distintos":n,"capacidade_estatica_t":float(total),
                      "unidade":"t","natureza":"CAPACIDADE_CADASTRADA_NAO_ESTOQUE"})
    return {"dataset_id":"CONAB_ARMAZENS_CAPACIDADE","fonte_id":"CONAB",
            "sha256_original":sha.hexdigest(),"bytes":p.stat().st_size,
            "linhas_validas":linhas,"municipios":len(saida),"agregados":saida,
            "capacidade_total_t":float(sum((x[0] for x in grupos.values()),Decimal(0))),
            "coleta":coleta,"referencia":referencia,"publicacao":publicacao,
            "status":"AGREGACAO_LOCAL_SEM_HOMOLOGACAO_DE_LAYOUT_DIREITOS_OU_PUBLICACAO",
            "alerta":"Sem dado de ocupação, estoque ou espaço disponível; identidade da unidade depende do layout"}


def main(argv=None):
    ap=argparse.ArgumentParser(description="NIVON: inspeção local de layout SICARM, sem rede")
    ap.add_argument("--inspecionar",required=True)
    args=ap.parse_args(argv)
    print(json.dumps(inspecionar_cabecalho_local(args.inspecionar),ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
