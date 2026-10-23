"""Plano de operação dos coletores NIVON: DRY-RUN, sem agendamento ou rede."""
from __future__ import annotations
import argparse
import json
from collections import Counter
from .catalogo_fontes import carregar_catalogo, ErroCatalogo

ORDER = {"P0":0,"P1":1,"P2":2}
CADENCE_RULE = {
    "HOURLY":"1h","SIX_HOURLY":"6h","TWICE_DAILY":"12h",
    "INTRADAY":"dentro_do_dia","DAILY":"diario","WEEKLY":"semanal",
    "BIWEEKLY":"quinzenal","MONTHLY":"mensal",
    "QUARTERLY":"trimestral","QUADRIMESTRAL":"quadrimestral",
    "ANNUAL":"anual","SEASONAL":"por_safra","IRREGULAR":"sob_evento",
}
WORKFLOW = [
    "source_identity", "licence_and_operation", "access_endpoint",
    "fetch_with_limits", "raw_hash_and_vintage", "schema_and_mime",
    "semantic_and_unit_tests", "normalize_observations",
    "reconciliation_and_quality", "persist_and_backup",
    "publication_with_freshness",
]


def plano(catalogo: dict, *, prioridade: str | None = None,
          grupo: str | None = None, incluir_restritas: bool = False) -> dict:
    if prioridade and prioridade not in ORDER:
        raise ErroCatalogo("prioridade inválida")
    fontes={f["id"]:f for f in catalogo["sources"]}
    out=[]
    for item in catalogo["datasets"]:
        if prioridade and item["priority"] != prioridade:continue
        if grupo and item["group"] != grupo:continue
        fonte=fontes[item["source_id"]]
        restrita=fonte["rights"]=="RESTRICTED" or item["stage"]=="BLOCKED_RIGHTS"
        if restrita and not incluir_restritas:continue
        if item["enabled"] or item["collection_authorized"]:
            raise ErroCatalogo("catálogo não permite rodar coletor sem gate")
        estado=(
            "PENDENTE_LICENCA" if restrita else
            "PENDENTE_PERSISTENCIA_DIREITOS" if item["stage"]=="REAL_SNAPSHOT_TESTED" else
            "PENDENTE_HOMOLOGACAO_PARSER" if item["stage"]=="CODE_PRESENT" else
            "PENDENTE_ENDPOINT_E_LAYOUT"
        )
        out.append({
            "dataset":item["id"],
            "origem":item["source_id"],
            "prioridade":item["priority"],
            "frequencia_proposta":CADENCE_RULE[item["cadence"]],
            "modo":item["mode"],
            "estado":estado,
            "executar":False,
            "etapas_necessarias":WORKFLOW,
        })
    out.sort(key=lambda x:(ORDER[x["prioridade"]],x["dataset"]))
    return {"coletores":len(out),"ativos":0,"sem_autorizacao_operacional":len(out),
            "por_estado":dict(sorted(Counter(d["estado"] for d in out).items())),
            "plano":out}


def main(argv=None):
    p=argparse.ArgumentParser(description="Plano NIVON: somente diagnóstico, sem coleta")
    p.add_argument("--prioridade",choices=sorted(ORDER))
    p.add_argument("--grupo")
    p.add_argument("--incluir-restritas",action="store_true")
    p.add_argument("--resumo",action="store_true")
    args=p.parse_args(argv)
    try:
        resultado=plano(carregar_catalogo(),prioridade=args.prioridade,
                        grupo=args.grupo,incluir_restritas=args.incluir_restritas)
        if args.resumo:
            resultado.pop("plano")
        print(json.dumps(resultado,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ErroCatalogo) as exc:
        print(json.dumps({"status":"PLANO_INVALIDO","motivo":str(exc)},ensure_ascii=False))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
