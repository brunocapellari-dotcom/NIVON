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
    # Somente estatísticas sintáticas de ate 20 linhas completas. Nunca mostrar valores.
    import re
    blocos=raw.decode(enc).splitlines()
    linhas=list(csv.DictReader(blocos[:-1],delimiter=";"))[:20]
    padroes={"inteiro":0,"ptbr_agrupado":0,"ptbr_decimal":0,"ponto_decimal":0,"outro":0}
    identificadores=set()
    codigo_ibge_ok=0
    linhas_validas=0
    for linha in linhas:
        if None in linha or linha.get("identificacao_armazem") is None:
            continue
        linhas_validas+=1
        identificadores.add(linha.get("identificacao_armazem",""))
        cap=str(linha.get("qtd_capacidade_estatica(t)","")).strip()
        if re.fullmatch(r"[0-9]+",cap):
            padroes["inteiro"]+=1
        elif re.fullmatch(r"[0-9]{1,3}(?:\\.[0-9]{3})+,[0-9]{1,3}",cap):
            padroes["ptbr_agrupado"]+=1
        elif re.fullmatch(r"[0-9]+,[0-9]{1,3}",cap):
            padroes["ptbr_decimal"]+=1
        elif re.fullmatch(r"[0-9]+\\.[0-9]{1,3}",cap):
            padroes["ponto_decimal"]+=1
        else:
            padroes["outro"]+=1
        if re.fullmatch(r"[0-9]{7}",str(linha.get("cod_ibge","")).strip()):
            codigo_ibge_ok+=1
    return {"status":"CABECALHO_RECEBIDO_NAO_HOMOLOGADO",
            "codificacao":enc,"colunas_estimadas":options,
            "rotulos_cabecalho":rotulos,
            "amostra_bytes":len(raw),"registros_individuais_expostos":0,
            "linhas_analisadas_sem_publicar_valores":linhas_validas,
            "id_unico_na_amostra":len(identificadores)==linhas_validas,
            "codigos_ibge_7_digitos":codigo_ibge_ok,
            "padroes_numericos":padroes}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--explicit-yes",action="store_true")
    x=p.parse_args()
    if not x.explicit_yes:
        raise SystemExit("DESABILITADO_POR_PADRAO")
    print(json.dumps(obter(),ensure_ascii=False))
