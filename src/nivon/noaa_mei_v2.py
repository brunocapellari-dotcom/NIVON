"""NOAA PSL MEI v2: cliente pontual e parsing de pares bimestrais.

O CSV oficial contém meses sobrepostos DJ, JF,...ND; não são doze
observações mensais independentes. Não misturar MEI v2, ONI e RONI.
Nenhum agendamento ou persistência está neste módulo.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler

CSV_URL = "https://psl.noaa.gov/data/correlation/meiv2.csv"
PERIODOS = ("DJ", "JF", "FM", "MA", "AM", "MJ", "JJ", "JA", "AS", "SO", "ON", "ND")


class ErroMEI(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _horario(valor):
    if not isinstance(valor, str):
        raise ErroMEI("carimbo de coleta ausente")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as e:
        raise ErroMEI("data de coleta inválida") from e
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroMEI("coleta sem fuso")
    return dt.astimezone(timezone.utc).isoformat()


def normalizar_mei_csv(blob: bytes, *, coletado_em: str) -> dict:
    coleta = _horario(coletado_em)
    if not isinstance(blob, bytes) or not 1 <= len(blob) <= 500_000:
        raise ErroMEI("arquivo ausente ou acima do limite")
    try:
        texto = blob.decode("utf-8-sig")
    except UnicodeError as e:
        raise ErroMEI("CSV NOAA não UTF-8") from e
    linhas = list(csv.reader(io.StringIO(texto), skipinitialspace=True))
    if not 2 <= len(linhas) <= 2_000:
        raise ErroMEI("CSV vazio ou excessivo")
    header = [h.strip().upper() for h in linhas[0]]
    obs = []
    chaves = set()

    def _valor(texto_indice):
        try:
            v = float(texto_indice.strip())
        except ValueError as e:
            raise ErroMEI("MEI não numérico") from e
        if not math.isfinite(v):
            raise ErroMEI("MEI não finito")
        if v in (-999.0, -99.9):
            return None
        if not -10 <= v <= 10:
            raise ErroMEI("MEI fora da faixa operacional")
        return v

    def _adicionar(dt, periodo, valor):
        if valor is None:
            return
        chave = dt.isoformat()
        if chave in chaves:
            raise ErroMEI("data MEI repetida")
        chaves.add(chave)
        obs.append({
            "data_referencia": chave,
            "competencia": chave[:7],
            "bimestre_movel": periodo,
            "valor_padronizado_mei_v2": valor, "unidade": "DESVIOS_PADRAO",
            "referencia": f"{dt.year}-{periodo}",
            "publicacao": None, "coleta": coleta,
            "natureza": "INDICE_ENSO_MEI_V2_BIMESTRAL_DESLIZANTE_OBSERVADO",
        })

    # CSV oficial 2026 do PSL: cabeçalho descritivo "Date, Multivariate ..."
    # seguido de 1979-01-01,0.460 (mês-âncora e índice bimestral DJ).
    if len(header) == 2 and header[0] == "DATE" and "MULTIVARIATE ENSO INDEX" in header[1]:
        for row in linhas[1:]:
            if len(row) != 2:
                raise ErroMEI("linha NOAA de mês e MEI desalinhada")
            try:
                from datetime import date
                dt = date.fromisoformat(row[0].strip())
            except ValueError as exc:
                raise ErroMEI("data NOAA inválida") from exc
            if dt.day != 1 or dt.year < 1979:
                raise ErroMEI("período NOAA inválido")
            _adicionar(dt, PERIODOS[dt.month-1], _valor(row[1]))

    # Formato tabular alternativo YEAR, DJ, JF...ND, mantido em testes.
    elif header == ["YEAR", *PERIODOS]:
        from datetime import date
        years = set()
        for row in linhas[1:]:
            if len(row) != 13:
                raise ErroMEI("linha NOAA tabular desalinhada")
            ano = row[0].strip()
            if not re.fullmatch(r"(19[7-9]\d|20\d\d|21\d\d)", ano) or ano in years:
                raise ErroMEI("ano NOAA inválido ou repetido")
            years.add(ano)
            for m, periodo in enumerate(PERIODOS, 1):
                if row[m].strip():
                    _adicionar(date(int(ano), m, 1), periodo, _valor(row[m]))
    else:
        raise ErroMEI("schema NOAA MEI desconhecido")
    if len(obs) > 1 and any(obs[i]["data_referencia"] <= obs[i-1]["data_referencia"] for i in range(1,len(obs))):
        raise ErroMEI("datas NOAA fora de ordem")
    if not obs:
        raise ErroMEI("sem MEI válido")
    return {
        "dataset_id": "NOAA_ENSO_INDICES_HISTORICOS", "fonte_id": "NOAA",
        "serie": "MEIV2", "url": CSV_URL,
        "observacoes": obs, "quantidade": len(obs),
        "sha256_original": hashlib.sha256(blob).hexdigest(),
        "coleta": coleta, "publicacao": None, "apto_backtest_asof": False,
        "apto_publicacao_automatica": False,
        "estado": "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO",
    }


def consultar_mei_v2(*, executar: bool = False, abridor=None, instante=None):
    if executar is not True:
        raise PermissionError("NOAA MEI: consulta HTTP pontual requer executar=True")
    agora = instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroMEI("instante precisa de timezone")
    cliente = abridor if abridor is not None else build_opener(_NoRedirect())
    req = Request(CSV_URL, headers={"User-Agent": "NIVON/0.1 (nao comercial)", "Accept": "text/csv,text/plain"})
    with cliente.open(req, timeout=15) as resp:
        if int(resp.status) != 200 or resp.geturl() != CSV_URL:
            raise ErroMEI("HTTP inválido ou redirect")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in {"text/csv", "text/plain", "application/octet-stream"}:
            raise ErroMEI("MIME incompatível")
        body = resp.read(500_001)
        if len(body) > 500_000:
            raise ErroMEI("tamanho excedido")
    data = normalizar_mei_csv(body, coletado_em=agora.isoformat())
    return {"aquisicao": {"sha256": data["sha256_original"], "bytes": len(body),
                           "coleta": data["coleta"]}, "dados": data}
