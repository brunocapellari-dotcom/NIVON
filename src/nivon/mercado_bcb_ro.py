"""BCB/SGS publico, fonte nao-canonica, lida pelo mesmo Cloud Run NIVON."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import Request, build_opener, HTTPRedirectHandler
import json
import re

SOURCES=(("ptax_usd_venda",1,"Dólar de referência · venda","BRL/USD"),
         ("selic_diaria",11,"Selic efetiva diária","% ao dia"))
MAX_BYTES=12000
DATE=re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
VALUE=re.compile(r"^\d{1,5}(?:[,.]\d{1,10})?$")

class ErroBCB(ValueError):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def parse(raw,now=None):
    now=now or datetime.now(timezone.utc)
    if now.utcoffset() is None or not isinstance(raw,list) or not 1<=len(raw)<=20:
        raise ErroBCB("lote/tempo invalido")
    points=[]
    for entry in raw:
        if not isinstance(entry,dict) or not isinstance(entry.get("data"),str) or not isinstance(entry.get("valor"),str):
            raise ErroBCB("campos invalidos")
        m=DATE.fullmatch(entry["data"])
        if not m or not VALUE.fullmatch(entry["valor"]):
            raise ErroBCB("formato invalido")
        try:
            day=date(int(m[3]),int(m[2]),int(m[1]))
            value=Decimal(entry["valor"].replace(",","."))
        except (ValueError,InvalidOperation) as exc:
            raise ErroBCB("valor/data invalida") from exc
        if not value.is_finite() or value<0 or day>now.date():
            raise ErroBCB("valor/referencia invalidos")
        points.append((day,value))
    day,value=max(points,key=lambda v:v[0])
    age=(now.date()-day).days
    return {"value":float(value),"referencia":day.isoformat(),"idade_dias":age,
            "status":"SOURCE_LAG" if age>5 else "INFORMADO"}

def fetch_sgs(code):
    if type(code) is not int or code not in (1,11):
        raise ErroBCB("codigo nao autorizado")
    url=f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/5?formato=json"
    req=Request(url,headers={"Accept":"application/json","User-Agent":"NIVON-BancoCentral/1"})
    with build_opener(NoRedirect).open(req,timeout=6) as res:
        if "json" not in res.headers.get("Content-Type","").lower():
            raise ErroBCB("BCB JSON esperado")
        length=res.headers.get("Content-Length")
        if length and int(length)>MAX_BYTES:
            raise ErroBCB("corpo excessivo")
        body=res.read(MAX_BYTES+1)
        if len(body)>MAX_BYTES:
            raise ErroBCB("corpo excessivo")
    return json.loads(body.decode("utf-8"))

def consultar(*,now=None,reader=None):
    now=now or datetime.now(timezone.utc)
    reader=reader or fetch_sgs
    result={}
    ok=0
    for key,code,label,unit in SOURCES:
        try:
            doc=parse(reader(code),now)
            if doc["value"]>(100 if code==1 else 10):
                raise ErroBCB("escala invalida")
            result[key]={"key":key,"code":code,"label":label,"unit":unit,
                         **doc,"fonte":"Banco Central do Brasil (SGS)"}
            ok+=1
        except Exception:
            result[key]={"key":key,"code":code,"label":label,"unit":unit,
                         "status":"FONTE_INDISPONIVEL","value":None,"referencia":None,
                         "fonte":"Banco Central do Brasil (SGS)"}
    return {"versao":"nivon.mercado.publico.v1",
            "status":"DISPONIVEL" if ok==2 else "PARCIAL" if ok else "INDISPONIVEL",
            "consultado_em":now.isoformat(),"leitura_somente":True,
            "origem":"API_PUBLICA_BCB_SEM_PERSISTENCIA",
            "nuvem_google_atualizada":False,"series":result}
