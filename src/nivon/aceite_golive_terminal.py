"""Aceite P0 do NIVON Terminal: diagnóstico seguro e smoke Cloud Run PRIVADO.

A CI sem autorização faz somente testes sintéticos. A rede real só é
executada mediante --executar, URL Cloud Run estritamente permitida e
ID token já provido pelo runtime federado. Nenhum dado de série ou token
é impresso, persistido ou anexado em artefatos do Actions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPResponse
import json
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ALLOWED = frozenset({"CONFIRMADO","AUSENTE","SEM_PERMISSAO",
                     "NAO_CONFIGURADO","DIVERGENTE","INDETERMINADO"})
REQUIRED = (
    "run.googleapis.com", "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com", "artifact_repository",
    "execution_service_account", "bigquery_dataset", "bigquery_view",
)
ACTIONS = {
    "run.googleapis.com":"CONFERIR_API_CLOUD_RUN_JA_HABILITADA",
    "cloudbuild.googleapis.com":"CONFERIR_API_CLOUD_BUILD_JA_HABILITADA",
    "artifactregistry.googleapis.com":"CONFERIR_API_ARTIFACT_REGISTRY_JA_HABILITADA",
    "artifact_repository":"CONFERIR_REPOSITORIO_DOCKER_E_VARIAVEL",
    "execution_service_account":"CONFERIR_SERVICE_ACCOUNT_EXECUCAO_E_VARIAVEL",
    "bigquery_dataset":"CONFERIR_DATASET_BIGQUERY_SAO_PAULO",
    "bigquery_view":"CONFERIR_VIEW_FERROVIA_ANTT",
    "terminal_cloudrun_existente":"CONFERIR_SERVICO_CLOUD_RUN_PRIVADO",
    "terminal_iam_privado":"RETIRAR_PERMISSAO_PUBLICA_OU_REVISAR_IAM",
}
_MAX_RESPONSE = 400_000
_HOST = re.compile(r"^nivon-terminal-[a-z0-9-]{4,100}\.(?:(?:southamerica-east1\.)?run\.app|a\.run\.app)$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ErroAceite(ValueError):
    """Aceite bloqueado sem entregar token, dado restrito ou segredo."""


def avaliar_preflight_cloudrun(doc: object) -> dict:
    """Transforma o diagnóstico real metadata-only em bloqueios acionáveis."""
    if (not isinstance(doc,dict) or doc.get("alteracoes_cloud") != 0
            or doc.get("sql_executado") is not False
            or not isinstance(doc.get("componentes"),dict)):
        raise ErroAceite("pré-voo sem prova de não alteração")
    s=doc["componentes"]
    if (set(s)-set(ACTIONS) or any(v not in ALLOWED for v in s.values())
            or not set(REQUIRED).issubset(s)
            or "terminal_cloudrun_existente" not in s
            or "terminal_iam_privado" not in s):
        raise ErroAceite("componentes do diagnóstico desconhecidos ou incompletos")
    pendencias=[
        {"componente":k,"estado":s[k],"acao":ACTIONS[k]}
        for k in REQUIRED if s[k]!="CONFIRMADO"
    ]
    service=s["terminal_cloudrun_existente"]
    iam=s["terminal_iam_privado"]
    if service not in ("AUSENTE","CONFIRMADO"):
        pendencias.append({"componente":"terminal_cloudrun_existente",
                           "estado":service,
                           "acao":ACTIONS["terminal_cloudrun_existente"]})
    elif service=="CONFIRMADO" and iam!="CONFIRMADO":
        pendencias.append({"componente":"terminal_iam_privado",
                           "estado":iam,"acao":ACTIONS["terminal_iam_privado"]})
    if service=="AUSENTE" and iam not in ("NAO_CONFIGURADO","AUSENTE"):
        pendencias.append({"componente":"terminal_iam_privado",
                           "estado":iam,"acao":ACTIONS["terminal_iam_privado"]})
    ready=not pendencias
    if doc.get("metadados_basicos_confirmados") is not ready:
        raise ErroAceite("resultado anterior do diagnóstico contraditório")
    return {
        "status":"METADADOS_PRONTOS_NAO_E_DEPLOY" if ready else "NO_GO_METADADOS",
        "total_bloqueios":len(pendencias),"bloqueios":pendencias,
        "proxima_etapa":(
            "REVISAR_IAM_CUSTOS_E_EXECUTAR_DEPLOY_MANUAL"
            if ready else "CORRIGIR_BLOQUEIOS_LISTADOS"
        ),
        "deploy_executado":False,
        "consumo_bigquery_executado":False,
        "acesso_privado_comprovado":False,
        "go_live_aprovado":False,
    }


def _url_valida(url: object) -> str:
    if not isinstance(url,str) or len(url)>220:
        raise ErroAceite("URL do terminal inválida")
    try:
        p=urlsplit(url)
    except ValueError as exc:
        raise ErroAceite("URL do terminal malformada") from exc
    if (p.scheme!="https" or p.username or p.password or p.port is not None
            or p.path not in ("","/") or p.query or p.fragment
            or not p.hostname or not _HOST.fullmatch(p.hostname)
            or p.hostname!=p.netloc):
        raise ErroAceite("somente URL raiz HTTPS do nivon-terminal no Cloud Run")
    return "https://"+p.hostname


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _consultar(opener, url: str, token: str, endpoint: str):
    req=Request(url+endpoint,method="GET",headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/json" if endpoint!="/" else "text/html",
        "Cache-Control":"no-store",
    })
    try:
        with opener.open(req,timeout=12) as response:
            if response.status!=200:
                raise ErroAceite("terminal não respondeu HTTP 200")
            tipo=response.headers.get("Content-Type","").split(";",1)[0].lower()
            esperado="text/html" if endpoint=="/" else "application/json"
            if tipo!=esperado or response.headers.get("Cache-Control")!="no-store":
                raise ErroAceite("contrato de MIME/cache inválido no terminal")
            if (response.headers.get("X-Frame-Options")!="DENY"
                    or response.headers.get("X-Content-Type-Options")!="nosniff"):
                raise ErroAceite("cabeçalhos de privacidade do terminal ausentes")
            data=response.read(_MAX_RESPONSE+1)
    except (HTTPError,URLError,OSError,TimeoutError) as exc:
        raise ErroAceite("terminal privado não acessível pela identidade autorizada") from exc
    if not 1<=len(data)<=_MAX_RESPONSE:
        raise ErroAceite("resposta vazia ou acima do limite")
    return data


def validar_terminal_privado(*, url: str, token: str,
                              agora: datetime | None=None, opener=None) -> dict:
    """Smoke real usando TLS e token autenticado; nunca imprime TU ou preços."""
    origin=_url_valida(url)
    if (not isinstance(token,str) or not 64<=len(token)<=8192
            or any(c.isspace() or ord(c)<33 or ord(c)>126 for c in token)):
        raise ErroAceite("identity token não disponível em memória")
    agora=agora or datetime.now(timezone.utc)
    if not isinstance(agora,datetime) or agora.utcoffset() is None:
        raise ErroAceite("relógio com fuso obrigatório")
    agora=agora.astimezone(timezone.utc)
    client=opener if opener is not None else build_opener(_SemRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    health=_consultar(client,origin,token,"/healthz")
    try:
        proc=json.loads(health)
    except ValueError as exc:
        raise ErroAceite("healthz retornou JSON inválido") from exc
    if proc != {"estado":"PROCESSO_ATIVO"}:
        raise ErroAceite("healthz não confirma processo ativo")
    raw=_consultar(client,origin,token,"/api/v1/ferrovia")
    try:
        doc=json.loads(raw)
    except ValueError as exc:
        raise ErroAceite("API ferroviária retornou JSON inválido") from exc
    if (not isinstance(doc,dict)
            or doc.get("estado")!="ANTT_SERIE_OBSERVADA_DECLARADA"
            or doc.get("natureza")!="OBSERVADO_DECLARADO"
            or doc.get("homologacao_editorial") is not False
            or doc.get("soma_multimodal_permitida") is not False
            or doc.get("point_in_time_historico") is not False
            or doc.get("status_publicacao")!="PREVIA_PRIVADA"):
        raise ErroAceite("API não preserva proveniência e limites metodológicos")
    serie=doc.get("serie")
    if (not isinstance(serie,list) or type(doc.get("anos")) is not int
            or doc["anos"]!=len(serie) or not 1<=len(serie)<=35
            or type(doc.get("registros_acumulados")) is not int
            or doc["registros_acumulados"]<=0):
        raise ErroAceite("histórico ferroviário ausente ou fabricado")
    anos=[s.get("ano") for s in serie if isinstance(s,dict)]
    if (len(anos)!=len(serie) or anos!=list(range(2006,2006+len(serie)))
            or serie[-1].get("ultima_competencia")!=doc.get("ultima_competencia")
            or not re.fullmatch(r"20[0-9]{2}-(?:0[1-9]|1[0-2])",
                                str(doc.get("ultima_competencia","")))):
        raise ErroAceite("anos e competência da API incoerentes")
    try:
        coleta=datetime.fromisoformat(doc["ultima_coleta_utc"].replace("Z","+00:00"))
    except (KeyError,AttributeError,ValueError) as exc:
        raise ErroAceite("data de coleta ausente ou inválida") from exc
    if (coleta.utcoffset() is None or coleta>agora
            or serie[-1]["ultima_competencia"]>agora.strftime("%Y-%m")):
        raise ErroAceite("dados temporalmente inconsistentes")
    html=_consultar(client,origin,token,"/")
    if b"NIVON" not in html or b"noindex" not in html.lower():
        raise ErroAceite("HTML do terminal não corresponde ao NIVON privado")
    return {
        "status":"SMOKE_PRIVADO_AUTENTICADO_PASSOU",
        "rotas_verificadas":["/healthz","/api/v1/ferrovia","/"],
        "fonte":"ANTT_SIADE","anos":doc["anos"],
        "ultima_competencia":doc["ultima_competencia"],
        "sha256_resposta_api":sha256(raw).hexdigest(),
        "identidade_iam_foi_aceita":True,
        "dados_reais_com_proveniencia_aparente":True,
        "go_live_final_homologado":False,
        "custos_medidos":False,
        "publicavel":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Aceite HTTP autenticado e privado do NIVON")
    parser.add_argument("--executar",action="store_true",
                        help="Executa 3 GET autenticados; requer deploy/custos aprovados")
    parser.add_argument("--url",default="",help="URL raiz oficial nivon-terminal Cloud Run")
    args=parser.parse_args(argv)
    if not args.executar:
        print(json.dumps({"status":"SMOKE_DESATIVADO_POR_PADRAO",
                          "rede_executada":False,"go_live_aprovado":False}))
        return 0
    try:
        result=validar_terminal_privado(
            url=args.url,token=os.environ.get("NIVON_TERMINAL_IDENTITY_TOKEN","")
        )
    except (ErroAceite,TypeError,ValueError) as exc:
        # Nunca ecoar URL, token, corpo HTTP, nomes de identidade ou erro IAM.
        print(json.dumps({"status":"NO_GO_SMOKE_PRIVADO",
                          "categoria":type(exc).__name__,
                          "publicavel":False}))
        return 2
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
