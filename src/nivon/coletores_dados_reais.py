"""Coletores executáveis de séries e arquivos públicos (sem crawling).

Argentina: séries temporais oficiais, dados numéricos com data/unidade.
Canadá: CSV acumulado oficial por safra, snapshot bruto + inspeção de cabeçalho.
CCEE: catálogo CKAN público; descarga do recurso CSV só após verificar licença,
domínio, extensão, formato e tamanho. Nenhuma extração oculta de dashboard.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .ingestao_fontes_reais import gravar_lote

BASE_SERIES = "https://apis.datos.gob.ar/series/api/series/"
CANADA_CSV = "https://grainscanada.gc.ca/en/grain-research/statistics/grain-statistics-weekly/{safra}/gsw-shg-en.csv"
CCEE_PACKAGE = "https://dadosabertos.ccee.org.br/api/3/action/package_show?id=pld_horario"
CAMBIO_AR = "168.1_T_CAMBIOR_D_0_0_26"
ALLOW_HOSTS = frozenset({
    "apis.datos.gob.ar", "grainscanada.gc.ca", "www.grainscanada.gc.ca",
    "dadosabertos.ccee.org.br", "pda-download.ccee.org.br", "api.bcra.gob.ar",
    "granosar.lfcaucino.workers.dev",
})
MAX_TRANSFER = 18_000_000
SERIES_LIMIT = 500
MAX_NORMALIZED = 500

class ErroColetor(ValueError):
    pass

class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None

def _get(url, *, cliente=None, max_bytes=MAX_TRANSFER, tipos=None):
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in ALLOW_HOSTS or
            p.port not in (None,443) or p.username or p.password or p.fragment):
        raise ErroColetor("destino fora da allowlist HTTPS")
    abrir=cliente if cliente is not None else build_opener(_SemRedirect())
    with abrir.open(Request(url,headers={"Accept":"application/json,text/csv,application/octet-stream",
        "User-Agent":"NIVON/0.1 open-data non-commercial"}),
        timeout=30) as resp:
        if int(resp.status)!=200 or resp.geturl()!=url:
            raise ErroColetor("HTTP/redirect inesperado")
        mime=str(resp.headers.get("Content-Type","")).split(";",1)[0].lower().strip()
        if tipos and mime not in tipos:
            raise ErroColetor("MIME diferente do esperado: "+mime)
        raw=resp.read(max_bytes+1)
    if not isinstance(raw,bytes) or not 1<=len(raw)<=max_bytes:
        raise ErroColetor("resposta vazia ou acima do limite")
    return raw,mime

def plano_series_argentina(*, inicio, fim, serie=CAMBIO_AR, limite=SERIES_LIMIT):
    if serie!=CAMBIO_AR:
        raise ErroColetor("serie argentina nao homologada")
    try:
        d1=date.fromisoformat(inicio)
        d2=date.fromisoformat(fim)
    except (ValueError,TypeError) as exc:
        raise ErroColetor("datas ISO necessarias") from exc
    if not d1<=d2 or (d2-d1).days>365 or d2>date.today():
        raise ErroColetor("janela fora do limite")
    if type(limite)!=int or not 1<=limite<=SERIES_LIMIT:
        raise ErroColetor("limite de linhas invalido")
    return BASE_SERIES+"?"+urlencode({
        "ids":serie, "start_date":inicio,"end_date":fim,
        "format":"json", "metadata":"full","limit":limite, "sort":"asc"
    })

def parse_series_argentina(raw, *, serie=CAMBIO_AR):
    try:
        doc=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ErroColetor("JSON argentino invalido") from exc
    if not isinstance(doc,dict) or not isinstance(doc.get("data"),list):
        raise ErroColetor("resposta argentina sem data")
    rows=doc["data"]
    if len(rows)>MAX_NORMALIZED:
        raise ErroColetor("pagina de series excede limite")
    if doc.get("error") or doc.get("errors"):
        raise ErroColetor("erro informado pela API")
    ret=[]
    for pair in rows:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:
            raise ErroColetor("par [data,valor] esperado")
        dia,val=pair
        try:
            dd=date.fromisoformat(dia)
        except (TypeError,ValueError) as exc:
            raise ErroColetor("referencia temporal invalida") from exc
        if val is None:
            continue
        if isinstance(val,bool) or not isinstance(val,(float,int)) or not math.isfinite(val):
            raise ErroColetor("valor numerico inesperado")
        ret.append({
            "identidade":serie+"|"+dia,"referencia":dd.isoformat(),
            "natureza":"INFORMADO", "valor":val, "unidade":"ARS por USD (verificar metadado)",
            "campos":{"serie":serie,"data":dia,"valor":val,
                "unidade_provisoria":True,"fonte":"Argentina Series API"}
        })
    return ret

def _safra_canada(safra):
    if not isinstance(safra,str) or not re.fullmatch(r"20\d{2}-\d{2}",safra):
        raise ErroColetor("safra canada invalida")
    a,b=safra.split("-")
    if int(b)!=(int(a)+1)%100 or not 2000<=int(a)<=date.today().year:
        raise ErroColetor("safra canadense fora do intervalo")
    return CANADA_CSV.format(safra=safra)

def parse_csv_canada(raw):
    # Classifica como RAW até confirmar nomes das colunas em amostra real.
    try:
        decoded=raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroColetor("CSV canadense nao UTF-8") from exc
    reader=csv.reader(io.StringIO(decoded,newline=""))
    head=next(reader,None)
    if not head or len(head)>100:
        raise ErroColetor("CSV canada sem cabecalho")
    if any(not isinstance(x,str) or len(x)>160 for x in head):
        raise ErroColetor("colunas canadenses invalidas")
    return {"cabecalho":head[:30],"linhas_sample":sum(1 for _,r in zip(range(20),reader) if r)}

def normalizar_csv_canada(raw):
    """Extrai cultura/semana/metric de tabela CSV oficial, mantendo revisoes RAW.

    Unidade original 'Ktonnes' e convertida para tonelada somente com colunas
    explicitamente conferidas. Dados nao sao comparaveis entre metricas.
    """
    try:
        stream=io.StringIO(raw.decode("utf-8-sig"),newline="")
    except UnicodeError as exc:
        raise ErroColetor("canada CSV nao UTF-8") from exc
    table=csv.DictReader(stream)
    obrigatorio={"Crop Year","Grain Week","Week Ending Date","worksheet",
                 "metric","period","grain","grade","Region","Ktonnes"}
    if not table.fieldnames or not obrigatorio<=set(table.fieldnames):
        return [],{"status_parser":"SCHEMA_NOT_MATCHING","expected":sorted(obrigatorio)}
    selecionados={"soybeans","corn","wheat","canola"}
    registros=[]
    lidas=0
    for d in table:
        lidas+=1
        if lidas>120000:
            raise ErroColetor("CSV canada excede linhas permitidas")
        grain=str(d.get("grain") or "").strip()
        if grain.casefold() not in selecionados:
            continue
        v=str(d.get("Ktonnes") or "").strip().replace(",","")
        if not v or v in {"-","..","N/A"}:
            continue
        try:
            decimal=Decimal(v)
        except InvalidOperation:
            raise ErroColetor("Ktonnes canada nao numerico")
        if not decimal.is_finite():
            raise ErroColetor("Ktonnes canada invalido")
        data=str(d.get("Week Ending Date") or "").split(" ")[0]
        try:
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", data):
                data=datetime.strptime(data, "%d/%m/%Y").date().isoformat()
            else:
                data=date.fromisoformat(data).isoformat()
        except ValueError as exc:
            raise ErroColetor("data semanal canada invalida") from exc
        identidade="|".join([str(d.get(k) or "") for k in
           ("Crop Year","Grain Week","worksheet","metric","period","grain","grade","Region")])
        if not identidade or len(identidade)>180:
            raise ErroColetor("identidade canada longa/invalida")
        tonnes=decimal*1000
        registros.append({
            "identidade":identidade,"referencia":data,
            "competencia":str(d.get("Crop Year")),"natureza":"INFORMADO",
            "valor":str(tonnes),"unidade":"t",
            "campos":{"region":d.get("Region"),"grain":grain,
              "metric":d.get("metric"),"period":d.get("period"),
              "worksheet":d.get("worksheet"),"grade":d.get("grade"),
              "crop_year":d.get("Crop Year"),"grain_week":d.get("Grain Week"),
              "source_ktonnes":str(decimal),"tonnes":str(tonnes),
              "unidade_original":"Ktonnes"}
        })
        if len(registros)>18000:
            raise ErroColetor("mais de 18000 series canada; particionar antes")
    return registros,{"status_parser":"MAPPED","linhas_total_csv":lidas,
             "observacoes_alvo":len(registros),"grains":sorted(selecionados)}

def normalizar_ccee_pld(raw):
    """Preço horário informado CCEE, R$/MWh, com hora local da fonte.

    Cada registro preserva submercado, mês, dia, hora e período
    de comercialização; evita comparar períodos diferentes como uma observação.
    """
    try:
        doc=raw.decode("utf-8-sig")
    except (UnicodeError,AttributeError) as exc:
        raise ErroColetor("CCEE CSV exige UTF-8") from exc
    reader=csv.DictReader(io.StringIO(doc), delimiter=";")
    cols={"MES_REFERENCIA","SUBMERCADO","PERIODO_COMERCIALIZACAO",
          "DIA","HORA","PLD_HORA"}
    if not reader.fieldnames or set(reader.fieldnames)!=cols:
        raise ErroColetor("schema CCEE desconhecido")
    dados=[]
    for n,r in enumerate(reader):
        if n>=75000:
            raise ErroColetor("CCEE CSV excede limite de linhas")
        try:
            mes=str(r["MES_REFERENCIA"])
            if not re.fullmatch(r"[0-9]{6}",mes):
                raise ValueError("referencia")
            ano,month=int(mes[:4]),int(mes[4:])
            if not 2000<=ano<=date.today().year:
                raise ValueError("ano invalido")
            day,hour,periodo=[int(str(r[k])) for k in
                           ("DIA","HORA","PERIODO_COMERCIALIZACAO")]
            dt=date(ano,month,day)
            if not 0<=hour<=23 or periodo!=(day-1)*24+hour+1:
                raise ValueError("hora/periodo incompatível")
            sub=str(r["SUBMERCADO"]).strip().upper()
            if not re.fullmatch(r"[A-Z_/ -]{2,40}",sub):
                raise ValueError("submercado invalido")
            v=Decimal(str(r["PLD_HORA"]).strip())
            if not v.is_finite() or not 0<=v<=100000:
                raise ValueError("PLD fora de faixa")
        except (ValueError,TypeError,InvalidOperation) as exc:
            raise ErroColetor("linha CCEE invalida "+str(n+2)) from exc
        dados.append({
            "identidade":f"{mes}|{sub}|{day:02d}|{hour:02d}|{periodo}",
            "referencia":dt.isoformat(),"competencia":mes,"natureza":"INFORMADO",
            "valor":str(v),"unidade":"R$/MWh",
            "campos":{"mes_referencia":mes,"submercado":sub,
                "periodo_comercializacao":periodo,"dia":day,"hora":hour,
                "pld_hora":str(v),"unidade_original":"R$/MWh",
                "classificacao":"preco informado CCEE","fuso_utc_nao_inferido":True}
        })
    if not dados:
        raise ErroColetor("CCEE CSV sem observacoes")
    return dados

def plano_ccee():
    return CCEE_PACKAGE

def _parse_ckan(raw):
    try:
        doc=json.loads(raw)
    except (UnicodeError,ValueError) as exc:
        raise ErroColetor("CKAN nao JSON") from exc
    if (not isinstance(doc,dict) or doc.get("success") is not True
            or not isinstance(doc.get("result"),dict)):
        raise ErroColetor("CKAN sem result")
    result=doc["result"]
    if result.get("name")!="pld_horario":
        raise ErroColetor("pacote CKAN inesperado")
    licenca=str(result.get("license_id") or "").lower()
    resources=result.get("resources")
    if not isinstance(resources,list) or len(resources)>1500:
        raise ErroColetor("CKAN recursos invalidos")
    return licenca, resources

def _recurso_ccee(resources, resource_id):
    if not isinstance(resource_id,str) or not re.fullmatch(r"[0-9a-fA-F-]{36}",resource_id):
        raise ErroColetor("resource_id deve ser UUID da API")
    encontrados=[r for r in resources if isinstance(r,dict) and r.get("id")==resource_id]
    if len(encontrados)!=1:
        raise ErroColetor("id nao pertence ao pacote")
    r=encontrados[0]
    if str(r.get("format","")).upper()!="CSV":
        raise ErroColetor("recurso nao e CSV")
    url=r.get("url")
    if not isinstance(url,str):
        raise ErroColetor("URL nao encontrada")
    p=urlsplit(url)
    dominio_arquivo = (
        p.hostname == "dadosabertos.ccee.org.br" and p.path.lower().endswith(".csv")
    )
    dominio_cdn = (
        p.hostname == "pda-download.ccee.org.br" and
        re.fullmatch(r"/[A-Za-z0-9_-]{20,80}/content", p.path) is not None
    )
    if (p.scheme!="https" or p.port not in (None,443) or
        p.username or p.password or p.query or p.fragment or
        not (dominio_arquivo or dominio_cdn)):
        raise ErroColetor("recurso fora da origem autorizada")
    return url

def executar_coleta(*, fonte, banco, raw_dir, executar=False,
                     inicio=None, fim=None, safra=None, recurso_id=None,
                     cliente=None, instante=None):
    """Coleta uma janela por chamada. Persistência RAW e linhas normalizadas."""
    if executar is not True:
        raise PermissionError("COLETA_REAL_DESABILITADA_SEM_EXECUCAO_EXPLICITA")
    instante=datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(instante,datetime) or instante.utcoffset() is None:
        raise ErroColetor("instante deve ter timezone")
    notas={}
    if fonte=="ARG_SERIES_CAMBIO":
        url=plano_series_argentina(inicio=inicio,fim=fim)
        raw,mime=_get(url,cliente=cliente,tipos={"application/json","text/json"})
        dados=parse_series_argentina(raw)
        dataset="ARG_SERIES_CAMBIO_DIARIO"
        estado="NORMALIZED" if dados else "RAW_RECEIVED"
        if not dados:
            notas={"sem_observacoes_na_janela":True,"fonte_desatualizada_ou_sem_dados":True}
    elif fonte=="CAN_GRAINS_WEEKLY":
        url=_safra_canada(safra)
        raw,mime=_get(url,cliente=cliente,max_bytes=MAX_TRANSFER,
                      tipos={"text/csv","application/octet-stream","text/plain","application/csv"})
        notas=parse_csv_canada(raw)
        dados,parsed=normalizar_csv_canada(raw)
        notas.update(parsed)
        dataset="CAN_GRAINS_CROP_YEAR_WEEKLY"
        estado="NORMALIZED" if dados else "RAW_RECEIVED"
    elif fonte=="BR_CCEE_PLD":
        url=plano_ccee()
        meta,mime=_get(url,cliente=cliente,max_bytes=1_500_000,
                       tipos={"application/json","text/json"})
        licenca,resources=_parse_ckan(meta)
        if recurso_id is None:
            return {"fonte":fonte,"estado":"METADATA_ONLY",
                "licenca":licenca,"csv_resources":[{"id":r.get("id"),"nome":r.get("name")}
                    for r in resources if isinstance(r,dict) and str(r.get("format","")).upper()=="CSV"][:50],
                "persistido":False}
        if licenca not in {"cc-by","cc-by-4.0","cc-by-3.0","cc-by-2.0"}:
            raise PermissionError("licenca CCEE nao comprovada para download neste coletor")
        url=_recurso_ccee(resources,recurso_id)
        raw,mime=_get(url,cliente=cliente,tipos={"text/csv","text/plain","application/octet-stream","application/csv"})
        dados=normalizar_ccee_pld(raw)
        dataset="BR_CCEE_PLD_HORARIO"
        estado="NORMALIZED"
        notas={"recurso_id":recurso_id,"hash_catalogo":hashlib.sha256(meta).hexdigest(),
               "licenca":licenca,"observacoes_parseadas":len(dados)}
    else:
        raise ErroColetor("fonte nao possui coleta homologada: "+str(fonte))
    saida=gravar_lote(banco=banco,diretorio_bruto=raw_dir,dataset_id=dataset,
                origem=url,raw=raw,tipo=mime if mime in (
                  "text/csv","application/json","application/octet-stream") else "text/csv",
                coletado_em=instante,registros=dados,estado=estado)
    saida.update({"fonte":fonte,"notas":notas,
                  "publicavel":False,"go_live":False})
    return saida

def main(argv=None):
    p=argparse.ArgumentParser(description="Coletores NIVON - dados reais, coleta pontual")
    p.add_argument("--fonte",required=True,choices=("ARG_SERIES_CAMBIO","CAN_GRAINS_WEEKLY","BR_CCEE_PLD"))
    p.add_argument("--banco",default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir",default="data/nivon/raw")
    p.add_argument("--inicio")
    p.add_argument("--fim")
    p.add_argument("--safra")
    p.add_argument("--recurso-id")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    out=executar_coleta(fonte=args.fonte,banco=args.banco,raw_dir=args.raw_dir,
        inicio=args.inicio,fim=args.fim,safra=args.safra,recurso_id=args.recurso_id,
        executar=args.executar)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
