"""Aceite determinístico do primeiro Cloud Run privado do NIVON.

Entrada: evidências produzidas por comandos GCP e HTTP já aprovados.
Sem dependências Google, autenticação implícita, deploy, IAM ou rede nesta rotina.
Não confundir healthz (processo ativo) com fonte operacional.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PROJECT="nivon-data"
REGION="southamerica-east1"
SERVICE="nivon-terminal"
DATASET="nivon_raw"
_SHA=re.compile(r"[a-f0-9]{40}\Z")
_COMP=re.compile(r"20\d{2}-(0[1-9]|1[0-2])\Z")


class FalhaAceite(ValueError):
    pass


def _tempo(value, label):
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (AttributeError,ValueError) as exc:
        raise FalhaAceite(label+": instante UTC inválido") from exc
    if dt.utcoffset() is None:
        raise FalhaAceite(label+": fuso ausente")
    return dt.astimezone(timezone.utc)


def _url_privada(value):
    if not isinstance(value,str):
        raise FalhaAceite("URL do serviço ausente")
    u=urlsplit(value)
    if (u.scheme!="https" or not u.hostname or
        not (u.hostname.endswith(".run.app") or u.hostname.endswith(".a.run.app"))
        or u.username or u.password or u.port or u.query or u.fragment
        or u.path not in ("","/")):
        raise FalhaAceite("URL não é o endpoint HTTPS padrão Cloud Run")
    return value.rstrip("/")


def _num(value, nome):
    try:
        if isinstance(value,bool) or value is None:
            raise ValueError("boolean/none")
        n=Decimal(str(value))
    except (ValueError,InvalidOperation,TypeError) as exc:
        raise FalhaAceite(nome+": número inválido") from exc
    if not n.is_finite() or n<0:
        raise FalhaAceite(nome+": número negativo ou não finito")
    return n



def conferir_politica_iap(service: dict, iam: dict, numero_projeto: str) -> dict:
    """Exige IAP nativo ativo e invoker reservado ao agente correto.

    Sem redes, mutações IAM ou aceites de acesso público.
    """
    if not isinstance(service, dict) or not isinstance(iam, dict):
        raise FalhaAceite("evidência de serviço/IAM inválida")
    if not isinstance(numero_projeto, str) or not re.fullmatch(r"[0-9]{6,20}", numero_projeto):
        raise FalhaAceite("número do projeto não confirmado")
    spec = service.get("spec") or {}
    metadata = service.get("metadata") or {}
    annotations = metadata.get("annotations") or {}
    # Cloud Run v2 e saída convertida do gcloud (v1).
    iap = (service.get("iapEnabled") is True
           or service.get("iap_enabled") is True
           or spec.get("iapEnabled") is True
           or str(annotations.get("run.googleapis.com/iap-enabled", "")).lower() == "true")
    if not iap:
        raise FalhaAceite("IAP não comprovadamente ativo")
    expected = "serviceAccount:service-" + numero_projeto + "@gcp-sa-iap.iam.gserviceaccount.com"
    bindings = iam.get("bindings")
    if not isinstance(bindings, list):
        raise FalhaAceite("bindings IAM inválidos")
    invokers = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise FalhaAceite("binding IAM inválido")
        members = binding.get("members") or []
        if not isinstance(members, list):
            raise FalhaAceite("members IAM inválidos")
        if set(members).intersection(("allUsers", "allAuthenticatedUsers")):
            raise FalhaAceite("IAM público proibido")
        if binding.get("role") == "roles/run.invoker":
            invokers.update(members)
    if expected not in invokers:
        raise FalhaAceite("roles/run.invoker do agente IAP ausente")
    return {"iap_ativo": True, "iam_sem_publico": True, "agente_iap_invoker": True}


def conferir_aceite_terminal(
    *, service, iam, health, dados, unauth_status, commit_sha,
    agora=None, numero_projeto=None,
):
    """Aceita apenas URL AUTENTICADA com fonte ANTT real e revisão aprovada.

    'service' e 'iam' precisam vir de gcloud. 'health' e 'dados' devem ser
    respostas obtidas com identity token autorizado, e a negativa unauth deve
    ser aferida contra a mesma URL. A rotina não valida assinaturas de prova:
    o executor deve guardar logs com SHA do commit no job de aprovação.
    """
    conferir_politica_iap(service, iam, numero_projeto)
    now=agora or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise FalhaAceite("relógio de aceite sem timezone")
    now=now.astimezone(timezone.utc)
    if not isinstance(commit_sha,str) or not _SHA.fullmatch(commit_sha):
        raise FalhaAceite("commit Git inexistente/inválido")
    if not isinstance(service,dict) or not isinstance(iam,dict):
        raise FalhaAceite("metadados Cloud Run/IAM inválidos")
    metadata=service.get("metadata") or {}
    spec=service.get("spec") or {}
    status=service.get("status") or {}
    template=(spec.get("template") or {}).get("spec") or {}
    labels=metadata.get("labels") or {}
    if metadata.get("name")!=SERVICE or labels.get("nivon-component")!="terminal":
        raise FalhaAceite("recurso Cloud Run de outro projeto/componente")
    if (template.get("serviceAccountName","").split("@")[-1]
            != PROJECT+".iam.gserviceaccount.com"):
        raise FalhaAceite("identidade de execução fora do projeto")
    containers=template.get("containers")
    if not isinstance(containers,list) or len(containers)!=1:
        raise FalhaAceite("container de execução ambíguo")
    image=containers[0].get("image","")
    expected_prefix=REGION+"-docker.pkg.dev/"+PROJECT+"/"
    if (not image.startswith(expected_prefix) or
        not image.endswith("/nivon-terminal:"+commit_sha[:12])):
        raise FalhaAceite("imagem implantada não corresponde ao commit")
    ready=status.get("latestReadyRevisionName")
    if not isinstance(ready,str) or not ready.startswith(SERVICE+"-"):
        raise FalhaAceite("revisão Cloud Run não pronta")
    conditions=status.get("conditions") or []
    if not any(c.get("type")=="Ready" and c.get("status") in (True,"True")
               for c in conditions):
        raise FalhaAceite("recurso Cloud Run sem condição Ready")
    traffic=status.get("traffic") or []
    if (len(traffic)!=1 or traffic[0].get("revisionName")!=ready
        or traffic[0].get("percent")!=100):
        raise FalhaAceite("tráfego não está integralmente na revisão validada")
    url=_url_privada(status.get("url"))
    for binding in iam.get("bindings",[]):
        if not isinstance(binding,dict):
            raise FalhaAceite("binding IAM inválido")
        if binding.get("role")=="roles/run.invoker":
            members=binding.get("members") or []
            if ("allUsers" in members or "allAuthenticatedUsers" in members):
                raise FalhaAceite("serviço Cloud Run com invoker público")
    if str(unauth_status) not in ("401","403"):
        raise FalhaAceite("acesso HTTP sem identidade não foi negado")
    if not isinstance(health,dict) or health.get("estado")!="PROCESSO_ATIVO":
        raise FalhaAceite("/healthz não respondeu pelo serviço autenticado")
    if (not isinstance(dados,dict) or
        dados.get("estado")!="ANTT_SERIE_OBSERVADA_DECLARADA" or
        dados.get("natureza")!="OBSERVADO_DECLARADO" or
        dados.get("fonte")!="ANTT/SIADE — transporte ferroviario origem-destino" or
        dados.get("status_publicacao")!="PREVIA_PRIVADA" or
        dados.get("homologacao_editorial") is not False or
        dados.get("point_in_time_historico") is not False or
        dados.get("soma_multimodal_permitida") is not False):
        raise FalhaAceite("API expôs dado sem contrato explícito de fonte")
    sequence=dados.get("serie")
    if (not isinstance(sequence,list) or
        len(sequence)!=now.year-2006+1 or
        dados.get("anos")!=len(sequence)):
        raise FalhaAceite("série ANTT incompleta na API")
    total_tu,total_od=Decimal(0),0
    for index,row in enumerate(sequence):
        if not isinstance(row,dict) or row.get("ano")!=2006+index:
            raise FalhaAceite("ano da série fora de ordem")
        val=_num(row.get("toneladas_uteis"),"toneladas_uteis")
        count=row.get("registros")
        if val<=0 or type(count) is not int or count<=0:
            raise FalhaAceite("série contém valores não verificáveis")
        comp=row.get("ultima_competencia")
        if not isinstance(comp,str) or not _COMP.fullmatch(comp) or int(comp[:4])!=row["ano"]:
            raise FalhaAceite("competência anual inválida")
        total_tu+=val
        total_od+=count
    if (total_tu!=_num(dados.get("tu_acumuladas"),"tu_acumuladas")
            or total_od!=dados.get("registros_acumulados")):
        raise FalhaAceite("total acumulado não reconcilia com a série")
    last=sequence[-1]["ultima_competencia"]
    if (last!=dados.get("ultima_competencia") or
        last>now.strftime("%Y-%m")):
        raise FalhaAceite("competência mais recente inválida ou futura")
    collected=_tempo(dados.get("ultima_coleta_utc"),"coleta")
    if collected>now or collected.year<2006:
        raise FalhaAceite("data de coleta futura")
    processed=dados.get("bytes_processados_ultimo_job")
    if processed is not None and (
        type(processed) is not int or not 0<=processed<=250_000_000):
        raise FalhaAceite("consulta excedeu orçamento de bytes configurado")
    return {
        "estado":"GO_LIVE_PRIVADO_01_ACEITE_TECNICO",
        "url_cloud_run_privada":url,
        "revisao":ready,
        "commit":commit_sha,
        "iam_sem_publico":True,
        "iap_ativo":True,
        "agente_iap_invoker":True,
        "acesso_sem_token_rejeitado":True,
        "health_autenticado":True,
        "ferrovia_bq_autenticado":True,
        "anos_observados":len(sequence),
        "ultima_competencia":last,
        "ultima_coleta_utc":collected.isoformat(),
        "fonte":"ANTT/SIADE",
        "natureza":"OBSERVADO_DECLARADO",
        "bytes_ultima_consulta":processed,
        "custos_totais_zerados_comprovados":False,
        "homologacao_editorial":False,
        "acesso_publico":False,
        "validado_em":now.isoformat(),
    }


def _json(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=5_000_000:
        raise FalhaAceite("evidência JSON ausente/insegura")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError) as exc:
        raise FalhaAceite("evidência JSON inválida") from exc


def main(argv=None):
    p=argparse.ArgumentParser(description="Aceite local de evidências de Cloud Run privado")
    for k in ("service","iam","health","dados","unauth-status","commit-sha","numero-projeto"):
        p.add_argument("--"+k,required=True)
    a=p.parse_args(argv)
    try:
        result=conferir_aceite_terminal(
            service=_json(a.service),iam=_json(a.iam),
            health=_json(a.health),dados=_json(a.dados),
            unauth_status=a.unauth_status,commit_sha=a.commit_sha,
            numero_projeto=a.numero_projeto)
    except (FalhaAceite,OSError) as exc:
        # Nunca imprimir credenciais, corpo bruto BigQuery ou token.
        print(json.dumps({"estado":"NAO_HOMOLOGADO","falha":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
