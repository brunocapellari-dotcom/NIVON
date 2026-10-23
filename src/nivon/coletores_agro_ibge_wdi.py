"""Coletores oficiais IBGE PAM (1612) e Banco Mundial (WDI) para o NIVON.

Implementação deliberadamente restrita: séries anuais regionais, sem crawling,
sem inventar datas de publicação e sem tratar índices como volumes físicos.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from .coletores_dados_reais import _get, ErroColetor
from .ingestao_fontes_reais import gravar_lote

IBGE_BASE="https://servicodados.ibge.gov.br/api/v3/agregados/1612"
WDI_BASE="https://api.worldbank.org/v2/country"
ESTADOS={"MT":"51","MS":"50","GO":"52","PR":"41","RS":"43","SP":"35","MG":"31","BA":"29","PA":"15"}
PAISES=frozenset({"BRA","ARG","PRY","USA","CHN","CAN","AUS"})
INDICADORES={
    "AG.YLD.CREL.KG":("Rendimento de cereais","kg/ha"),
    "AG.LND.ARBL.HA":("Terra aravel","ha"),
    "AG.CON.FERT.ZS":("Consumo de fertilizante","kg/ha de terra aravel"),
    "AG.PRD.FOOD.XD":("Indice de producao de alimentos","indice"),
}
MAX_ROWS=1000

class ErroFonteAgro(ValueError):
    pass

def _year(ano):
    if type(ano)!=int or ano<1974 or ano>date.today().year:
        raise ErroFonteAgro("ano fora dos limites")
    return ano

def plano_ibge_pam(*,ano,uf="MT",variavel=214):
    ano=_year(ano)
    if uf not in ESTADOS:
        raise ErroFonteAgro("estado fora da allowlist")
    if variavel!=214:
        raise ErroFonteAgro("variavel PAM nao homologada")
    query=urlencode({"localidades":f"N3[{ESTADOS[uf]}]",
                    "classificacao":"81[all]"})
    return f"{IBGE_BASE}/periodos/{ano}/variaveis/{variavel}?{query}"

def _decimal(x):
    if isinstance(x,bool) or x is None:
        return None
    if isinstance(x,(float,int,Decimal)):
        try:
            val=Decimal(str(x))
        except InvalidOperation as exc:
            raise ErroFonteAgro("valor numerico invalido") from exc
    elif isinstance(x,str):
        cleaned=x.strip()
        if cleaned in {"X","..","...","","NaN"}:
            return None
        if cleaned=="-":
            return Decimal("0")  # convencao documentada IBGE: zero absoluto
        try:
            val=Decimal(cleaned.replace(" ",""))
        except InvalidOperation as exc:
            raise ErroFonteAgro("simbolo estatistico inesperado") from exc
    else:
        raise ErroFonteAgro("valor numerico invalido")
    if not val.is_finite():
        raise ErroFonteAgro("numero nao finito")
    return val

def parse_ibge_pam(raw, *,ano,uf,variavel=214):
    try:
        document=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ErroFonteAgro("IBGE JSON invalido") from exc
    if not isinstance(document,list) or len(document)!=1 or not isinstance(document[0],dict):
        raise ErroFonteAgro("IBGE exige 1 agregado de variavel")
    serie=document[0]
    if str(serie.get("id"))!=str(variavel):
        raise ErroFonteAgro("IBGE retornou variavel diferente")
    label=str(serie.get("variavel","")).casefold()
    unidade=str(serie.get("unidade","")).strip()
    if "quantidade produzida" not in label or not ("tonelada" in unidade.casefold()):
        raise ErroFonteAgro("variavel/unidade de producao PAM divergente")
    resultados=serie.get("resultados")
    if not isinstance(resultados,list) or not 1<=len(resultados)<=200:
        raise ErroFonteAgro("PAM sem resultados validos")
    output=[]
    codes=set()
    for result in resultados:
        classificacoes=result.get("classificacoes") if isinstance(result,dict) else None
        linhas=result.get("series") if isinstance(result,dict) else None
        if not isinstance(classificacoes,list) or not isinstance(linhas,list) or len(linhas)>20:
            raise ErroFonteAgro("resultado PAM inesperado")
        cat=next((c.get("categoria") for c in classificacoes if str(c.get("id"))=="81"),None)
        if not isinstance(cat,dict) or len(cat)!=1:
            raise ErroFonteAgro("categoria PAM nao identificada")
        cat_code,cat_name=next(iter(cat.items()))
        name=str(cat_name).strip().casefold()
        if name not in ("soja (em grão)","soja (em grao)","soja","milho (em grão)","milho (em grao)","milho"):
            continue
        product="SOJA" if name.startswith("soja") else "MILHO"
        for row in linhas:
            loc=row.get("localidade") if isinstance(row,dict) else None
            info=row.get("serie") if isinstance(row,dict) else None
            if (not isinstance(loc,dict) or str(loc.get("id"))!=ESTADOS[uf] or
                not isinstance(info,dict) or set(info)!={str(ano)}):
                raise ErroFonteAgro("serie PAM fora do recorte de ano/UF")
            valor=_decimal(info[str(ano)])
            if valor is None:
                continue
            identidade=f"{ano}|{uf}|{product}|{variavel}"
            if identidade in codes:
                raise ErroFonteAgro("PAM linha de mesmo produto duplicada")
            codes.add(identidade)
            output.append({"identidade":identidade,"referencia":f"{ano}-12-31",
                "competencia":str(ano),"natureza":"INFORMADO",
                "valor":str(valor),"unidade":"t",
                "campos":{"fonte":"IBGE_PAM_TABELA_1612","ano_civil":ano,
                    "uf":uf,"uf_codigo_ibge":ESTADOS[uf],"produto":product,
                    "categoria_codigo":str(cat_code),"variavel_codigo":variavel,
                    "valor_t":str(valor),"unidade_original":unidade,
                    "data_publicacao_nao_informada":True,
                    "anual_nao_estimativa_mensal":True}})
    return output

def coletar_ibge_pam(*,ano,uf,banco,raw_dir,executar=False,cliente=None,instante=None):
    if executar is not True:
        raise PermissionError("IBGE_PAM_FETCH_OFF")
    url=plano_ibge_pam(ano=ano,uf=uf)
    raw,mime=_get(url,cliente=cliente,max_bytes=1_600_000,tipos={"application/json","text/json"})
    linhas=parse_ibge_pam(raw,ano=ano,uf=uf)
    now=instante if instante is not None else datetime.now(timezone.utc)
    saida=gravar_lote(banco=banco,diretorio_bruto=raw_dir,
        dataset_id="BR_IBGE_PAM_PRODUCAO_UF",origem=url,raw=raw,tipo="application/json",
        coletado_em=now,registros=linhas,estado="NORMALIZED" if linhas else "RAW_RECEIVED")
    return {**saida,"fonte":"IBGE_PAM","uf":uf,"ano":ano,
        "dados_publicados":False,"data_publicacao_confirmada":False}

def plano_wdi(*,pais,indicador,inicio,fim):
    if pais not in PAISES or indicador not in INDICADORES:
        raise ErroFonteAgro("pais/indicador sem contrato WDI")
    a,b=_year(inicio),_year(fim)
    if a>b or b-a>20:
        raise ErroFonteAgro("janela de anos WDI excedida")
    return (f"{WDI_BASE}/{pais}/indicator/{indicador}?"+
        urlencode({"format":"json","date":f"{a}:{b}","per_page":"100"}))

def parse_wdi(raw, *,pais,indicador,inicio,fim):
    try:
        doc=json.loads(raw)
    except (UnicodeError,ValueError) as exc:
        raise ErroFonteAgro("JSON WDI invalido") from exc
    if not isinstance(doc,list) or len(doc)!=2 or not isinstance(doc[0],dict) or not isinstance(doc[1],list):
        raise ErroFonteAgro("WDI nao retornou pagina [meta, observations]")
    meta,rows=doc
    if (meta.get("pages") not in (1,"1") or
        not isinstance(rows,list) or len(rows)>100 or
        not isinstance(meta.get("total"),int)):
        raise ErroFonteAgro("paginacao WDI incompleta ou diferente")
    if int(meta["total"])!=len(rows):
        raise ErroFonteAgro("WDI precisa resultado completo")
    output=[]
    _,unit=INDICADORES[indicador]
    seen=set()
    for item in rows:
        if not isinstance(item,dict):
            raise ErroFonteAgro("observacao WDI nao e objeto")
        cc=item.get("countryiso3code")
        indicador_meta=item.get("indicator")
        if (cc!=pais or not isinstance(indicador_meta,dict) or
                indicador_meta.get("id")!=indicador):
            raise ErroFonteAgro("pais ou indicador WDI nao correspondem")
        year=item.get("date")
        if not isinstance(year,str) or not year.isdigit() or not inicio<=int(year)<=fim:
            raise ErroFonteAgro("ano WDI fora do recorte")
        val=_decimal(item.get("value"))
        if val is None:
            continue
        status=str(item.get("obs_status") or "").strip()
        natureza="PROJETADO" if status.upper()=="F" else "INFORMADO"
        ident=f"{pais}|{indicador}|{year}"
        if ident in seen:
            raise ErroFonteAgro("WDI retornou duplicata")
        seen.add(ident)
        output.append({"identidade":ident,"referencia":f"{year}-12-31",
            "competencia":year,"natureza":natureza,
            "valor":str(val),"unidade":unit,
            "campos":{"pais_iso3":pais,"indicador":indicador,
                "ano_civil":int(year),"valor":str(val),"unidade":unit,
                "fonte":"WORLD_BANK_WDI","obs_status":status or None,
                "data_publicacao_nao_informada":True}})
    return output

def coletar_wdi(*,pais,indicador,inicio,fim,banco,raw_dir,
                executar=False,cliente=None,instante=None):
    if executar is not True:
        raise PermissionError("WDI_FETCH_OFF")
    url=plano_wdi(pais=pais,indicador=indicador,inicio=inicio,fim=fim)
    raw,mime=_get(url,cliente=cliente,max_bytes=350_000,tipos={"application/json","text/json"})
    linhas=parse_wdi(raw,pais=pais,indicador=indicador,inicio=inicio,fim=fim)
    now=instante if instante is not None else datetime.now(timezone.utc)
    result=gravar_lote(banco=banco,diretorio_bruto=raw_dir,
       dataset_id="WORLD_BANK_AGRO_INDICADORES",origem=url,raw=raw,
       tipo="application/json",coletado_em=now,registros=linhas,
       estado="NORMALIZED" if linhas else "RAW_RECEIVED")
    return {**result,"fonte":"WORLD_BANK_WDI","pais":pais,
        "indicador":indicador,"dados_publicados":False}

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description="NIVON — novas fontes agrícolas oficiais")
    p.add_argument("--fonte",required=True,choices=("ibge","wdi"))
    p.add_argument("--uf",default="MT",choices=sorted(ESTADOS))
    p.add_argument("--ano",type=int)
    p.add_argument("--pais",default="BRA",choices=sorted(PAISES))
    p.add_argument("--indicador",default="AG.YLD.CREL.KG",choices=sorted(INDICADORES))
    p.add_argument("--inicio",type=int)
    p.add_argument("--fim",type=int)
    p.add_argument("--banco",default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir",default="data/nivon/raw")
    p.add_argument("--executar",action="store_true")
    a=p.parse_args(argv)
    if a.fonte=="ibge":
        if a.ano is None: p.error("IBGE exige --ano")
        result=coletar_ibge_pam(ano=a.ano,uf=a.uf,banco=a.banco,
                                raw_dir=a.raw_dir,executar=a.executar)
    else:
        if a.inicio is None or a.fim is None: p.error("WDI exige --inicio --fim")
        result=coletar_wdi(pais=a.pais,indicador=a.indicador,inicio=a.inicio,fim=a.fim,
                            banco=a.banco,raw_dir=a.raw_dir,executar=a.executar)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
