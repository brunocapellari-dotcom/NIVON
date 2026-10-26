"""Smoke privado e plano de rollback. Nunca executa deploy ou troca de tráfego."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .acessos_smoke_privado import _SemRedirect


def _token(url):
    result=subprocess.run(["gcloud","auth","print-identity-token",f"--audiences={url}"],
                          capture_output=True,text=True,timeout=20,check=False)
    if result.returncode or not result.stdout.strip():
        raise ValueError("AUTENTICACAO_INDISPONIVEL")
    return result.stdout.strip()


def _request(url,token):
    headers={"Accept":"application/json"}
    if token:headers["Authorization"]="Bearer "+token
    try:
        with build_opener(_SemRedirect).open(Request(url,headers=headers),timeout=15) as res:
            raw=res.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError("RESPOSTA_EXCESSIVA")
            return res.status,json.loads(raw)
    except HTTPError as exc:
        code=exc.code
        exc.close()
        return code,{}


def diagnosticar(*,env=None,service=None,policy=None,previous=None,
                executar=False,request=_request,token_provider=_token):
    env=os.environ if env is None else env
    report={"estado":"BLOCKED","smoke_ok":False,"go_live":False,
            "rollback":{"modo":"DRY_RUN","executado":False,"plano_validado":False},
            "checks":{},"alteracoes":0}
    checks=report["checks"]
    url=env.get("NIVON_TERMINAL_URL","")
    try:
        parsed=urlsplit(url)
        host=parsed.hostname
    except ValueError:
        return report
    checks["endpoint_conhecido"]=(parsed.scheme=="https" and
        bool(re.fullmatch(r"nivon-terminal-[a-z0-9.-]+\.run\.app",host or ""))
        and parsed.netloc==host and not parsed.path.strip("/")
        and not parsed.query and not parsed.fragment)
    checks["custo_aprovado"]=env.get("NIVON_GCP_COST_REVIEWED")=="true"
    checks["leitura_aprovada"]=env.get("NIVON_TERMINAL_READ_APPROVED")=="true"
    sha=env.get("NIVON_TERMINAL_EXPECTED_SHA","")
    checks["commit_informado"]=bool(re.fullmatch(r"[a-f0-9]{40}",sha))
    if not all(checks.values()) or service is None or policy is None:
        return report
    try:
        meta=service.get("metadata",{});status=service.get("status",{})
        revision=status.get("latestReadyRevisionName")
        checks["revisao_pronta"]=(isinstance(revision,str) and revision.startswith("nivon-terminal-")
                                    and revision==status.get("latestCreatedRevisionName"))
        checks["servico_pronto"]=any(x.get("type")=="Ready" and x.get("status")=="True"
                                      for x in status.get("conditions",[]))
        traffic=status.get("traffic",[])
        checks["trafego_commit_atual"]=(bool(traffic) and sum(t.get("percent",0) for t in traffic)==100
            and all(t.get("revisionName")==revision for t in traffic if t.get("percent",0)>0))
        checks["url_corresponde"]=status.get("url","").rstrip("/")==url.rstrip("/")
        checks["servico_nivon"]=meta.get("name")=="nivon-terminal" and meta.get("labels",{}).get("nivon-component")=="terminal"
        checks["iam_invoker_habilitado"]=meta.get("annotations",{}).get("run.googleapis.com/invoker-iam-disabled","false")=="false"
        bindings=policy.get("bindings")
        checks["iam_sem_acesso_publico"]=(isinstance(bindings,list) and all(
            isinstance(b,dict) and isinstance(b.get("members"),list) and
            not {"allUsers","allAuthenticatedUsers"}.intersection(b["members"]) for b in bindings))
        image=service["spec"]["template"]["spec"]["containers"][0]["image"]
        checks["imagem_commit"]=bool(re.fullmatch(
            r"southamerica-east1-docker\.pkg\.dev/nivon-data/[a-z0-9-]+/nivon-terminal:"+sha[:12],image))
        if previous:
            target=previous.get("metadata",{}).get("name","")
            ready=any(x.get("type")=="Ready" and x.get("status")=="True" for x in previous.get("status",{}).get("conditions",[]))
            if (re.fullmatch(r"nivon-terminal-[a-z0-9-]+",target) and target!=revision and ready):
                report["rollback"].update(plano_validado=True,revisao_anterior=target)
        if not all(checks.values()):return report
        if executar is not True:
            report["estado"]="PLANO_SEM_REDE"
            return report
        # Reject public exposure before requesting an identity token or API data.
        for route in ("/healthz","/readyz","/api/v1/ferrovia"):
            code,_=request(url.rstrip("/")+route,None)
            if code not in (401,403):
                checks["rotas_anonimas_bloqueadas"]=False
                return report
        checks["rotas_anonimas_bloqueadas"]=True
        token=token_provider(url)
        for route in ("/healthz","/readyz","/api/v1/ferrovia"):
            code,data=request(url.rstrip("/")+route,token)
            ok=code==200 and isinstance(data,dict)
            if route=="/healthz":ok=ok and data.get("estado")=="PROCESSO_ATIVO"
            elif route=="/readyz":ok=ok and data.get("estado")=="PRONTO_PARA_LEITURA"
            else:
                ok=(ok and data.get("estado")=="ANTT_SERIE_OBSERVADA_DECLARADA"
                    and data.get("natureza")=="OBSERVADO_DECLARADO"
                    and data.get("homologacao_editorial") is False
                    and "ANTT/SIADE" in data.get("fonte","")
                    and bool(re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])",data.get("ultima_competencia",""))))
            checks[route]=bool(ok)
        report["smoke_ok"]=all(checks.values())
        report["estado"]="SMOKE_PRIVADO_OK" if report["smoke_ok"] else "SMOKE_FALHOU"
    except Exception:
        report["estado"]="METADADOS_OU_SMOKE_INDISPONIVEIS"
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-json",type=Path)
    parser.add_argument("--policy-json",type=Path)
    parser.add_argument("--previous-revision-json",type=Path)
    parser.add_argument("--executar-smoke",action="store_true")
    args=parser.parse_args(argv)
    def load(path):
        if path is None:return None
        if path.is_symlink() or not 0<path.stat().st_size<=2_000_000:raise ValueError("MANIFESTO_INVALIDO")
        return json.loads(path.read_text())
    try:
        result=diagnosticar(service=load(args.service_json),policy=load(args.policy_json),
            previous=load(args.previous_revision_json),executar=args.executar_smoke)
    except Exception:
        result={"estado":"MANIFESTO_INDISPONIVEL","smoke_ok":False,"go_live":False,"alteracoes":0}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result.get("smoke_ok") else 2


if __name__=="__main__":raise SystemExit(main())
