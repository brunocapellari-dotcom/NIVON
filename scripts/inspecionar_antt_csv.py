"""Coleta exploratória do CSV ferroviário ANTT: SOMENTE estatísticas de schema.

Fonte oficial SIADE, Creative Commons Atribuição, não é MDF-e rodoviário.
Não imprime linhas de estações individuais nem persiste arquivos brutos.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
from collections import Counter
from nivon.antt_ferrovia_csv import extrair_csv, resumo_safra_ferroviaria
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

URL = "https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/resource/c2854ec9-1cc5-4554-a1ae-96c5f37b5df6/download/producao_origem_destino_2026.csv"
CAMPOS = ("Mes_Ano", "Ferrovia", "Mercadoria_ANTT", "Estacao_Origem",
          "UF_Origem", "Estacao_Destino", "UF_Destino", "TU", "TKU")


def analisar_bytes(dados: bytes) -> dict:
    if not dados or len(dados) > 3_000_000:
        raise ValueError("CSV ausente ou excessivo")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            texto = dados.decode(encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("codificação desconhecida")
    primeira = texto.splitlines()[0]
    delim = ";" if primeira.count(";") > primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto, newline=""), delimiter=delim)
    if leitor.fieldnames is None or set(CAMPOS) != set(leitor.fieldnames):
        raise ValueError(f"campos inesperados: {leitor.fieldnames}")
    linhas=0
    mercadorias=Counter()
    meses=Counter()
    tu_exemplos=Counter()
    tku_exemplos=Counter()
    for row in leitor:
        linhas+=1
        if linhas>25000: raise ValueError("linhas excessivas")
        if None in row or any(row.get(k) is None for k in CAMPOS):
            raise ValueError(f"colunas desalinhadas na linha {linhas}")
        mercadorias[row["Mercadoria_ANTT"].strip()]+=1
        meses[row["Mes_Ano"].strip()]+=1
        if len(tu_exemplos)<6:tu_exemplos[row["TU"]]+=1
        if len(tku_exemplos)<6:tku_exemplos[row["TKU"]]+=1
    if not linhas:raise ValueError("CSV sem linhas")
    return {
        "fonte":"ANTT_SIADE_FERROVIA_2026_CSV",
        "modal":"FERROVIARIO_NAO_RODOVIARIO_MDFe",
        "licenca_catalogo":"Creative Commons Atribuição",
        "bytes":len(dados),"sha256":hashlib.sha256(dados).hexdigest(),
        "codificacao":encoding,"delimitador":delim,"colunas":leitor.fieldnames,
        "linhas":linhas,"meses":dict(sorted(meses.items())),
        "mercadorias_interesse":{k:v for k,v in mercadorias.items()
            if any(x in k.upper() for x in ("SOJA","MILHO","FERTILIZANTE"))},
        "exemplos_formatos_tu":list(tu_exemplos),
        "exemplos_formatos_tku":list(tku_exemplos),
        "observacao":"Estação NÃO é município; cifras ainda não validadas por parser canônico",
    }


def executar():
    req=Request(URL,headers={"User-Agent":"NIVON/0.2 (ANTT SIADE pesquisa esquema)"})
    with urlopen(req, timeout=30) as resp:
        host=urlsplit(resp.geturl())
        if resp.status!=200 or host.scheme!="https" or host.hostname!="dados.antt.gov.br":
            raise ValueError("redirecionamento/fonte não autorizado")
        raw=resp.read(3_000_001)
    resumo = analisar_bytes(raw)
    registros = extrair_csv(raw, fonte_id="ANTT_SIADE_CSV_2026")
    validado = resumo_safra_ferroviaria(registros)
    if len(registros) != resumo["linhas"]:
        raise ValueError("divergência no número de linhas de inspeção versus parser")
    if len(validado["por_mes"]) != len(resumo["meses"]):
        raise ValueError("divergência mensal no resumo dos dados")
    mt = validado["fluxos_mt_por_estacao"]
    por_produto = {}
    for linha in mt:
        produto = linha["mercadoria_fonte"]
        atual = por_produto.setdefault(produto, {"rotas_mensais": 0, "tu_t": 0.0})
        atual["rotas_mensais"] += 1
        atual["tu_t"] += linha["tu_t"]
    resumo["parser_numerico"] = {
        "estado": "EXTRACAO_FERROVIARIA_REAL_VALIDADA_POR_CONTRATO",
        "linhas_normalizadas": len(registros),
        "meses": [v["mes"] for v in validado["por_mes"]],
        "rotas_mensais_mt": len(mt),
        "origem_mt_por_mercadoria": {
            k: {"rotas_mensais": v["rotas_mensais"], "tu_t": round(v["tu_t"], 3)}
            for k, v in sorted(por_produto.items())
        },
        "limitacao": "SEM MAPA ESTACAO-PARA-MUNICIPIO; NAO E MDF-E RODOVIARIO",
    }
    return resumo


if __name__=="__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
