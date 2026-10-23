"""Painel 2025 com camadas ferroviária e rodoviária oficiais separadas.

Rodo: apenas top-16 anual RGI, sem produto. Ferrovia: origem de estação.
Correspondência de nome RGI/estação é sinal geográfico, NAO transbordo.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import unicodedata

from .antt_rodovia_rgi_gcp import PROJECT, DATASET
from .transporte_multimodal import ErroTransporte

POLOS = (
    ("MT_RONDONOPOLIS_FERRO","Rondonópolis","MT"),
    ("MT_ITIQUIRA_FERRO","Itiquira","MT"),
    ("MT_ALTO_ARAGUAIA_FERRO","Alto Araguaia","MT"),
    ("MT_DOM_AQUINO_BR070","Dom Aquino","MT"),
    ("PA_MIRITITUBA_HIDRO","Itaituba","PA"),
    ("RO_PORTO_VELHO_HIDRO","Porto Velho","RO"),
    ("PA_SANTAREM_PORTO","Santarém","PA"),
    ("PA_BARCARENA_PORTO","Barcarena","PA"),
    ("AM_ITACOATIARA_PORTO","Itacoatiara","AM"),
)
POLORAIL = {p[0] for p in POLOS[:4]}

def _norm(txt: str) -> str:
    if not isinstance(txt,str): return ""
    return "".join(c for c in unicodedata.normalize("NFKD",txt.casefold())
                   if not unicodedata.combining(c)).strip()

def montar_relatorio(rodovia: list, ferrovia: list) -> dict:
    if len(rodovia)!=16:
        raise ErroTransporte("rodovia top16 oficial nao conciliada")
    chaves=set()
    top=[]
    total=0
    for row in rodovia:
        if (row.ano!=2025 or not isinstance(row.sha256,str) or len(row.sha256)!=64
                or str(row.granularidade)!="RGI"
                or str(row.escopo)!="TOP_16_FLUXOS_GERAIS_ANUAIS"
                or type(row.toneladas) is not int or row.toneladas<=0):
            raise ErroTransporte("RGI nao compativel com prova oficial")
        chave=(row.origem_uf,row.origem_rgi,row.destino_uf,row.destino_rgi)
        if chave in chaves: raise ErroTransporte("RGI par duplicado")
        chaves.add(chave)
        total+=row.toneladas
        top.append({
            "origem_uf":row.origem_uf,"origem_rgi":row.origem_rgi,
            "destino_uf":row.destino_uf,"destino_rgi":row.destino_rgi,
            "toneladas_top16":str(row.toneladas),"sha256_fonte":row.sha256,
            "escopo":"TOP_16_FLUXOS_GERAIS_ANUAIS",
            "produto":None,"transbordo_confirmado":False,
        })
    if total!=98170287 or len({r["sha256_fonte"] for r in top})!=1:
        raise ErroTransporte("top16 alterado sem nova conciliacao")
    fer={}
    for r in ferrovia:
        if r.polo_id not in POLORAIL or r.polo_id in fer:
            raise ErroTransporte("polo ferroviario nao homologado/duplicado")
        tu=Decimal(str(r.tu))
        if not tu.is_finite() or tu<0:raise ErroTransporte("TU ferroviaria invalida")
        fer[r.polo_id]=str(tu)
    if {p[0] for p in POLOS[:3]}-set(fer):
        raise ErroTransporte("faltam polos ferroviarios com dados reais")
    if (Decimal(fer["MT_RONDONOPOLIS_FERRO"])!=Decimal("24258027")
            or Decimal(fer["MT_ITIQUIRA_FERRO"])!=Decimal("742649")
            or Decimal(fer["MT_ALTO_ARAGUAIA_FERRO"])!=Decimal("1458596")):
        raise ErroTransporte("base 2025 ferroviaria mudou: revisar antes de publicar")
    items=[]
    for id_,nome,uf in POLOS:
        chegadas=[r for r in top if r["destino_uf"]==uf and _norm(r["destino_rgi"])==_norm(nome)]
        saidas=[r for r in top if r["origem_uf"]==uf and _norm(r["origem_rgi"])==_norm(nome)]
        items.append({
            "polo_id":id_,"nome_polo":nome,"uf":uf,
            "ferrovia_origem_ton_2025":fer.get(id_),
            "ferrovia_escopo":"ANTT_SIADE_ESTACAO_ORIGEM" if id_ in fer else "SEM_DADO_FERROVIARIO_NESTE_RECORTE",
            "rodovia_rgi_top16_entradas":chegadas,
            "rodovia_rgi_top16_saidas":saidas,
            "rodovia_status":"PARCIAL_TOP16_ANUAL_GERAL",
            "correspondencia_geografica":"MESMO_NOME_RGI_NAO_COMPROVA_TERMINAL",
            "hidrovia_status":"SEM_MICRODADO_OFICIAL_ANTAQ_HOMOLOGADO_NESTE_BQ",
            "transbordo_confirmado":False,
            "somar_ferrovia_rodovia_hidrovia":False,
        })
    return {
        "estado":"PAINEL_MULTIMODAL_2025_DADOS_SEPARADOS_COM_PROVENIENCIA",
        "ano":2025,"projeto":PROJECT,"dataset":DATASET,
        "fontes":[
            {"fonte":"ANTT_SIADE","modal":"FERROVIA",
             "granularidade":"ESTACAO_ORIGEM","produto_na_fonte":True},
            {"fonte":"ANTT_ANUARIO_TRC_2025_TABELA_12","modal":"RODOVIA",
             "granularidade":"REGIAO_GEOGRAFICA_IMEDIATA","produto_na_fonte":False},
            {"fonte":"ANTAQ_MICRODADOS_PRIMARIOS","modal":"HIDROVIA",
             "estado":"NAO_DISPONIVEL_NO_BQ_NIVON"},
        ],
        "escopo_top16_rodoviario_toneladas":str(total),
        "escopo_top16_e_total_nacional":False,
        "rodovia_rgi_fluxos_top16":sorted(top,key=lambda r:-int(r["toneladas_top16"])),
        "polos":items,
        "transbordos_efetivos_identificados":False,
        "totais_das_modalidades_somaveis":False,
        "avisos":["RGI nao e municipio nem terminal",
                  "SIADE ferroviario e por estacao, nao entrega rodoviaria",
                  "Falta base ANTAQ oficial e MDF-e OD mensal/produto",
                  "Fretes anunciados ou negociados nao inferidos"],
    }

def consultar(*, cliente=None,sdk=None):
    if cliente is None:
        from google.cloud import bigquery as sdk
        cliente=sdk.Client(project=PROJECT)
    elif sdk is None:raise ErroTransporte("SDK de teste requerido")
    cfg=sdk.QueryJobConfig(maximum_bytes_billed=70_000_000)
    q=chr(96)
    rod=f"{PROJECT}.{DATASET}.vw_antt_rodovia_rgi_top16_atual"
    rail=f"{PROJECT}.{DATASET}.vw_nivon_corredores_ferrovia_mensal"
    sql_rodo=(f"SELECT ano,origem_uf,origem_rgi,destino_uf,destino_rgi,"
              f"toneladas,sha256,granularidade,escopo FROM {q}{rod}{q} "
              "WHERE ano=2025 AND data_referencia=DATE '2025-12-31' "
              "ORDER BY toneladas DESC LIMIT 17")
    sql_ferro=(f"SELECT polo_id,CAST(SUM(toneladas_uteis) AS STRING) AS tu "
               f"FROM {q}{rail}{q} "
               "WHERE data_referencia BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' "
               "GROUP BY polo_id ORDER BY polo_id")
    rows_rodo=list(cliente.query(sql_rodo,job_config=cfg).result(timeout=90))
    rows_ferro=list(cliente.query(sql_ferro,job_config=cfg).result(timeout=90))
    return montar_relatorio(rows_rodo,rows_ferro)

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--saida",required=True)
    a=ap.parse_args(argv)
    try:
        result=consultar()
        p=Path(a.saida)
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        print(json.dumps({"estado":result["estado"],
            "top16_rodoviario_toneladas":result["escopo_top16_rodoviario_toneladas"],
            "polos":len(result["polos"]),
            "cruzamentos":sum(bool(p["rodovia_rgi_top16_entradas"] or p["rodovia_rgi_top16_saidas"])
                             for p in result["polos"])},ensure_ascii=False))
        return 0
    except (ErroTransporte,ValueError,OSError) as exc:
        import sys
        print(json.dumps({"estado":"PAINEL_BLOQUEADO","motivo":str(exc)[:200]},
                         ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
