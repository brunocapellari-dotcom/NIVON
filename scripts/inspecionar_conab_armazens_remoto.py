"""Consulta manual e limitada SOMENTE ao cabeçalho TXT CONAB; sem gravação."""
import argparse
import csv
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL="https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt"
MAX_BYTES=16384

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None

def obter():
    req=Request(URL,headers={"User-Agent":"NIVON/0.2 schema-only",
                              "Accept":"text/plain,application/octet-stream",
                              "Range":"bytes=0-16383"})
    try:
        with build_opener(NoRedirect()).open(req,timeout=15) as response:
            mime=response.headers.get("Content-Type","").lower().split(";",1)[0]
            if response.status not in (200,206) or response.geturl()!=URL:
                return {"status":"REDIRECT_OU_STATUS_INESPERADO"}
            if mime not in ("text/plain","application/octet-stream","text/csv"):
                return {"status":"MIME_NAO_TABULAR","tipo":mime[:80]}
            raw=response.read(MAX_BYTES)
    except (OSError,TimeoutError,HTTPError,URLError) as exc:
        return {"status":"FALHA_DE_ACESSO","classe":type(exc).__name__}
    for enc in ("utf-8-sig","cp1252"):
        try:
            line=raw.decode(enc).splitlines()[0]
            break
        except (UnicodeError,IndexError):
            continue
    else:
        return {"status":"CODIFICACAO_INDEFINIDA"}
    if not line or len(line)>8000 or line.lstrip().lower().startswith(("<html","<!doctype")):
        return {"status":"RESPOSTA_NAO_TABULAR"}
    options={}
    for name,sep in (("semicolon",";"),("pipe","|"),("tab","\t"),("comma",",")):
        options[name]=len(next(csv.reader([line],delimiter=sep)))
    cols=next(csv.reader([line],delimiter=";"))
    # Apenas ROTULOS do cabecalho; os registros permanecem descartados.
    rotulos=[" ".join(x.split())[:90] for x in cols]
    return {"status":"CABECALHO_RECEBIDO_NAO_HOMOLOGADO",
            "codificacao":enc,"colunas_estimadas":options,
            "rotulos_cabecalho":rotulos,
            "amostra_bytes":len(raw),"registros_individuais_expostos":0}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--explicit-yes",action="store_true")
    x=p.parse_args()
    if not x.explicit_yes:
        raise SystemExit("DESABILITADO_POR_PADRAO")
    print(json.dumps(obter(),ensure_ascii=False))
