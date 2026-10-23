"""Auditoria estática offline de workflows; NÃO invoca Actions, endpoints ou banco.

Os sinais são indícios conservadores, não atestação de custos, licenças,
credenciais, confirmação de coleta ou aderência da configuração de produção.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

LIMITE=300_000
CRON=re.compile(r"^\s*-\s*cron:\s*['\"]?([^'\"]+)")
HAS_SCHEDULE=re.compile(r"(?m)^ {2}schedule:\s*(?:#.*)?$")
HAS_DISPATCH=re.compile(r"(?m)^ {2}workflow_dispatch:\s*(?:#.*)?$")
HAS_PUSH=re.compile(r"(?m)^ {2}push:\s*(?:#.*)?$")
URI_DOMAINS=re.compile(r"https://([a-zA-Z0-9.-]+)(?=[/: \t\"'])")
PATTERN_PROVIDER={
    "NEON":r"\bneon\.tech\b|NIVON_(?:CEPEA|IMEA|CONAB).*?(?:INGEST|STAGE)",
    "GCP":r"google-github-actions/|gcloud\s|BigQuery|NIVON_GCS_BUCKET|NIVON_BQ_PROJECT|GCS",
    "ANTT":r"ANTT|antt[_-]",
    "CEPEA":r"CEPEA|cepea[_-]",
    "IMEA":r"IMEA|imea[_-]",
    "CONAB":r"CONAB|conab[_-]",
}
REDE_ESCRITA=re.compile(
    r"\burlopen\s*\(|\brequests\.post\s*\(|\bfetch\s*\(|\bcurl\s+.*(?:-X POST|-d\s)|"
    r"\bPOST\b|\bMERGE\b|--executar\b|\bwrite_rows\b|--criar-tabela\b|"
    r"\bload_table_from\b|\.insert_rows\b",re.I
)
REDE_LEITURA=re.compile(r"\burlopen\b|\brequests\.get\b|--live\b|\bhttp",re.I)
COST_APPROVAL=re.compile(r"(?m)^\s*if:\s*.*NIVON_ZERO_COST_BQ_APPROVED.*true")
OIDC=re.compile(r"(?m)^\s*id-token:\s*write\b")
PIN_REF=re.compile(r"(?m)^\s*ref:\s*['\"]?([0-9a-f]{40})['\"]?\s*$")


class ErroAuditoriaWorkflow(ValueError):
    pass


def analisar_workflow(conteudo: str, *, nome: str) -> dict:
    if not isinstance(conteudo,str) or not conteudo or len(conteudo.encode())>LIMITE:
        raise ErroAuditoriaWorkflow("workflow vazio ou excessivo")
    if "\x00" in conteudo or not nome.endswith((".yml",".yaml")):
        raise ErroAuditoriaWorkflow("workflow inseguro")
    crons=CRON.findall(conteudo)
    ativo=bool(HAS_SCHEDULE.search(conteudo) or crons)
    labels=sorted(k for k,p in PATTERN_PROVIDER.items()
                  if re.search(p,conteudo,re.I|re.S))
    may_write=bool(REDE_ESCRITA.search(conteudo))
    gated_cost=bool(COST_APPROVAL.search(conteudo))
    reasons=[]
    if ativo:
        reasons.append("AGENDA_PERIODICA_PRESENTE")
    if may_write:
        reasons.append("EFEITO_EXTERNO_POSSIVEL")
    if may_write and not gated_cost:
        reasons.append("GATE_CUSTO_NAO_DETECTADO")
    if OIDC.search(conteudo):
        reasons.append("OIDC_PERMISSAO_ESCRITA")
    if activo:=("GCP" in labels or "NEON" in labels):
        if not gated_cost and may_write:
            reasons.append("AUTORIZACAO_DESPESA_NAO_PROVADA")
    if crons and not all(5<=len(s.split())<=6 for s in crons):
        reasons.append("CRON_FORMATO_NAO_VALIDADO")
    domains=sorted(set(URI_DOMAINS.findall(conteudo)))
    return {
        "arquivo":nome,
        "sha256_fonte":hashlib.sha256(conteudo.encode()).hexdigest(),
        "fontes_ou_plataformas":labels,
        "dominios_referenciados":domains,
        "gatilhos":{
            "schedule":ativo,
            "cron":crons,
            "workflow_dispatch":bool(HAS_DISPATCH.search(conteudo)),
            "push":bool(HAS_PUSH.search(conteudo)),
        },
        "operacao_externa_possivel":may_write,
        "rede_possivel":bool(may_write or REDE_LEITURA.search(conteudo)),
        "oidc_write_declarado":bool(OIDC.search(conteudo)),
        "gate_custo_detectado_textualmente":gated_cost,
        "refs_fixos_sha40":len(PIN_REF.findall(conteudo)),
        "sinais":sorted(set(reasons)),
        "atestado_operacional":False,
        "licenca_verificada":False,
        "persistencia_confirmada":False,
        "ativacao_recomendada":False,
    }


def analisar_diretorio(pasta: str | Path, *, limite_arquivos: int=250) -> dict:
    root=Path(pasta)
    if not root.is_dir() or root.is_symlink():
        raise ErroAuditoriaWorkflow("diretório inválido")
    files=sorted([*root.glob("*.yml"),*root.glob("*.yaml")])
    if len(files)>limite_arquivos:
        raise ErroAuditoriaWorkflow("quantidade excessiva de workflows")
    result=[]
    for p in files:
        if p.is_symlink() or not p.is_file():
            raise ErroAuditoriaWorkflow("workflow symlink/arquivo inválido")
        result.append(analisar_workflow(
            p.read_text(encoding="utf-8"),nome=p.name,
        ))
    return {
        "total":len(result),
        "agendados":sum(a["gatilhos"]["schedule"] for a in result),
        "possivel_escrita":sum(a["operacao_externa_possivel"] for a in result),
        "exigem_revisao":[x["arquivo"] for x in result if x["sinais"]],
        "arquivos":result,
        "somente_leitura":True,"disparos_executados":0,
        "ativacao_autorizada":False,
    }
