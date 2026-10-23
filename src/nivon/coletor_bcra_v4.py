"""BCRA Estadisticas Monetarias v4: serie historica com preservacao de revisoes.

Fonte: https://www.bcra.gob.ar/apis-banco-central/
Rota: /estadisticas/v4.0/Monetarias/{IdVariable}, segundo documentacao v4.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from .coletores_dados_reais import _get, ErroColetor
from .ingestao_fontes_reais import gravar_lote

BASE="https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/"
VARIAVEIS=frozenset({1})  # Reservas internacionais. Outros IDs exigem metadados v4.
MAX_LINHAS=250

def plano_bcra(*,variavel=1,inicio,fim,limite=MAX_LINHAS):
    if type(variavel)!=int or variavel not in VARIAVEIS:
        raise ErroColetor("idVariavel BCRA nao verificado")
    try:
        a=date.fromisoformat(inicio)
        b=date.fromisoformat(fim)
    except (TypeError,ValueError) as exc:
        raise ErroColetor("datas BCRA invalidas") from exc
    if a>b or (b-a).days>365 or b>date.today():
        raise ErroColetor("intervalo BCRA fora do limite")
    if type(limite)!=int or not 1<=limite<=MAX_LINHAS:
        raise ErroColetor("limite BCRA invalido")
    return BASE+str(variavel)+"?"+urlencode({
         "Desde":inicio,"Hasta":fim,"Limit":limite,"Offset":0
    })

def parse_bcra(raw, *,variavel=1):
    try:
        doc=json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ErroColetor("BCRA sem JSON valido") from exc
    if not isinstance(doc,dict) or doc.get("status") not in (0,200):
        raise ErroColetor("BCRA status invalido")
    out=doc.get("results")
    if not isinstance(out,list) or len(out)!=1 or not isinstance(out[0],dict):
        raise ErroColetor("BCRA results inesperado")
    serie=out[0]
    if serie.get("idVariable")!=variavel or not isinstance(serie.get("detalle"),list):
        raise ErroColetor("serie/idVariable BCRA inesperados")
    resultset=doc.get("metadata",{}).get("resultset",{})
    n=len(serie["detalle"])
    if n>MAX_LINHAS:
        raise ErroColetor("quantidade acima do limite BCRA")
    # Se existe paginacao, nao declarar recorte como completo.
    incompleto=bool(isinstance(resultset,dict) and
        isinstance(resultset.get("count"),int) and
        resultset["count"]>n)
    rows=[]
    for item in serie["detalle"]:
        if not isinstance(item,dict):
            raise ErroColetor("detalhe BCRA nao objeto")
        try:
            dia=date.fromisoformat(item.get("fecha"))
        except (TypeError,ValueError) as exc:
            raise ErroColetor("fecha BCRA invalida") from exc
        val=item.get("valor")
        if val is None:
            continue
        if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val):
            raise ErroColetor("valor BCRA nao numerico")
        rows.append({"identidade":f"BCRA_{variavel}|{dia.isoformat()}",
           "referencia":dia.isoformat(),"natureza":"INFORMADO","valor":val,
           "unidade":None,
           "campos":{"idVariable":variavel,"fecha":dia.isoformat(),
               "valor":val,"metadados_unidade_pendentes":True}})
    return rows,incompleto

def coletar_bcra(*,inicio,fim,banco,raw_dir,executar=False,variavel=1,
                 cliente=None,instante=None):
    if executar is not True:
        raise PermissionError("BCRA_HTTP_OFF")
    url=plano_bcra(variavel=variavel,inicio=inicio,fim=fim)
    raw,mime=_get(url,cliente=cliente,max_bytes=1_000_000,
                   tipos={"application/json","text/json","text/plain"})
    rows,incompleto=parse_bcra(raw,variavel=variavel)
    now=instante if instante is not None else datetime.now(timezone.utc)
    saida=gravar_lote(banco=banco,diretorio_bruto=raw_dir,dataset_id="ARG_BCRA_V1",
             origem=url,raw=raw,tipo="application/json",coletado_em=now,
             registros=rows,estado="NORMALIZED")
    saida.update({"fonte":"ARG_BCRA","pagina_incompleta":incompleto,
         "unidade_pendente":True,"publicavel":False,"go_live":False})
    return saida

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description="BCRA v4 - serie oficial historica no SQLite NIVON")
    p.add_argument("--inicio",required=True)
    p.add_argument("--fim",required=True)
    p.add_argument("--variavel",type=int,default=1)
    p.add_argument("--banco",default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir",default="data/nivon/raw")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    resp=coletar_bcra(inicio=args.inicio,fim=args.fim,variavel=args.variavel,
       banco=args.banco,raw_dir=args.raw_dir,executar=args.executar)
    print(json.dumps(resp,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
