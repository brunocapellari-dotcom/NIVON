"""Adaptadores tipados de fontes prioritarias NIVON para o contrato de observacoes.

Funcoes de normalizacao sem rede: fonte coletada != fonte homologada.
Nao confunde publicacao/atualizacao, frete informado/negociado ou capacidade/estoque.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .bcb_sgs_selic import normalizar_selic_diaria
from .bcb_ptax import normalizar_ptax_odata
from .conab_armazens import LAYOUT_CONAB_SICARM_HEADER_V1, agregar_capacidade_local
from .qualidade_conab_armazens import verificar_consistencia_armazens
from .imea_legado_pipeline import preparar_lote as preparar_imea

CONAB_URL = "https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json"
_SUPPORTED = frozenset({
    "CONAB_ARMAZENS_CAPACIDADE", "BCB_SGS_TAXA_SELIC_DIARIA",
    "BCB_PTAX", "IMEA_WORKBOOK_LEGADO_STAGING",
})
MIME = {
    "CONAB_ARMAZENS_CAPACIDADE": "text/plain",
    "BCB_SGS_TAXA_SELIC_DIARIA": "application/json",
    "BCB_PTAX": "application/json",
    "IMEA_WORKBOOK_LEGADO_STAGING":
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class ErroFonteNuvem(ValueError):
    pass


def _timestamp(text: str) -> str:
    if not isinstance(text, str):
        raise ErroFonteNuvem("timestamp ausente")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroFonteNuvem("timestamp invalido") from exc
    if dt.utcoffset() is None:
        raise ErroFonteNuvem("timestamp sem timezone")
    return dt.astimezone(timezone.utc).isoformat()


def normalizar(dataset_id: str, raw: bytes, *, origem: str,
               coletado_em: str, publicado_em: str | None = None,
               referencia_oficial: str | None = None) -> dict:
    """Normaliza lote para carga em nuvem com proveniencia explicita."""
    if dataset_id not in _SUPPORTED:
        raise ErroFonteNuvem("dataset sem adaptador especifico")
    collected = _timestamp(coletado_em)
    if not isinstance(raw, bytes) or not raw:
        raise ErroFonteNuvem("RAW ausente")
    import hashlib
    sha = hashlib.sha256(raw).hexdigest()
    rows = []
    qa = {}
    if dataset_id == "CONAB_ARMAZENS_CAPACIDADE":
        if origem != CONAB_URL or len(raw) > 120_000_000:
            raise ErroFonteNuvem("CONAB URL ou tamanho nao homologado")
        # O parser existente necessita arquivo local; somente arquivo temporario.
        with tempfile.TemporaryDirectory(prefix="nivon-conab-") as pasta:
            arquivo = Path(pasta) / "sicarm.txt"
            arquivo.write_bytes(raw)
            agregado = agregar_capacidade_local(
                arquivo, LAYOUT_CONAB_SICARM_HEADER_V1,
                coletado_em=collected, referencia=referencia_oficial,
                publicacao=publicado_em)
        qualidade = verificar_consistencia_armazens(agregado)
        qa = {k:qualidade[k] for k in (
            "estado", "municipios", "armazens", "codigo_ibge_sem_resolucao",
            "referencia_oficial_homologada", "liberado_para_publicacao")}
        # Sem data oficial de corte, a referencia vira o dia do snapshot,
        # identificada como tal; NAO afirmar referencia de estoque ou ocupacao.
        for a in agregado["agregados"]:
            ref = referencia_oficial or collected[:10]
            fields = dict(a, fonte="CONAB", instrumento="SICARM",
                          referencia_tipo=("OFICIAL_INFORMADA" if referencia_oficial
                                          else "SNAPSHOT_DATA_COLETA_NAO_REFERENCIA_OFICIAL"),
                          capacidade_nao_estoque=True,
                          codigo_ibge_nao_homologado=a["codigo_ibge"] is None,
                          valor_canonico=a["capacidade_estatica_t"],
                          publicado_nao_verificado=publicado_em is None,
                          dominio="ARMAZENAGEM")
            rows.append({
                "identidade":f"SICARM|{a['uf']}|{a['municipio_normalizado']}",
                "referencia":ref, "competencia":ref[:7],
                "publicacao":publicado_em, "natureza":"INFORMADO",
                "unidade":"t", "valor":a["capacidade_estatica_t"],
                "campos":fields,
            })
    elif dataset_id == "BCB_SGS_TAXA_SELIC_DIARIA":
        if origem != SGS_URL or len(raw)>250_000:
            raise ErroFonteNuvem("BCB SGS endpoint/tamanho invalido")
        result=normalizar_selic_diaria(raw,coletado_em=collected)
        for d in result["observacoes"]:
            rows.append({
                "identidade":f"SGS11|{d['data_referencia']}",
                "referencia":d["data_referencia"],"competencia":d["competencia"],
                "publicacao":None,"natureza":"INFORMADO",
                "unidade":"PERCENTUAL_AO_DIA",
                "valor":d["valor_pct_ao_dia"],
                "campos":{"fonte":"BCB_SGS", "serie":11,
                          "valor_canonico":d["valor_pct_ao_dia"],
                          "taxa_diaria_nao_meta_selic_anual":True},
            })
        qa={"observacoes":len(rows),"publicacao_nao_informada":True}
    elif dataset_id == "BCB_PTAX":
        if len(raw)>1_000_000:
            raise ErroFonteNuvem("BCB PTAX resposta grande")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError,UnicodeError) as exc:
            raise ErroFonteNuvem("PTAX nao JSON") from exc
        result=normalizar_ptax_odata(data,moeda="USD",coletado_em=collected,
                                     consulta_url=origem)
        for d in result["observacoes"]:
            for lado, campo in (("COMPRA","cotacao_compra_brl_por_moeda"),
                                ("VENDA","cotacao_venda_brl_por_moeda")):
                date_key=d["referencia_data_hora_utc"][:10]
                value=d[campo]
                rows.append({
                    "identidade":f"PTAX|USD|{d['referencia_data_hora_utc']}|{d['tipo_boletim'] or 'SEM_TIPO'}|{lado}",
                    "referencia":date_key, "competencia":date_key[:7],
                    "publicacao":None,"natureza":"INFORMADO","unidade":"BRL/USD",
                    "valor":value,
                    "campos":{"fonte":"BCB_PTAX","moeda":"USD",
                              "data_hora_cotacao":d["referencia_data_hora_utc"],
                              "tipo_boletim":d["tipo_boletim"],
                              "lado":lado,"valor_canonico":value,
                              "nao_presumir_fechamento":True}
                })
        qa={"boletins":result["numero_de_boletins"],"lados":len(rows)}
    elif dataset_id == "IMEA_WORKBOOK_LEGADO_STAGING":
        lote=preparar_imea(raw,origem=origem,coletado_em=collected,
                           publicado_em=publicado_em)
        rows=lote["registros"]
        qa={"abas":lote["contagem_abas"],
            "status":"QUARENTENA_SEM_HOMOLOGACAO",
            "direitos_comerciais":False,
            "feed_primario_monitorado":False}
    if not rows:
        raise ErroFonteNuvem("fonte sem observacoes validas")
    return {
        "dataset_id":dataset_id,"origem":origem,"raw":raw,"sha256":sha,
        "tipo":MIME[dataset_id], "coletado_em":collected,"registros":rows,
        "qa":qa,"promovido_a_indicador":False,
        "publication_evidence_validated":False,
    }
