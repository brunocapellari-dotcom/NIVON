"""Aquisição manual NASA POWER em 1 requisição HTTPS, com cache SQLite.

Sem agendamento, sem crawler, sem retries e sem download por padrão.
Evita baixar novamente a MESMA solicitação salvo revisão explicitamente
pedida pelo executor. Mecanismo de cache por URL não resolve células
equivalentes de pontos diferentes: uso em larga escala exige malha canônica.
"""
from __future__ import annotations
import hashlib
import sqlite3
from datetime import datetime,timezone
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from .nasa_power_diario import ErroPower
from .grade_meteorologica_store import ingerir_power_local

class ErroCapturaPower(ValueError):
    pass

class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,url):
        return None

def capturar_power_manual(db:sqlite3.Connection,*,plano:dict,
                         autorizar_http:bool=False,
                         autorizacoes:frozenset[str]=frozenset(),
                         evidencia_licenca:str|None=None,
                         revisao_explicita:bool=False,
                         transporte=None,
                         timeout:int=15):
    """Consulta manual com autorização de coleta/armazenamento em separado.

    transport: fake opener em testes. Não é job agendado; chamada só
    ocorre mediante execução humana/externa explícita.
    """
    if autorizar_http is not True:
        raise PermissionError("HTTP NASA desligado por padrão")
    if not {"COLETA","ARMAZENAMENTO"}.issubset(autorizacoes):
        raise PermissionError("direitos por operação não confirmados")
    if not isinstance(evidencia_licenca,str) or len(evidencia_licenca.strip())<8:
        raise PermissionError("evidência de licença/autorizações não registrada")
    if type(revisao_explicita) is not bool or type(timeout) is not int or not 1<=timeout<=25:
        raise ErroCapturaPower("parâmetros de execução não autorizados")
    if not isinstance(plano,dict) or plano.get("dataset_id")!="NASA_POWER_AG" or plano.get("executar") is not False:
        raise ErroCapturaPower("plano sem política segura")
    url=plano.get("url")
    if not isinstance(url,str):
        raise ErroCapturaPower("URL inexistente")
    p=urlsplit(url)
    if (p.scheme!="https" or p.hostname!="power.larc.nasa.gov" or
        p.path!="/api/temporal/daily/point" or
        p.username is not None or p.password is not None or
        p.port not in (None,443) or p.fragment):
        raise ErroCapturaPower("host/rota fora da allowlist")
    req_sha=hashlib.sha256(url.encode("utf-8")).hexdigest()
    row=db.execute("""SELECT conteudo_sha256 FROM grade_edicao
          WHERE dataset_id='NASA_POWER_AG' AND consulta_sha256=?
          LIMIT 1""",(req_sha,)).fetchone()
    if row is not None and not revisao_explicita:
        return {"estado":"CACHE_LOCAL_SEM_HTTP","consulta_sha256":req_sha,
                "ultimo_conteudo_sha256":row[0],
                "requisições_http":0,"atualizacao_forcada":False}
    opener=transporte or build_opener(_SemRedirecionamento())
    request=Request(url,headers={"Accept":"application/json",
                                 "User-Agent":"NIVON/1.0 approved NASA POWER manual ingestion"},
                    method="GET")
    try:
        with opener.open(request,timeout=timeout) as response:
            if getattr(response,"status",None)!=200:
                raise ErroCapturaPower("resposta HTTP NASA diferente de 200")
            remote=urlsplit(response.geturl()) if hasattr(response,"geturl") else urlsplit(url)
            if remote.scheme!="https" or remote.hostname!="power.larc.nasa.gov" or remote.path!=p.path:
                raise ErroCapturaPower("redirect inesperado ou origem diferente")
            mime=response.headers.get("Content-Type","") if hasattr(response,"headers") else ""
            if "json" not in mime.lower():
                raise ErroCapturaPower("NASA não retornou MIME JSON")
            raw=response.read(2_000_001)
    except ErroCapturaPower:
        raise
    except Exception:
        raise ErroCapturaPower("falha de rede NASA POWER: consulta manual não concluída") from None
    if not 1<=len(raw)<=2_000_000:
        raise ErroCapturaPower("payload NASA vazio ou excessivo")
    result=ingerir_power_local(
        db,bytes_json=raw,plano=plano,
        coletado_em=datetime.now(timezone.utc).isoformat(),
        publicado_em=None,
        classe="REAL_AUTORIZADO",
        permissoes=autorizacoes,
        licenca_evidencia=evidencia_licenca,
    )
    return {**result,"estado":"CAPTURADO_E_VERIFICADO_LOCAL",
            "requisições_http":1,"atualizacao_forcada":revisao_explicita,
            "publicacao_desconhecida":True,
            "modelos_preditivos_homologados":False}
