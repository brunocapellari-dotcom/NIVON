"""Inspeção real do preço de DIESEL e S10 na ANP, Setembro/2026.

Apenas estatísticas agregadas por município; nunca imprime, armazena ou
versiona CNPJ, nome de posto, endereço nem linhas individuais.
"""
from __future__ import annotations
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from nivon.anp_diesel import resumo_diesel_municipal

URL=("https://www.gov.br/anp/pt-br/centrais-de-conteudo/"
     "dados-abertos/arquivos/shpc/dsan/2026/"
     "09-dados-abertos-precos-2026-09-diesel-gnv.csv/@@download/file")
LIMITE_BYTES=15_000_000


def executar():
    req=Request(URL,headers={
        "User-Agent":"NIVON/0.2 (uso estatistico dados abertos ANP)",
        "Accept":"text/csv,application/octet-stream,text/plain",
    })
    with urlopen(req,timeout=35) as resposta:
        url_final=resposta.geturl()
        parse=urlsplit(url_final)
        if resposta.status!=200 or parse.scheme!="https" or parse.hostname!="www.gov.br":
            raise ValueError("ANP: fonte HTTP ou domínio incompatível")
        raw=resposta.read(LIMITE_BYTES+1)
        if not raw or len(raw)>LIMITE_BYTES:
            raise ValueError("ANP: arquivo vazio ou acima do limite")
        if raw[:512].lstrip().lower().startswith((b"<html",b"<!doctype html")):
            raise ValueError("ANP: HTML/WAF não é CSV")
    resumo=resumo_diesel_municipal(raw, mes_esperado="2026-09")
    mt=[x for x in resumo["series"] if x["uf"]=="MT"]
    por_produto={}
    for tipo in ("DIESEL","DIESEL S10"):
        linhas=[x for x in mt if x["produto"]==tipo]
        por_produto[tipo]={
            "municipios_com_amostra":len(set(x["municipio"] for x in linhas)),
            "grupos_municipio_semana":len(linhas),
            "observacoes_de_preco":sum(x["postos_observacoes"] for x in linhas),
        }
    datas=sorted({x["semana_inicio_inferida"] for x in mt})
    ultimo=datas[-1] if datas else None
    ultimos=[
        x for x in mt
        if x["semana_inicio_inferida"]==ultimo and x["produto"]=="DIESEL S10"
    ]
    return {
        "fonte":"ANP_PRECOS_ABERTOS_POSTO_REVENDA",
        "url":url_final,
        "competencia_mes":resumo["competencia_mes"],
        "arquivo_sha256":resumo["arquivo_sha256"],
        "bytes":len(raw),
        "linhas_diesel_validas":resumo["totais"]["linhas_diesel_validas"],
        "grupos_municipio_semana":resumo["grupos_municipio_semana"],
        "mt":por_produto,
        "ultima_semana_inferida_mt":ultimo,
        "amostra_s10_ultima_semana_mt":[
            {"municipio":x["municipio"],"n":x["postos_observacoes"],
             "preco_medio_rs_l":x["preco_medio_revenda_rs_l"]}
            for x in sorted(ultimos,key=lambda y:-y["postos_observacoes"])[:12]
        ],
        "evidencia":"OBSERVADO_AMOSTRA_ANP",
        "aviso":"Sem paridade internacional; média simples por amostra, não ponderada por volume; calendário semanal inferido",
        "dados_individuais_persistidos":False,
    }


if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,indent=2))
