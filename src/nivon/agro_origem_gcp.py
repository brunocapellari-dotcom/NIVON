"""Coleta direta CEPEA, IMEA, CONAB e entrega ao ledger RAW NIVON.

Reutiliza normalizadores já auditados e o mesmo gravar_lote/arquivo_raw_gcs
do núcleo. IMEA e safras CONAB sem data_referencia continuam QUARANTINED.
Arquivos do agrobr são snapshots semânticos, NÃO bytes HTTP originais.
Nenhum mecanismo de coleta altera a tabela BigQuery por conta própria.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

from .cepea_web_primario import (
    URL_MILHO, URL_SOJA, consultar_pagina_primaria, extrair_precos_html,
)
from .imea_lotes import prepare as preparar_imea
from .conab_job import edicoes_atuais, registros_publicacao
from .ingestao_fontes_reais import gravar_lote

FONTES = ("CEPEA_SOJA", "CEPEA_MILHO", "IMEA", "CONAB")
CADEIAS_IMEA = ("soja", "milho", "algodao", "bovinocultura")
REGISTRO = {
    "CEPEA_SOJA": ("CEPEA_PRECOS_FISICOS", URL_SOJA, ("soja_paranagua", "soja_parana")),
    "CEPEA_MILHO": ("CEPEA_PRECOS_FISICOS", URL_MILHO, ("milho_esalq_b3",)),
}
PUBLICACAO_SEM_REFERENCIA = "PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"


class ErroAgroOrigem(ValueError):
    pass


def _utc(agora):
    now = agora if agora is not None else datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ErroAgroOrigem("data de coleta sem timezone")
    return now.astimezone(timezone.utc)


def _json_bytes(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, default=str,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _guardar(base, ds, url, payload, registros, estado, agora, tipo="application/json"):
    if not registros:
        raise ErroAgroOrigem("coleta sem registros validados")
    base = Path(base)
    return gravar_lote(
        banco=base/"fontes_reais.sqlite", diretorio_bruto=base/"raw",
        dataset_id=ds, origem=url, raw=payload, tipo=tipo,
        coletado_em=agora.isoformat(), registros=registros, estado=estado)


def coletar_cepea(*, fonte, base, agora=None, abrir=None,
                  homologacao_referencia=False):
    """Página original + validador legado; normalização CEPEA apenas opt-in."""
    if fonte not in REGISTRO:
        raise ErroAgroOrigem("CEPEA: fonte desconhecida")
    instante = _utc(agora)
    ds, url, series = REGISTRO[fonte]
    if abrir is None:
        html = consultar_pagina_primaria(url)
    else:
        html = consultar_pagina_primaria(url, open_url=abrir)
    observacoes = extrair_precos_html(
        html, series, hoje=instante.date(), coleta=instante)
    registros = []
    for x in observacoes:
        if x["data_publicacao"] is not None:
            raise ErroAgroOrigem("CEPEA: publicação não verificada")
        campos = {**x, "proveniencia": "PAGINA_PRIMARIA_CEPEA",
                  "publicacao_nao_inferida": True,
                  "promocao_analitica_aprovada": bool(homologacao_referencia)}
        registros.append({
            "identidade": x["serie_id"]+"|"+x["data_referencia"],
            "referencia": x["data_referencia"],
            "competencia": x["competencia"],
            "publicacao": None,
            "natureza": "INFORMADO",
            "valor": x["valor"],
            "unidade": x["unidade"],
            "campos": campos})
    # HTML extraído completo (sem bytes HTTP originais); não simular JSON de preços.
    raw = html.encode("utf-8")
    estado = "NORMALIZED" if homologacao_referencia else "QUARANTINED"
    salvo = _guardar(base, ds, url, raw, registros, estado, instante, "text/html")
    return {"fonte": fonte, "dataset": ds, "estado": estado,
            "quantidade": len(registros), "novos": salvo["novas_observacoes"],
            "snapshot_id": salvo["snapshot_id"],
            "referencia_verificada": True, "publicacao_verificada": False,
            "fonte_http_bruto_original": False, "bigquery_executado": False}


async def coletar_imea(*, base, agora=None, cliente=None, cadeias=CADEIAS_IMEA):
    """Adaptador agrobr/IMEA: todas as métricas sem data-referência em staging."""
    instante = _utc(agora)
    if not cadeias or any(c not in CADEIAS_IMEA for c in cadeias):
        raise ErroAgroOrigem("cadeia IMEA inválida")
    if cliente is None:
        from agrobr import imea as cliente
    saidas = []
    for chain in cadeias:
        tabela, meta = await cliente.cotacoes(chain, return_meta=True)
        lote = preparar_imea(tabela.to_dict(orient="records"), meta, chain)
        registros = []
        for original in (row for batch in lote["batches"] for row in batch):
            if original["reference_date"] is not None:
                raise ErroAgroOrigem("IMEA: referência inesperada no contrato")
            pub = original["published_at"]
            # Representação técnica exigida pelo ledger SQLite, NUNCA referência.
            tecnica = date.fromisoformat(str(pub)[:10]).isoformat()
            if tecnica > instante.date().isoformat():
                raise ErroAgroOrigem("IMEA: publicação futura")
            campos = {**original, "data_referencia": None,
                      "data_ancora_tecnica": tecnica,
                      "tipo_referencia": PUBLICACAO_SEM_REFERENCIA,
                      "original_http_bytes": False}
            registros.append({
                "identidade": original["source_key"]+"|"+original["version_hash"],
                "referencia": tecnica, "publicacao": pub,
                "competencia": original.get("crop_year"),
                "natureza": "INFORMADO", "valor": original["value"],
                "unidade": original["unit"], "campos": campos})
        # Payload semântico versionado de retorno agrobr, não arquivo HTTP original.
        raw = _json_bytes({
            "fonte": "IMEA", "origem": lote["source_url"],
            "chain": chain, "colecao": "AGROBR_RESULTADO_NORMALIZADO",
            "linhas": [row for batch in lote["batches"] for row in batch]})
        salvo = _guardar(base, "IMEA_PUBLICACOES_STAGING", lote["source_url"],
                         raw, registros, "QUARANTINED", instante)
        saidas.append({"cadeia": chain, "quantidade": len(registros),
                       "novos": salvo["novas_observacoes"],
                       "snapshot_id": salvo["snapshot_id"],
                       "ultima_publicacao": lote["last_publication"],
                       "referencia_verificada": False})
    return {"fonte": "IMEA", "dataset": "IMEA_PUBLICACOES_STAGING",
            "estado": "QUARANTINED", "cadeias": saidas,
            "bigquery_canonico": False, "raw_http_original": False}


async def coletar_conab(*, base, agora=None, cliente=None, limite=2):
    """CONAB safras MT edições explícitas, sem inventar data de referência."""
    instante = _utc(agora)
    if cliente is None:
        from agrobr import conab as cliente
    edicoes = await edicoes_atuais(cliente, limite=limite, hoje=instante.date())
    saidas = []
    for edicao in edicoes:
        origin = edicao["url"]
        linhas = await registros_publicacao(cliente, edicao)
        if len(linhas) != 2:
            raise ErroAgroOrigem("CONAB: duas métricas soja/milho obrigatórias")
        registros = []
        for x in linhas:
            pub = x["publication_date"]
            if str(pub) != edicao["data_publicacao"]:
                raise ErroAgroOrigem("CONAB: publicação divergente")
            met = x["metric"]
            produto = met["produto"]
            ref_tec = date.fromisoformat(str(pub)).isoformat()
            campos = {**x, "data_referencia": None,
                      "data_ancora_tecnica": ref_tec,
                      "tipo_referencia": PUBLICACAO_SEM_REFERENCIA,
                      "original_http_bytes": False}
            registros.append({
                "identidade": f'{edicao["safra"]}|{edicao["levantamento"]}|{produto}|MT',
                "referencia": ref_tec,
                "competencia": edicao["safra"], "publicacao": pub+"T00:00:00Z",
                "natureza": "INFORMADO", "unidade": "MULTIPLAS_METRICAS",
                "valor": None, "campos": campos})
        raw = _json_bytes({
            "fonte": "CONAB", "origem": origin,
            "colecao": "AGROBR_RESULTADO_NORMALIZADO",
            "edicao": edicao, "registros": linhas})
        salvo = _guardar(base, "CONAB_SAFRAS_STAGING", origin, raw, registros,
                         "QUARANTINED", instante)
        saidas.append({"safra": edicao["safra"],
                       "levantamento": edicao["levantamento"],
                       "quantidade": len(registros),
                       "novos": salvo["novas_observacoes"],
                       "snapshot_id": salvo["snapshot_id"],
                       "referencia_verificada": False})
    return {"fonte": "CONAB", "dataset": "CONAB_SAFRAS_STAGING",
            "estado": "QUARANTINED", "edicoes": saidas,
            "bigquery_canonico": False, "raw_http_original": False}


def executar(*, fonte, base, agora=None, cliente=None, serie=None,
             homologacao_referencia=False):
    """Entry point único para CLI: não faz GCS/BigQuery implicitamente."""
    if fonte not in FONTES:
        raise ErroAgroOrigem("fonte desconhecida")
    if fonte.startswith("CEPEA_"):
        return coletar_cepea(fonte=fonte, base=base, agora=agora,
                            abrir=cliente,
                            homologacao_referencia=homologacao_referencia)
    if homologacao_referencia:
        raise ErroAgroOrigem("homologação CEPEA não aplicável à IMEA/CONAB")
    if fonte == "IMEA":
        return asyncio.run(coletar_imea(
            base=base, agora=agora, cliente=cliente,
            cadeias=(serie,) if serie else CADEIAS_IMEA))
    return asyncio.run(coletar_conab(base=base, agora=agora, cliente=cliente))
