"""Comparação TRIMODAL 2025 de universos SEPARADOS: ANTT rail/road + HF hidrovia.

Não concatena fluxos, não soma rios, não aloca cargas a terminais.
Só consulta BigQuery e dados de réplica HF validada, sem escrita Cloud.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

from .corredores_multimodais_2025 import consultar as consultar_bq
from .antaq_secundaria_gcp_2025 import (
    baixar_revisao_fixada, preparar_lote, HF_COMMIT,
)
from .antaq_replica_hidrovia import ErroReplicaANTAQ


def preparar_painel(antt: dict, recortes: list[dict], fonte: dict) -> dict:
    if (antt.get("ano") != 2025
            or antt.get("estado") != "PAINEL_MULTIMODAL_2025_DADOS_SEPARADOS_COM_PROVENIENCIA"
            or antt.get("totais_das_modalidades_somaveis") is not False
            or antt.get("escopo_top16_rodoviario_toneladas") != "98170287"
            or len(antt.get("polos", [])) != 9):
        raise ErroReplicaANTAQ("base rodoviaria/ferroviaria nao homologada")
    if (fonte.get("estado") != "REPLICA_ANTAQ_2025_APENAS_CAMADA_SECUNDARIA"
            or fonte.get("hf_revision") != HF_COMMIT
            or fonte.get("ano") != 2025
            or fonte.get("fonte_direta_antaq") is not False
            or not 1 <= len(recortes) <= 1200
            or len(recortes) != fonte.get("linhas_hidroviarias")):
        raise ErroReplicaANTAQ("recorte hidroviario fora da revisao auditada")
    if len(recortes) != 27:
        raise ErroReplicaANTAQ("revisao secundaria fixa alterou 27 grupos observados")
    rios = []
    chaves = set()
    for item in recortes:
        if (item["ano"] != 2025 or item["hf_revision"] != HF_COMMIT
                or item["snapshot_id"] != fonte["snapshot_id"]
                or item["sha256_hidrovia"] != fonte["sha256_hidrovia"]
                or item["sha256_carga"] != fonte["sha256_carga"]
                or item["dados_oficiais_antaq"] is not False
                or item["aditividade_entre_rios"] is not False
                or item["transbordo_confirmado"] is not False
                or item["navegacao"] != "Interior"):
            raise ErroReplicaANTAQ("replica nao permite comparacao trimodal")
        key=(item["hidrovia"],item["sentido"],item["grupo_produto"])
        if key in chaves:
            raise ErroReplicaANTAQ("grupo duplicado por rio/sentido/produto")
        chaves.add(key)
        tu = Decimal(item["toneladas_trechos"])
        if not tu.is_finite() or tu < 0:
            raise ErroReplicaANTAQ("toneladas de trecho invalidas")
        rios.append({
            "hidrovia":item["hidrovia"], "sentido":item["sentido"],
            "produto":item["grupo_produto"], "toneladas_trechos":str(tu),
            "unidade":"toneladas",
            "fonte":"HF_REPLICA_ANTAQ_HISTORICA",
            "classificacao":"DERIVADO_TERCEIRO_NAO_HOMOLOGADO",
            "transbordo_confirmado":False,
            "total_por_rio_aditivo":False,
        })
    rios.sort(key=lambda x: (x["hidrovia"],x["sentido"],x["produto"]))
    return {
        "estado":"PAINEL_TRIMODAL_2025_SEM_SOMA_ENTRE_MODALIDADES",
        "ano":2025,
        "projeto":"nivon-data",
        "fontes":{
            "ferrovia":"ANTT_SIADE_ESTACOES_ORIGEM",
            "rodovia":"ANTT_TR_CARGAS_2025_TOP16_RGI_TODOS_PRODUTOS",
            "hidrovia":"REPLICA_HF_ANT_AQ_2025_TERCEIRO_NAO_HOMOLOGADO",
        },
        "polos_rodovia_e_ferrovia":antt["polos"],
        "od_rodoviaria_top16":antt["rodovia_rgi_fluxos_top16"],
        "escopo_rodovia_top16_toneladas":antt["escopo_top16_rodoviario_toneladas"],
        "hidrovia_recortes":rios,
        "hidrovia_grupos":len(rios),
        "hidrovia_snapshot_sha":fonte["snapshot_id"],
        "hidrovia_hf_revision":HF_COMMIT,
        "hidrovia_cargas_interior_unicas_terceiro":fonte[
            "toneladas_navegacao_interior_idcarga_unica"],
        "hidrovia_com_localizacao_de_trecho_terceiro":fonte[
            "toneladas_com_hidrovia_identificada_idcarga_unica"],
        "gates":{
            "somar_rodovia_ferrovia_hidrovia":False,
            "somar_hidrovias_entre_si":False,
            "inferir_terminal_por_nome_de_rgi":False,
            "inferir_transbordos":False,
            "inferir_conteudo_caminhoes_sem_ncm":False,
            "aprovar_hidrovia_como_oficial":False,
            "gravar_google_cloud":False,
        },
        "observacao":"Dados de fontes e universos distintos; volumes em rios podem repetir IDCarga. Portos/terminais nao foram associados a transbordos."
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Comparar 3 modalidades em 2025 sem escrever GCP")
    p.add_argument("--saida",required=True)
    args=p.parse_args(argv)
    try:
        relatorio_antt=consultar_bq()   # apenas 2 SELECT limitados
        with TemporaryDirectory(prefix="nivon-hidrovia-terceiro-") as tmp:
            files=baixar_revisao_fixada(tmp)
            rows,meta=preparar_lote(
                files["hidrovia"], files["carga"],
                collected_at=datetime.now(timezone.utc))
        doc=preparar_painel(relatorio_antt,rows,meta)
        dest=Path(args.saida)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        print(json.dumps({
            "estado":doc["estado"],
            "polos_rodovia_ferrovia":len(doc["polos_rodovia_e_ferrovia"]),
            "recortes_hidrovia_secundaria":doc["hidrovia_grupos"],
            "escritas_cloud":0,
            "transbordos_confirmados":False,
        },ensure_ascii=False))
        return 0
    except (ErroReplicaANTAQ, ValueError, OSError) as exc:
        print(json.dumps({"estado":"PAINEL_TRIMODAL_NAO_HOMOLOGADO",
                          "motivo":str(exc)[:250]},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
