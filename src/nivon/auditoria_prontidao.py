"""Auditoria estática de prontidão NIVON, sem rede, envio, deploy ou escrita.

Maturidade do parser, licença, cobertura, histórico e modelo são condições
independentes. Uma contagem de testes não pode ser traduzida em '95% pronto'.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from .catalogo_fontes import carregar_catalogo, validar_catalogo, ErroCatalogo
from .rotas_coleta import carregar_rotas, validar_rotas
from .cobertura import carregar_matriz, validar_matriz
from .registro_motores import carregar_registro, validar_registro
from .lineup_nacional import carregar_escopo

STAGES = {
    "REAL_SNAPSHOT_TESTED": "HISTORICO_DURAVEL_DIREITOS_E_AGENDAMENTO",
    "CODE_PRESENT": "AMOSTRA_REAL_LAYOUT_E_HOMOLOGACAO",
    "CANDIDATE": "ENDPOINT_DIREITOS_LAYOUT_E_TESTE_REAL",
    "DISCOVERY_ONLY": "LOCALIZAR_RECURSO_E_CONFIRMAR_DIREITOS",
    "BLOCKED_RIGHTS": "AUTORIZACAO_COMERCIAL_OU_ALTERNATIVA_PERMITIDA",
}
OPERATIONS = frozenset({
    "DIREITOS_POR_OPERACAO", "LAYOUT_REAL_VALIDADO",
    "HISTORICO_INCREMENTAL", "ARMAZENAMENTO_BACKUP_RESTORE",
    "VALIDACAO_EMPIRICA_MOTOR", "OBSERVABILIDADE_E_ALERTAS",
    "HOMOLOGACAO_INDEPENDENTE",
})


def auditar_prontidao(catalogo: dict, rotas: dict, matriz: dict,
                     motores: dict, escopo: dict) -> dict:
    validar_catalogo(catalogo)
    validar_rotas(rotas, catalogo)
    validar_matriz(matriz, catalogo)
    validar_registro(motores, matriz)
    pids=[p.get("id") for p in escopo.get("ports", [])]
    if len(pids)!=45 or len(set(pids))!=45:
        raise ErroCatalogo("escopo nacional deve ter 45 IDs únicos")
    official={d["id"].removeprefix("LINEUP_") for d in catalogo["datasets"]
              if d["id"].startswith("LINEUP_")}
    if official!=set(pids):
        raise ErroCatalogo("escopo de portos diverge dos datasets nacionais")
    if any(p.get("live_enabled") is not False or p.get("parser_homologated") is not False
           for p in escopo["ports"]):
        raise ErroCatalogo("escopo não pode habilitar porto implicitamente")
    stages=Counter(d["stage"] for d in catalogo["datasets"])
    source_map={s["id"]:s for s in catalogo["sources"]}
    routes_map={r["dataset_id"]:r for r in rotas["entries"]}
    detailed=[]
    for d in catalogo["datasets"]:
        r=routes_map[d["id"]]
        s=source_map[d["source_id"]]
        restricted=s["rights"]=="RESTRICTED" or d["stage"]=="BLOCKED_RIGHTS"
        gate=STAGES[d["stage"]]
        if d["enabled"] or d["collection_authorized"] or r["runtime_enabled"] or r["scheduled_enabled"]:
            raise ErroCatalogo("ativação sem gate validado")
        detailed.append({
            "dataset":d["id"],"grupo":d["group"],"priority":d["priority"],
            "stage":d["stage"],"fonte":d["source_id"],
            "direitos_restritos":restricted,
            "url_dados_confirmada":r["locator"]["kind"]=="DIRECT_PUBLIC_FILE" and r["locator"]["url"] is not None,
            "parser_mapeado":d["stage"] in {"CODE_PRESENT","REAL_SNAPSHOT_TESTED"},
            "gates_faltantes":r["gates_missing"],
            "bloqueio_principal":gate,
            "coleta_autorizada":False,"operacional":False,
        })
    fronts=[]
    for x in motores["engines"]:
        fronts.append({
            "frente":x["front_id"],
            "indicadores_previstos":x["indicators_planned"],
            "funcoes_de_codigo":len(x["entrypoints"]),
            "homologado_em_dados_reais":False,
            "previsao_validada_fora_amostra":False,
            "apto_producao":False,
        })
    return {
        "project":"NIVON","status":"BLOQUEADO_PARA_GO_LIVE",
        "fontes":len(catalogo["sources"]),
        "datasets":len(catalogo["datasets"]),
        "rotas":len(rotas["entries"]),
        "lineups_catalogados":len(pids),
        "indicadores_previstos":sum(len(x["indicators"]) for x in matriz["systems"]),
        "frentes":len(fronts),
        "funcoes_vinculadas":sum(x["funcoes_de_codigo"] for x in fronts),
        "coletas_operacionais":0,
        "motores_preditivos_homologados":0,
        "datasets_por_estagio":dict(sorted(stages.items())),
        "direitos_restritos_pendentes":sum(x["direitos_restritos"] for x in detailed),
        "gates_transversais_pendentes":sorted(OPERATIONS),
        "observacoes":[
            "Cadastro de fonte não é endpoint ativo nem permissão para coleta.",
            "Snapshot REAL_SNAPSHOT_TESTED não equivale a histórico durável ou coleta automática.",
            "Previsão em fixture sintética não representa habilidade preditiva empírica.",
            "Porto cadastrado não equivale a line-up observado ou navio em operação.",
            "Sem acesso/backup/homologação não há go-live, mesmo que toda a suíte passe.",
        ],
        "frentes_detalhadas":fronts,
        "datasets_detalhados":detailed,
    }


def diagnostico_atual() -> dict:
    c=carregar_catalogo()
    return auditar_prontidao(
        c,carregar_rotas(),carregar_matriz(catalogo=c),
        carregar_registro(),carregar_escopo(),
    )


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Auditoria NIVON (somente leitura)")
    parser.add_argument("--resumo",action="store_true")
    parser.add_argument("--grupo",default=None)
    args=parser.parse_args(argv)
    try:
        resultado=diagnostico_atual()
        if args.grupo:
            resultado["datasets_detalhados"]=[
                x for x in resultado["datasets_detalhados"]
                if x["grupo"]==args.grupo
            ]
        if args.resumo:
            resultado.pop("datasets_detalhados",None)
            resultado.pop("frentes_detalhadas",None)
        print(json.dumps(resultado,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,KeyError,TypeError,ErroCatalogo) as exc:
        print(json.dumps({"status":"AUDITORIA_INVALIDA","erro":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
