"""Inspeção transitória e limitada SOMENTE de SCHEMA em APIs públicas.

Não é coletor permanente. Apenas emissão de nomes de campos, tipos e rótulos
do cabeçalho SIDRA, jamais valores, CNPJ, municípios, preços ou séries.
Sem redirects, credenciais, armazenamento, retries ou contorno de WAF.
"""
from __future__ import annotations
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

URL_SIDRA=("https://apisidra.ibge.gov.br/values/t/1612/"
           "n6/5107925/v/214/p/2024/c81/2702/h/y/f/a")
URL_PTAX=("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
          "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
          "?%40dataInicial=%2708-01-2025%27&%40dataFinalCotacao=%2708-05-2025%27"
          "&%24format=json&%24top=20")
_URLS={"SIDRA":URL_SIDRA,"PTAX":URL_PTAX}
_MAX=128_000

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        return None

def verificar_estrutura(provider,*,opener=None):
    if provider not in _URLS:
        raise ValueError("provedor desconhecido")
    url=_URLS[provider]
    host=urlsplit(url).hostname
    if host not in ("apisidra.ibge.gov.br","olinda.bcb.gov.br"):
        raise ValueError("domínio inesperado")
    client=opener if opener is not None else build_opener(_NoRedirect())
    req=Request(url,headers={"User-Agent":"NIVON/0.2 schema-inspection",
                             "Accept":"application/json"})
    try:
        with client.open(req,timeout=15) as response:
            if response.status!=200 or response.geturl()!=url:
                return {"provedor":provider,"estado":"STATUS_OU_REDIRECT_INESPERADO"}
            mime=response.headers.get("Content-Type","").lower().split(";",1)[0]
            if mime not in ("application/json","text/json"):
                return {"provedor":provider,"estado":"MIME_NAO_JSON"}
            raw=response.read(_MAX+1)
    except (OSError,TimeoutError,HTTPError,URLError) as exc:
        return {"provedor":provider,"estado":"ACESSO_INDISPONIVEL","classe":type(exc).__name__}
    if not raw or len(raw)>_MAX:
        return {"provedor":provider,"estado":"JSON_AUSENTE_OU_GRANDE"}
    try:
        obj=json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError,ValueError):
        return {"provedor":provider,"estado":"JSON_INVALIDO"}
    if provider=="SIDRA":
        if not isinstance(obj,list) or not obj or not isinstance(obj[0],dict):
            return {"provedor":provider,"estado":"FORMATO_NAO_LISTA_COM_HEADER"}
        descritores={k:str(v)[:85] for k,v in obj[0].items()
                     if k in ("NC","NN","MC","MN","V","D1C","D1N","D2C","D2N",
                              "D3C","D3N","D4C","D4N","D5C","D5N")}
        return {"provedor":provider,"estado":"HEADER_RECEBIDO_SEM_HOMOLOGACAO",
                "colunas_cabecalho":descritores,"linhas_sem_expor_valores":max(0,len(obj)-1)}
    if not isinstance(obj,dict) or not isinstance(obj.get("value"),list):
        return {"provedor":provider,"estado":"ODATA_SEM_VALUE"}
    keys=sorted(obj["value"][0].keys()) if obj["value"] else []
    return {"provedor":provider,"estado":"ODATA_RECEBIDO_SEM_HOMOLOGACAO",
            "campos_de_uma_cotacao":keys,
            "quantidade_sem_expor_valores":len(obj["value"]),
            "paginacao_indicada":bool(obj.get("@odata.nextLink"))}

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--explicit-yes",action="store_true")
    args=p.parse_args(argv)
    if not args.explicit_yes:
        print(json.dumps({"estado":"DESABILITADO_POR_PADRAO"}))
        return 2
    for id in ("SIDRA","PTAX"):
        print(json.dumps(verificar_estrutura(id),ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
