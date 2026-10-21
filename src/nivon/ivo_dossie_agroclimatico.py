"""IVO — dossiê intersetorial somente leitura de fatos com proveniência.

Conecta duas infraestruturas pré-existentes do NIVON: SQLite de edições CONAB
e SQLite de séries ANA/INMET. Não há junção espacial presumida, nem
equivalência entre safra e mês ou promoção de inferência para observado.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime,timezone

from .ivo_conab_bridge import consultar_safras_conab
from .ivo_ambiental_bridge import resumo_mensal_estacao_asof


class ErroDossie(ValueError):
    pass


def dossie_agroclimatico_asof(*,
    conab_db:sqlite3.Connection,
    ambiental_db:sqlite3.Connection,
    corte:datetime,
    arquivo_conab:str,
    uf:str,
    indicador_agricola:str,
    dataset_ambiental:str,
    estacao_id:str,
    metrica_ambiental:str,
    mes_ambiental:str,
)->dict:
    """Forma contexto para o agente IVO, SEM gerar recomendação numérica."""
    if not isinstance(corte,datetime) or corte.tzinfo is None or corte.utcoffset() is None:
        raise ErroDossie("corte as-of com timezone obrigatório")
    instante=corte.astimezone(timezone.utc)
    agricola=consultar_safras_conab(conab_db,arquivo=arquivo_conab,uf=uf,
                                   indicador=indicador_agricola,corte=instante)
    ambiental=resumo_mensal_estacao_asof(
        ambiental_db,dataset_id=dataset_ambiental,
        estacao_id=estacao_id,metrica=metrica_ambiental,mes=mes_ambiental,
        corte_publicacao=instante,corte_coleta=instante,
    )
    ambiente_ok=ambiental["estado"]=="CANDIDATO_MENSAL_COMPLETO_NAO_HOMOLOGADO"
    agro_ok=agricola["safras"]>0
    return {
        "estado":"DOSSIE_INTERSETORIAL_INFORMATIVO_NAO_HOMOLOGADO",
        "corte":instante.isoformat(),
        "agricultura":agricola,
        "ambiente":ambiental,
        "fontes_disponiveis":int(agro_ok)+int(ambiente_ok),
        "fontes_consultadas":2,
        "conexao_causal_demonstrada":False,
        "localizacao_estacao_na_uf_verificada":False,
        "conversao_safra_mes_realizada":False,
        "labels_agricolas_realizados_certificados":0,
        "treinamento_autonomo_habilitado":False,
        "previsao_intersetorial_homologada":False,
        "publicacao_comercial_autorizada":False,
        "aviso":(
            "O dossiê junta evidências, não séries temporal/geograficamente equivalentes. "
            "A CONAB informa/estima safras; a estação ambiental representa apenas "
            "seu ponto de medição. Georreferenciamento, direitos, confirmação "
            "de resultados, causalidade e backtest continuam obrigatórios."
        ),
    }
