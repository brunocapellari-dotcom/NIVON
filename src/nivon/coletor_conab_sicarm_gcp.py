"""SICARM/CONAB official registered warehouses -> conservative RAW quarantine.

Uses existing NIVON SICARM parser + quality gate; only aggregates per
municipality can reach local staging. Original raw includes identifiable
records: GCS bucket must be private, restricted and retention-controlled.
Never infer storage occupancy, inventory or actual product movements.
"""
from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .conab_armazens import LAYOUT_CONAB_SICARM_HEADER_V1, agregar_capacidade_local
from .qualidade_conab_armazens import verificar_consistencia_armazens
from .ingestao_fontes_reais import gravar_lote

URL_OFICIAL = "https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt"
MAX_BYTES = 120_000_000
_OPERACOES = frozenset({"COLETA","ARMAZENAMENTO","USO_INTERNO"})


class ErroConabRemoto(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def coletar_conab_armazens(*, base: str | Path,
                           autorizacoes: frozenset[str]=frozenset(),
                           evidencia: str | None=None, executar: bool=False,
                           abridor=None, instante: datetime | None=None) -> dict:
    if executar is not True or not _OPERACOES <= set(autorizacoes):
        raise PermissionError("SICARM: permitir COLETA, ARMAZENAMENTO, USO_INTERNO")
    if not isinstance(evidencia,str) or len(evidencia.strip())<10:
        raise PermissionError("SICARM: registrar direito de acesso/uso")
    now=instante or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ErroConabRemoto("coleta precisa de timezone")
    coleta=now.astimezone(timezone.utc).isoformat()
    cliente=abridor if abridor is not None else build_opener(_SemRedirect())
    req=Request(URL_OFICIAL,headers={
        "Accept":"text/plain,application/octet-stream",
        "User-Agent":"NIVON/0.1 (data collection, public official source)"})
    with cliente.open(req,timeout=45) as resp:
        if int(resp.status)!=200 or resp.geturl()!=URL_OFICIAL:
            raise ErroConabRemoto("HTTP/redirect fora da origem oficial")
        mime=str(resp.headers.get("Content-Type","")).split(";",1)[0].lower().strip()
        if mime not in ("text/plain","application/octet-stream","text/csv"):
            raise ErroConabRemoto("MIME divergente do TXT SICARM")
        raw=resp.read(MAX_BYTES+1)
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:
        raise ErroConabRemoto("SICARM vazio ou maior que 120 MB")
    if raw.lstrip().lower().startswith((b"<html",b"<!doctype",b"request rejected")):
        raise ErroConabRemoto("origem retornou HTML/WAF em vez de tabela")
    with tempfile.TemporaryDirectory() as scratch:
        arq=Path(scratch)/"sicarm.txt"
        arq.write_bytes(raw)
        resumo=agregar_capacidade_local(
            arq,LAYOUT_CONAB_SICARM_HEADER_V1,
            coletado_em=coleta,referencia=None,publicacao=None)
    resultado_qa=verificar_consistencia_armazens(resumo)
    if resultado_qa["estado"]!="CONSISTENCIA_INTERNA_OK_SEM_HOMOLOGACAO":
        raise ErroConabRemoto("QA municipal nao passou")
    # No official reference date is available here. Collection date is
    # a technical placeholder only, never a claimed effective-date vintage.
    rows=[]
    for item in resumo["agregados"]:
        rows.append({
            "identidade":"|".join((item["uf"],item["municipio_normalizado"])),
            "referencia":coleta[:10],"competencia":coleta[:7],
            "publicacao":None,"natureza":"INFORMADO","unidade":"t",
            "valor":item["capacidade_estatica_t"],
            "campos":{
                **item,
                "fonte":"CONAB_SICARM","valor_canonico":item["capacidade_estatica_t"],
                "referencia_tecnica_da_coleta_nao_vigencia":True,
                "ocupacao_ou_estoque":None,
                "status": "QUARENTENA_SEM_RECONCILIACAO_IBGE",
                "QA_interna_ok":True,
            },
        })
    base=Path(base)
    gravado=gravar_lote(
        banco=base/"fontes_reais.sqlite",diretorio_bruto=base/"raw",
        dataset_id="CONAB_ARMAZENS_CAPACIDADE",
        origem=URL_OFICIAL,raw=raw,tipo="application/octet-stream",
        coletado_em=coleta,registros=rows,estado="QUARANTINED")
    return {
        "fonte":"CONAB","dataset":"CONAB_ARMAZENS_CAPACIDADE",
        "status":"RAW_E_AGREGADOS_EM_QUARENTENA",
        "municipios":len(rows),"linhas_armazens":resumo["linhas_validas"],
        "capacidade_cadastrada_t":resumo["capacidade_total_t"],
        "novas_observacoes":gravado["novas_observacoes"],
        "snapshot_id":gravado["snapshot_id"],
        "sha256":gravado["sha256"],
        "marco_temporal":"DATA_COLETA_NAO_REFERENCIA_PUBLICACAO",
        "homologado":False,"bigquery_canonico":False,
    }
