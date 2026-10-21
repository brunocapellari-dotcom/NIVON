"""CEMADEN PED: acumulados recentes de uma cidade IBGE, somente com JWT autorizado.

Swagger oficial: https://sws.cemaden.gov.br/PED/api/ui/swagger.json
Este conector NÃO cria token, solicita autorização, agenda histórico ou
varre a rede. Somente uma leitura explícita: /pcds-acum/acumulados-recentes.
Token acessado exclusivamente por env do executor, nunca em query/log.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

_BASE = "https://sws.cemaden.gov.br/PED/rest/pcds-acum/acumulados-recentes"
_ACC = ("acc1hr", "acc3hr", "acc6hr", "acc12hr", "acc24hr", "acc48hr", "acc72hr")
_MAX_BYTES = 180_000
_MAX_ITEMS = 500


class ErroCemaden(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def construir_requisicao(*, codigo_ibge: str, token: str) -> Request:
    # Portal CEMADEN exige identificador municipal IBGE de sete dígitos.
    if not isinstance(codigo_ibge, str) or not re.fullmatch(r"[0-9]{7}", codigo_ibge):
        raise ErroCemaden("código IBGE inválido")
    if not isinstance(token, str) or not 20 <= len(token) <= 8192 or any(c.isspace() for c in token):
        raise ErroCemaden("JWT CEMADEN indisponível ou com formato inválido")
    return Request(_BASE + "?" + urlencode({"codibge": codigo_ibge, "formato": "JSON"}),
                   method="GET", headers={"token": token, "Accept": "application/json"})


def normalizar_acumulados(payload: bytes, *, codigo_ibge: str) -> dict:
    if not isinstance(codigo_ibge, str) or not re.fullmatch(r"[0-9]{7}",codigo_ibge):
        raise ErroCemaden("código IBGE inválido")
    if not isinstance(payload, bytes) or not 0 < len(payload) <= _MAX_BYTES:
        raise ErroCemaden("resposta CEMADEN fora do limite")
    try:
        doc = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        raise ErroCemaden("JSON CEMADEN inválido") from None
    # Dado bruto CEMADEN pode vir vazio para municípios sem cobertura.
    if not isinstance(doc, list) or len(doc) > _MAX_ITEMS:
        raise ErroCemaden("schema de acumulados CEMADEN inesperado")
    out, seen = [], set()
    for line in doc:
        if not isinstance(line, dict) or str(line.get("codibge")) != codigo_ibge:
            raise ErroCemaden("registro CEMADEN não pertence ao município solicitado")
        station=line.get("codestacao")
        stamp=line.get("datahora")
        if not isinstance(station, str) or not re.fullmatch(r"[0-9A-Za-z]{5,20}", station):
            raise ErroCemaden("código de estação CEMADEN inválido")
        if not isinstance(stamp, str) or len(stamp) > 40:
            raise ErroCemaden("data de leitura CEMADEN inválida")
        try:
            # Conservar o instante bruto. Não presumir offset em datahora
            # sem validar o contrato real do provedor.
            parsed = datetime.fromisoformat(stamp.replace("Z","+00:00"))
        except ValueError:
            raise ErroCemaden("timestamp CEMADEN inválido") from None
        key=(station,stamp)
        if key in seen:
            raise ErroCemaden("registro de estação duplicado")
        seen.add(key)
        acc={}
        for name in _ACC:
            val=line.get(name)
            if val is None:
                acc[name]=None
            elif isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not 0 <= val <= 3000:
                raise ErroCemaden("acumulado pluviométrico fora do domínio")
            else:
                acc[name]=float(val)
        out.append({
            "codigo_estacao_cemaden": station,
            "codigo_municipio_ibge": codigo_ibge,
            "data_hora_fonte":stamp,
            "timestamp_com_offset":parsed.tzinfo is not None,
            "fuso_validado_independentemente":False,
            "acumulados_mm":acc,
            "natureza":"OBSERVADO_BRUTO_SEM_QC",
            "utilizar_para_modelo":False,
        })
    return {"fonte":"CEMADEN_PED", "dataset_id":"CEMADEN_CHUVA_ACUMULADA_RECENTE",
            "endpoint":"/PED/rest/pcds-acum/acumulados-recentes",
            "municipio_ibge":codigo_ibge, "registros":out,
            "data_coleta":None, "homologado":False, "publicavel":False,
            "coleta_agendada":False}


def consultar_acumulados(*, codigo_ibge: str, habilitar_rede=False, transporte=None):
    if not habilitar_rede:
        raise PermissionError("CEMADEN PED exige acesso explicitamente autorizado")
    token=os.environ.get("NIVON_CEMADEN_TOKEN","")
    req=construir_requisicao(codigo_ibge=codigo_ibge, token=token)
    client=transporte or build_opener(_SemRedirect)
    try:
        with client.open(req,timeout=12) as response:
            if getattr(response,"status",None)!=200:
                raise ErroCemaden("servidor CEMADEN não confirmou HTTP 200")
            data=response.read(_MAX_BYTES+1)
    except (HTTPError, URLError, OSError):
        raise ErroCemaden("consulta CEMADEN não autenticada ou indisponível") from None
    result=normalizar_acumulados(data,codigo_ibge=codigo_ibge)
    result["data_coleta"]=datetime.now(timezone.utc).isoformat()
    return result
