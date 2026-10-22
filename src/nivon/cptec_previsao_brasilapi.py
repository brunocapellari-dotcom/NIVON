"""CPTEC/INPE via BrasilAPI: previsão pontual por código CPTEC, sem full scan.

Agregador BrasilAPI não substitui fonte primária. Dados não comerciais;
preservar datas e não habilitar publicação, coleta contínua ou produção
antes da verificação de serviço, cobertura e termos do CPTEC/INPE.
"""
from __future__ import annotations

from datetime import date
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = "https://brasilapi.com.br"
LIMITE_BYTES = 128_000
_MAX_DIAS = 6
_UF = re.compile(r"[A-Z]{2}\Z")


class ErroPrevisaoCPTEC(ValueError):
    """Erro sem refletir URL, corpo HTTP ou dados upstream."""


class _BloquearRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def preparar_consulta(*, codigo_cptec: int, dias: int = 3) -> Request:
    # Identificadores CPTEC nao sao codigos de municipio IBGE.
    if type(codigo_cptec) is not int or not 1 <= codigo_cptec <= 999_999:
        raise ErroPrevisaoCPTEC("código de localidade CPTEC inválido")
    if type(dias) is not int or not 1 <= dias <= _MAX_DIAS:
        raise ErroPrevisaoCPTEC("BrasilAPI CPTEC suporta somente 1 a 6 dias")
    path = "/api/cptec/v1/clima/previsao/" + str(codigo_cptec) + "/" + str(dias)
    return Request(BASE + path, method="GET",
                   headers={"Accept": "application/json"})


def _temperatura(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ErroPrevisaoCPTEC("temperatura inválida")
    v = float(value)
    if not math.isfinite(v) or not -75 <= v <= 65:
        raise ErroPrevisaoCPTEC("temperatura fora do domínio admissível")
    return v


def normalizar_previsao(payload: bytes, *, codigo_cptec: int, dias: int) -> dict:
    preparar_consulta(codigo_cptec=codigo_cptec, dias=dias)
    if not isinstance(payload, bytes) or not 0 < len(payload) <= LIMITE_BYTES:
        raise ErroPrevisaoCPTEC("resposta CPTEC fora do limite")
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise ErroPrevisaoCPTEC("JSON CPTEC inválido") from None
    if not isinstance(data, dict):
        raise ErroPrevisaoCPTEC("objeto CPTEC inesperado")
    cidade, uf, atualizacao, clima = (
        data.get("cidade"), data.get("estado"), data.get("atualizado_em"), data.get("clima")
    )
    if (not isinstance(cidade, str) or not cidade.strip() or len(cidade) > 160
            or not isinstance(uf, str) or not _UF.fullmatch(uf)
            or not isinstance(atualizacao, str)
            or not isinstance(clima, list) or not 1 <= len(clima) <= dias):
        raise ErroPrevisaoCPTEC("estrutura de previsão inválida")
    try:
        date.fromisoformat(atualizacao)
    except ValueError:
        raise ErroPrevisaoCPTEC("data de atualização inválida") from None
    out, vistos = [], set()
    for row in clima:
        if not isinstance(row, dict) or not isinstance(row.get("data"), str):
            raise ErroPrevisaoCPTEC("linha de previsão inválida")
        try:
            dt = date.fromisoformat(row["data"])
        except ValueError:
            raise ErroPrevisaoCPTEC("data prevista inválida") from None
        if dt.isoformat() in vistos:
            raise ErroPrevisaoCPTEC("dia de previsão duplicado")
        vistos.add(dt.isoformat())
        mini, maxi = _temperatura(row.get("min")), _temperatura(row.get("max"))
        if mini > maxi:
            raise ErroPrevisaoCPTEC("máxima inferior à mínima")
        condicao = row.get("condicao")
        if not isinstance(condicao, str) or not condicao or len(condicao) > 40:
            raise ErroPrevisaoCPTEC("condição de tempo inválida")
        uv = row.get("indice_uv")
        # UV zerado tem relatos de inconsistência no agregador; não homologar.
        uv_valido = (isinstance(uv, (int, float)) and not isinstance(uv, bool)
                     and math.isfinite(uv) and 0 < uv <= 25)
        out.append({
            "dia_previsto": dt.isoformat(),
            "temp_min_c": mini,
            "temp_max_c": maxi,
            "condicao_cptec": condicao,
            "indice_uv_reportado": uv if uv_valido else None,
            "uv_validado_independentemente": False,
            "natureza": "PROJETADO",
        })
    return {
        "fonte_primaria": "CPTEC/INPE",
        "provedor": "BrasilAPI",
        "dataset_id": "CPTEC_PREVISAO_CIDADE",
        "codigo_cptec": codigo_cptec,
        "codigo_ibge": None,
        "cidade": cidade.strip(),
        "uf": uf,
        "data_atualizacao_fonte": atualizacao,
        "previsoes": sorted(out, key=lambda r: r["dia_previsto"]),
        "frescor_verificado": False,
        "homologado": False,
        "publicavel": False,
        "coleta_agendada": False,
    }


def consultar_previsao(*, codigo_cptec: int, dias: int = 3, habilitar_rede: bool = False,
                      transporte=None, timeout: int = 12) -> dict:
    req = preparar_consulta(codigo_cptec=codigo_cptec, dias=dias)
    if not habilitar_rede:
        raise PermissionError("previsão CPTEC exige opt-in de rede")
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ErroPrevisaoCPTEC("timeout inválido")
    opener = transporte or build_opener(_BloquearRedirecionamento)
    try:
        with opener.open(req, timeout=timeout) as response:
            if getattr(response, "status", None) != 200:
                raise ErroPrevisaoCPTEC("resposta CPTEC sem HTTP 200")
            payload = response.read(LIMITE_BYTES + 1)
    except (HTTPError, URLError, OSError):
        raise ErroPrevisaoCPTEC("serviço CPTEC/BrasilAPI não validado") from None
    return normalizar_previsao(payload, codigo_cptec=codigo_cptec, dias=dias)
