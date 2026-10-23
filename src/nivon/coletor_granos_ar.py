"""Coleta oficial da API pública do provedor secundário granos.ar.

Conforme https://granos.ar/api-docs/ (Fase 1 grátis; atribuição requerida).
Não substitui BCR, SIO Granos, SAGyP ou negociação real; classificação INFORMADO.
"""
from __future__ import annotations
import json
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from .coletores_dados_reais import _get, ErroColetor
from .ingestao_fontes_reais import gravar_lote

BASE="https://granosar.lfcaucino.workers.dev/api/v1/"
ENDPOINTS=frozenset({
    "pizarra","pizarra/historico","dolar","riesgo-pais","clima","lluvias",
    "cbot/diferencial","cbot/historico","wasde","resumen","indicadores","alertas","status",
})
PORIZO=frozenset({"pizarra/historico","cbot/historico"})
CULTURAS=frozenset({"soja","maiz","trigo","sorgo","girasol"})
MIME=frozenset({"application/json","text/json"})

def plano_granos_ar(*,endpoint, dias=30):
    if endpoint not in ENDPOINTS:
        raise ErroColetor("endpoint granos.ar fora da lista")
    if type(dias)!=int or not 1<=dias<=365:
        raise ErroColetor("limite historico granos.ar invalido")
    if endpoint=="resumen":
        raise ErroColetor("resumen sem contrato JSON tipado")
    return BASE+endpoint+("?"+urlencode({"dias":dias}) if endpoint in PORIZO else "")

def parse_granos_ar(raw, *,endpoint):
    try:
        data=json.loads(raw)
    except (UnicodeError,ValueError) as exc:
        raise ErroColetor("JSON granos.ar invalido") from exc
    if not isinstance(data,dict) or not isinstance(data.get("meta"),dict):
        raise ErroColetor("envelope granos.ar incorreto")
    if data["meta"].get("fuente")!="granos.ar" or data.get("error"):
        raise ErroColetor("fonte declarada inesperada/erro remoto")
    conteudo=data.get("data")
    if conteudo is None or not isinstance(conteudo,(dict,list)):
        raise ErroColetor("data granos.ar nao tipado")
    rows=[]
    if endpoint=="pizarra" and isinstance(conteudo,dict):
        dt=conteudo.get("fecha")
        try:
            ref=date.fromisoformat(dt).isoformat()
        except (ValueError,TypeError) as exc:
            raise ErroColetor("pizarra sem data de referencia") from exc
        precos=conteudo.get("granos")
        if not isinstance(precos,dict):
            raise ErroColetor("pizarra sem granos")
        for cultura,itens in precos.items():
            if cultura not in CULTURAS or not isinstance(itens,dict):
                continue
            for indicador,unidade in (("ars_tn","ARS/t"),("usd_tn","USD/t")):
                v=itens.get(indicador)
                if v is None:
                    continue
                if type(v) not in (int,float) or not math.isfinite(v) or v<=0:
                    raise ErroColetor("preco granos.ar invalido")
                rows.append({
                    "identidade":f"{ref}|{cultura}|{indicador}",
                    "referencia":ref,"natureza":"INFORMADO",
                    "valor":v,"unidade":unidade,
                    "campos":{"produto":cultura,"indicador":indicador,
                      "valor":v,"unidade":unidade,"mercado":"pizarra_reportada",
                      "fonte":"granos.ar","validacao_primaria":False}
                })
        if not rows:
            raise ErroColetor("pizarra sem preco numerico")
    return rows

def coletar_granos_ar(*,endpoint,banco,raw_dir,executar=False,dias=30,
                        cliente=None,instante=None):
    if executar is not True:
        raise PermissionError("GRANOS_AR_NETWORK_OFF")
    url=plano_granos_ar(endpoint=endpoint,dias=dias)
    raw,mime=_get(url,cliente=cliente,max_bytes=750_000,tipos=MIME)
    rows=parse_granos_ar(raw,endpoint=endpoint)
    now=instante if instante is not None else datetime.now(timezone.utc)
    dataset="ARG_GRANOS_AR_"+endpoint.upper().replace("/","_").replace("-","_")
    estado="NORMALIZED" if rows else "RAW_RECEIVED"
    result=gravar_lote(banco=banco,diretorio_bruto=raw_dir,dataset_id=dataset,
        origem=url,raw=raw,tipo="application/json",coletado_em=now,
        registros=rows,estado=estado)
    result.update({"provider":"granos.ar","endpoint":endpoint,
      "tipo_fonte":"SECUNDARIA","publicavel":False,
      "validacao_primaria":False,"go_live":False})
    return result

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description="Coleta pública granos.ar, não é fonte primária")
    p.add_argument("--endpoint",required=True,choices=sorted(ENDPOINTS-{"resumen"}))
    p.add_argument("--dias",type=int,default=30)
    p.add_argument("--banco",default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir",default="data/nivon/raw")
    p.add_argument("--executar",action="store_true")
    x=p.parse_args(argv)
    print(json.dumps(coletar_granos_ar(endpoint=x.endpoint,dias=x.dias,executar=x.executar,
      banco=x.banco,raw_dir=x.raw_dir),ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
