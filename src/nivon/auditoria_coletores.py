"""Auditoria estática de prontidão de coletores NIVON: 0 acesso de rede.

Inventário de bloqueios distinto do plano de coleta. Fonte listada, URL
institucional, código offline e direito de operação NÃO significam homologação.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from .catalogo_fontes import carregar_catalogo, validar_catalogo
from .rotas_coleta import carregar_rotas, validar_rotas

_ORDER = {"P0":0,"P1":1,"P2":2}


def auditoria_estatica(catalogo: dict, rotas: dict, *, prioridade: str | None=None) -> dict:
    """Audita todos os datasets canônicos, sem agendamento nem classificação otimista."""
    meta=validar_catalogo(catalogo)
    controle=validar_rotas(rotas,catalogo)
    if prioridade not in (None,"P0","P1","P2"):
        raise ValueError("prioridade inválida")
    fontes={f["id"]:f for f in catalogo["sources"]}
    entradas={e["dataset_id"]:e for e in rotas["entries"]}
    if len(entradas)!=len(catalogo["datasets"]) or controle["rotas"]!=len(entradas):
        raise ValueError("cobertura de rotas incompleta")
    saida=[]
    for dado in catalogo["datasets"]:
        if prioridade is not None and dado["priority"]!=prioridade:
            continue
        rota=entradas[dado["id"]]
        src=fontes[dado["source_id"]]
        acesso_restrito = src["rights"]=="RESTRICTED" or dado["stage"]=="BLOCKED_RIGHTS"
        # Página da documentação não é endpoint de dados homologado.
        endpoint=rota["locator"]["kind"]=="DIRECT_PUBLIC_FILE"
        codigo = bool(dado.get("existing_module")) or dado["stage"] in ("CODE_PRESENT","REAL_SNAPSHOT_TESTED")
        amostra_real = dado["stage"]=="REAL_SNAPSHOT_TESTED"
        bloqueios=list(rota["gates_missing"])
        if not bloqueios or not {"HISTORICAL_BACKFILL","DURABLE_PERSISTENCE_AND_RESTORE",
                                 "LICENSED_PUBLICATION_GATE"}.issubset(bloqueios):
            raise ValueError("gates críticos removidos indevidamente")
        if rota["runtime_enabled"] or rota["scheduled_enabled"] or dado["enabled"]:
            raise ValueError("ativação indevida")
        if acesso_restrito:
            etapa="DIREITOS_RESTRITOS"
        elif not endpoint:
            etapa="ENDPOINT_DE_DADOS_NAO_COMPROVADO"
        elif not codigo:
            etapa="PARSER_A_DESENVOLVER"
        elif not amostra_real:
            etapa="CODIGO_SEM_SNAPSHOT_REAL_HOMOLOGADO"
        else:
            etapa="SNAPSHOT_REAL_SEM_GATES_OPERACIONAIS"
        saida.append({
            "dataset_id":dado["id"],"fonte_id":dado["source_id"],
            "prioridade":dado["priority"],"grupo":dado["group"],
            "codigo_referenciado":codigo,"snapshot_real_testado":amostra_real,
            "recurso_tecnico_identificado":endpoint,
            "acesso_restrito":acesso_restrito,"fase":etapa,
            "bloqueios":bloqueios,"publicacao_liberada":False,
            "coleta_automatica_habilitada":False,
        })
    saida.sort(key=lambda x:(_ORDER[x["prioridade"]],x["grupo"],x["dataset_id"]))
    return {
        "fonte_de_verdade":"CATALOGO_E_ROTAS_V1",
        "total_catalogado":meta["datasets"],
        "total_auditado":len(saida),
        "fontes":meta["fontes"],
        "automaticos_habilitados":0,"prontos_para_producao":0,
        "por_fase":dict(sorted(Counter(x["fase"] for x in saida).items())),
        "por_prioridade":dict(sorted(Counter(x["prioridade"] for x in saida).items())),
        "por_grupo":dict(sorted(Counter(x["grupo"] for x in saida).items())),
        "datasets":saida,
        "limite":"diagnóstico documental não homologa acesso, licença, amostra real ou disponibilidade",
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: auditoria estática OFFLINE dos coletores")
    p.add_argument("--prioridade",choices=["P0","P1","P2"])
    p.add_argument("--resumo",action="store_true")
    args=p.parse_args(argv)
    try:
        out=auditoria_estatica(carregar_catalogo(),carregar_rotas(),prioridade=args.prioridade)
        if args.resumo:
            out.pop("datasets")
        print(json.dumps(out,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError) as exc:
        print(json.dumps({"estado":"BLOQUEADO","motivo":str(exc)},ensure_ascii=False))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
