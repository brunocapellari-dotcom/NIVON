"""INMET: inventário público de estações, sem API privada BDMEP.

Somente GET pontual do catálogo /estacoes/T ou /estacoes/M, nunca
endpoint horário protegido. Sem rede por padrão, download ou agendamento.
Não confundir status da estação com observação meteorológica corrente.
"""
from __future__ import annotations

import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = "https://apitempo.inmet.gov.br"
LIMITE_BYTES = 2_500_000
_MAX_ESTACOES = 5000
_CODIGO = re.compile(r"[A-Z][0-9]{3}\Z")
_UF = re.compile(r"[A-Z]{2}\Z")


class ErroCatalogoINMET(ValueError):
    """Erro de domínio sem registrar URL, cabeçalhos ou payload."""


class _BloquearRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def preparar_consulta(tipo: str) -> Request:
    if tipo not in ("T", "M"):
        raise ErroCatalogoINMET("tipo de estação não autorizado")
    return Request(BASE + "/estacoes/" + tipo, method="GET",
                   headers={"Accept": "application/json"})


def normalizar_catalogo(payload: bytes, *, tipo: str) -> list[dict]:
    if tipo not in ("T", "M") or not isinstance(payload, bytes) or not (0 < len(payload) <= LIMITE_BYTES):
        raise ErroCatalogoINMET("resposta INMET fora do contrato")
    try:
        entries = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroCatalogoINMET("JSON INMET inválido") from None
    if not isinstance(entries, list) or not (1 <= len(entries) <= _MAX_ESTACOES):
        raise ErroCatalogoINMET("lista de estações inválida")
    result, seen = [], set()
    for item in entries:
        if not isinstance(item, dict):
            raise ErroCatalogoINMET("registro de estação inválido")
        code, uf, nome = item.get("CD_ESTACAO"), item.get("SG_ESTADO"), item.get("DC_NOME")
        if (not isinstance(code, str) or not _CODIGO.fullmatch(code)
                or not isinstance(uf, str) or not _UF.fullmatch(uf)
                or not isinstance(nome, str) or not nome.strip() or len(nome) > 160
                or code in seen):
            raise ErroCatalogoINMET("metadados de estação inválidos ou duplicados")
        seen.add(code)
        try:
            lat = float(item["VL_LATITUDE"])
            lon = float(item["VL_LONGITUDE"])
        except (TypeError, ValueError, KeyError):
            raise ErroCatalogoINMET("coordenadas da estação inválidas") from None
        if not (math.isfinite(lat) and math.isfinite(lon) and -34 <= lat <= 6 and -74 <= lon <= -28):
            raise ErroCatalogoINMET("coordenadas fora do domínio brasileiro esperado")
        situacao = item.get("CD_SITUACAO")
        if situacao is not None and (not isinstance(situacao, str) or len(situacao) > 80):
            raise ErroCatalogoINMET("situação da estação inválida")
        result.append({
            "fonte": "INMET",
            "dataset_id": "INMET_CATALOGO_ESTACOES",
            "tipo_catalogo": tipo,
            "codigo_estacao": code,
            "nome_estacao": nome.strip(),
            "uf": uf,
            "latitude": lat,
            "longitude": lon,
            "situacao_reportada": situacao,
            "inicio_operacao_fonte": item.get("DT_INICIO_OPERACAO"),
            "fim_operacao_fonte": item.get("DT_FIM_OPERACAO"),
            "natureza": "METADADO_DE_ESTACAO",
            "observacao_meteorologica": False,
            "homologado": False,
            "publicavel": False,
        })
    return result


def consultar_catalogo(*, tipo: str = "T", habilitar_rede: bool = False,
                       transporte=None, timeout: int = 12) -> list[dict]:
    req = preparar_consulta(tipo)
    if not habilitar_rede:
        raise PermissionError("requisição pública INMET exige opt-in")
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ErroCatalogoINMET("timeout inválido")
    opener = transporte or build_opener(_BloquearRedirecionamento)
    try:
        with opener.open(req, timeout=timeout) as response:
            if getattr(response, "status", None) != 200:
                raise ErroCatalogoINMET("resposta INMET sem HTTP 200")
            raw = response.read(LIMITE_BYTES + 1)
    except (HTTPError, URLError, OSError):
        raise ErroCatalogoINMET("catálogo público INMET não validado") from None
    return normalizar_catalogo(raw, tipo=tipo)
