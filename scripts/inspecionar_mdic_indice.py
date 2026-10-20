"""Inspeção pontual do índice MDIC; somente metadados de links, sem CSV."""
from __future__ import annotations
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urljoin,urlsplit
from urllib.request import HTTPRedirectHandler,Request,build_opener
from urllib.error import HTTPError,URLError

INDEX=("https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/"
       "estatisticas/base-de-dados-bruta")
MAX=800_000

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a":
            href=dict(attrs).get("href")
            if href:self.links.append(href)

def obter(*,abridor=None):
    client=abridor if abridor is not None else build_opener(_NoRedirect())
    try:
        with client.open(Request(INDEX,headers={
            "User-Agent":"NIVON/0.2 mdic-metadata-only","Accept":"text/html"}),timeout=20) as response:
            if response.status!=200 or response.geturl()!=INDEX:
                return {"status":"REDIRECT_OU_STATUS_NAO_ACEITO"}
            if response.headers.get("Content-Type","").split(";",1)[0].strip().lower()!="text/html":
                return {"status":"MIME_NAO_HTML"}
            data=response.read(MAX+1)
    except (HTTPError,URLError,OSError,TimeoutError) as exc:
        return {"status":"SEM_ACESSO","erro_tipo":type(exc).__name__}
    if not data or len(data)>MAX:
        return {"status":"HTML_AUSENTE_OU_GRANDE"}
    parser=_Links()
    try:
        parser.feed(data.decode("utf-8"))
    except (UnicodeError,ValueError):
        return {"status":"HTML_NAO_DECODIFICADO"}
    hosts=Counter()
    anos=Counter()
    nomes=[]
    for href in parser.links:
        u=urlsplit(urljoin(INDEX,href))
        if u.scheme not in ("https","http") or not u.hostname:continue
        path=u.path.lower()
        if not any(path.endswith(x) for x in (".csv",".zip",".xlsx",".xls")):
            continue
        hosts[u.hostname]+=1
        nome=PurePosixPath(u.path).name
        if any(y in nome for y in ("2025","2026")) and len(nomes)<15:
            nomes.append({"arquivo":nome[:110],"host":u.hostname})
        for y in ("2025","2026"):
            if y in nome:anos[y]+=1
    return {"status":"METADADOS_LINKS_HTML_SEM_DOWNLOAD",
            "links_arquivo_por_host":dict(sorted(hosts.items())),
            "arquivos_com_ano":dict(sorted(anos.items())),
            "amostras_nome_arquivo":nomes,
            "coletados_csv":0,"redirecionamentos":0}

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--explicit-yes",action="store_true")
    args=p.parse_args()
    if not args.explicit_yes:
        raise SystemExit("DESABILITADO_POR_PADRAO")
    print(json.dumps(obter(),ensure_ascii=False))
