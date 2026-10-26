"""Bootstrap único das duas tabelas NIVON no dataset GCP existente.

Modo padrão: só leitura. A opção --aplicar é restrita a main, GitHub Environment
e aprovações separadas para cada tabela. Nunca cria projeto/dataset/bucket.
Sem ingestão, sem consultas de dados nem alteração de tabelas existentes.
"""
from __future__ import annotations

import argparse
import json
import os

from .auditoria_gcp_readonly import auditar
from .preflight_gcp_fontes import verificar_nuvem, validar_config
from .agro_staging_bigquery import verificar_ou_criar_tabela

ALVOS = ("canonico", "agro", "ambas")
APROVACOES_COMUNS = ("NIVON_ZERO_COST_BQ_APPROVED",)
APROVACOES_CANONICO = ("NIVON_BQ_BOOTSTRAP_TABLE_APPROVED",)
APROVACOES_AGRO = ("NIVON_AGRO_STAGING_SCHEMA_APPROVED",
                   "NIVON_AGRO_GCP_WRITE_APPROVED")


class ErroBootstrap(ValueError):
    pass


def _selecionadas(alvo):
    if alvo not in ALVOS:
        raise ErroBootstrap("alvo de bootstrap inválido")
    return ["nivon_observacoes", "agro_publicacoes_staging"] if alvo == "ambas" else [
        "nivon_observacoes" if alvo == "canonico" else "agro_publicacoes_staging"
    ]


def _gates(alvo, env):
    chaves=list(APROVACOES_COMUNS)
    if alvo in ("canonico", "ambas"):
        chaves.extend(APROVACOES_CANONICO)
    if alvo in ("agro", "ambas"):
        chaves.extend(APROVACOES_AGRO)
    return [key for key in chaves if env.get(key) != "true"]


def executar_bootstrap(*, projeto, dataset, bucket, alvo="ambas",
                       aplicar=False, env=None, leitura=None,
                       bootstrap_canonico=None, bootstrap_agro=None):
    """Primeiro inspeciona ambas; se aplicar, exige todos os gates antes de escrever.

    Funções injetáveis permitem testes E2E determinísticos sem nuvem.
    A operação não é transacional entre duas tabelas: rerun é idempotente.
    """
    validar_config(projeto=projeto, dataset=dataset, bucket=bucket)
    escolhidas=_selecionadas(alvo)
    if type(aplicar) is not bool:
        raise ErroBootstrap("aplicar precisa booleano")
    ambiente=os.environ if env is None else env
    leitor=auditar if leitura is None else leitura
    canonico=verificar_nuvem if bootstrap_canonico is None else bootstrap_canonico
    agro=verificar_ou_criar_tabela if bootstrap_agro is None else bootstrap_agro
    antes=leitor(projeto=projeto,dataset=dataset,bucket=bucket,executar=True)
    if not isinstance(antes,dict) or antes.get("acesso_metadados_confirmado") is not True:
        raise ErroBootstrap("auditoria cloud incompleta")
    if antes.get("regiao_conforme") is not True:
        raise ErroBootstrap("recursos GCP fora da região aprovada")
    tabela_por_nome={t["tabela"]:t for t in antes.get("tabelas",[])
                     if isinstance(t,dict) and isinstance(t.get("tabela"),str)}
    if any(x not in tabela_por_nome for x in escolhidas):
        raise ErroBootstrap("auditoria não retornou todas as tabelas")
    for nome in escolhidas:
        estado=tabela_por_nome[nome]
        if estado.get("existe") and (estado.get("schema_conforme") is not True
                                   or estado.get("particao_conforme") is not True
                                   or estado.get("cluster_conforme") is not True):
            raise ErroBootstrap(f"tabela {nome} existente mas incompatível; não modificar")
    resposta={
        "projeto":projeto,"dataset":dataset,"bucket":bucket,
        "alvo":alvo,"consultas_sql":0,
        "tabelas_antes":[{"tabela":n,"existe":bool(tabela_por_nome[n]["existe"])}
                          for n in escolhidas],
        "criou_tabelas":[],"executou_escrita":False,
        "pronto_para_producao":False,
    }
    if not aplicar:
        resposta["estado"]="VERIFICACAO_SOMENTE_LEITURA"
        resposta["tabelas_pendentes"]=[n for n in escolhidas if not tabela_por_nome[n]["existe"]]
        return resposta
    ausentes=_gates(alvo,ambiente)
    if ausentes:
        raise PermissionError("bootstrap bloqueado; aprovações ausentes: "+", ".join(ausentes))
    if "nivon_observacoes" in escolhidas:
        confirmado=canonico(projeto=projeto,dataset=dataset,bucket=bucket,
                            criar_tabela=not tabela_por_nome["nivon_observacoes"]["existe"])
        if not isinstance(confirmado,dict) or confirmado.get("tabela_validada") is not True:
            raise ErroBootstrap("bootstrap canônico não confirmou schema")
        if not tabela_por_nome["nivon_observacoes"]["existe"]:
            if confirmado.get("tabela_criada") is not True:
                raise ErroBootstrap("bootstrap canônico não confirmou criação")
            resposta["criou_tabelas"].append("nivon_observacoes")
    if "agro_publicacoes_staging" in escolhidas:
        staging=agro(projeto=projeto,dataset=dataset,verificar=True,
                     aplicar=not tabela_por_nome["agro_publicacoes_staging"]["existe"],
                     aprovado=True)
        if not isinstance(staging,dict):
            raise ErroBootstrap("resultado staging inesperado")
        if not tabela_por_nome["agro_publicacoes_staging"]["existe"]:
            if staging.get("criou_tabela") is not True:
                raise ErroBootstrap("staging não confirmou a criação")
            resposta["criou_tabelas"].append("agro_publicacoes_staging")
    # Segunda auditoria faz leitura independente, jamais supõe sucesso no create.
    depois=leitor(projeto=projeto,dataset=dataset,bucket=bucket,executar=True)
    estado_final={t["tabela"]:t for t in depois.get("tabelas",[])
                  if isinstance(t,dict) and "tabela" in t}
    if not all(estado_final.get(n,{}).get("existe") is True
               and estado_final[n].get("schema_conforme") is True
               and estado_final[n].get("particao_conforme") is True
               and estado_final[n].get("cluster_conforme") is True
               for n in escolhidas):
        raise ErroBootstrap("leitura após bootstrap não confirmou as tabelas")
    resposta["executou_escrita"]=bool(resposta["criou_tabelas"])
    resposta["tabelas_confirmadas"]=escolhidas
    resposta["estado"]="SCHEMAS_CONFIRMADOS_SEM_DADOS"
    return resposta


def main(argv=None):
    p=argparse.ArgumentParser(description="Validar/criar tabelas BQ no dataset NIVON existente")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--alvo",choices=ALVOS,default="ambas")
    p.add_argument("--aplicar",action="store_true")
    a=p.parse_args(argv)
    saida=executar_bootstrap(projeto=a.projeto,dataset=a.dataset,
                             bucket=a.bucket,alvo=a.alvo,aplicar=a.aplicar)
    print(json.dumps(saida,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
