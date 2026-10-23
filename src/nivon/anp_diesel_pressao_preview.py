"""Conexão conservadora entre ANP diesel de revenda e custo hipotético de frota.

Não usa preço de posto como preço efetivamente pago pela transportadora;
não calcula repasse ou média municipal de fretes. Preview interno apenas.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import sqlite3

from .anp_lpc_staging_real import tendencia_diesel_preliminar
from .diesel_pressao import sensibilidade_diesel


def impacto_diesel_anp_preliminar(
    db: sqlite3.Connection, *, municipio: str, produto: str, as_of: str,
    distancia_operacional_km: Decimal,
    consumo_estimado_l_km: Decimal,
    carga_por_viagem_t: Decimal,
    distancia_validada: bool,
    premissas_documentadas: bool,
) -> dict:
    """Estima somente variação de custo de combustível hipotética, sem frete."""
    trend = tendencia_diesel_preliminar(
        db, municipio=municipio, produto=produto, as_of=as_of)
    if trend["status"] != "COMPARACAO_PRELIMINAR":
        return {
            "status": "INSUFICIENTE_PARA_CENARIO_DE_CUSTO",
            "motivo": trend["status"], "publicavel": False,
            "natureza": "ANP_PRELIMINAR_NAO_HOMOLOGADA",
            "repasse_ao_frete": "INDETERMINADO",
        }
    model = sensibilidade_diesel(
        distancia_operacional_km=distancia_operacional_km,
        consumo_estimado_l_km=consumo_estimado_l_km,
        carga_por_viagem_t=carga_por_viagem_t,
        preco_diesel_base_brl_l=Decimal(
            trend["preco_revenda_anterior_rs_l"]),
        preco_diesel_cenario_brl_l=Decimal(
            trend["preco_revenda_atual_rs_l"]),
        distancia_validada=distancia_validada,
        fonte_preco="ANP_LPC_MEDIA_AMOSTRAL_MUNICIPAL_REVENDA",
        referencia_preco=date.fromisoformat(trend["semana_atual"]),
        produto_diesel="DIESEL_S10" if produto=="DIESEL S10" else "DIESEL",
        premissas_documentadas=premissas_documentadas,
    )
    return {
        **model,
        "status": "CENARIO_HIPOTETICO_PRELIMINAR",
        "municipio":municipio,"uf":"MT",
        "semana_anterior":trend["semana_anterior"],
        "semana_atual":trend["semana_atual"],
        "sha256_anterior":trend["sha256_anterior"],
        "sha256_atual":trend["sha256_atual"],
        "indicador_preco":"ANP_PRECO_MEDIO_AMOSTRAL_DIESEL_B_MUNICIPIO",
        "dados_homologados":False,
        "frete_negociado":False,"frete_anunciado":False,
        "publicavel":False,
        "aviso":"Análise de sensibilidade, não preço pago/repasse ao frete.",
    }
