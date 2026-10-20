"""Extrator OFFLINE de tabela CDP/Santarém com múltiplas mercadorias por linha.

A página pode conter movimentos de 2022: coletar a página hoje NÃO transforma
linhas antigas em line-up atual. WDT ID não é DUV; um registro pode ter 2 produtos.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .lineup_nacional import instante


class ErroCDP(ValueError):
    pass


URL_SANTAREM = "https://www.cdp.com.br/programacao-de-navios-do-porto-de-santarem/"


def _nome(text: str) -> str:
    s=unicodedata.normalize("NFKD",text or "")
    return " ".join("".join(x for x in s if not unicodedata.combining(x)).upper().split())


def _celula(partes: list[str]) -> str:
    return "\n".join(" ".join(x.split()) for x in "".join(partes).split("\n") if x.strip())


class _Tabelas(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[]
        self.table=None
        self.row=None
        self.cell=None

    def handle_starttag(self,tag,attrs):
        if tag=="table":
            if self.table is not None: raise ErroCDP("tabela aninhada")
            self.table=[]
        elif tag=="tr" and self.table is not None:
            if self.row is not None: raise ErroCDP("linha aninhada")
            self.row=[]
        elif tag in ("th","td") and self.row is not None:
            if self.cell is not None: raise ErroCDP("célula aninhada")
            if any(k in ("rowspan","colspan") for k,_ in attrs):
                raise ErroCDP("colspan/rowspan exige adaptação individual")
            self.cell=[]
        elif tag=="br" and self.cell is not None:
            self.cell.append("\n")

    def handle_data(self,data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self,tag):
        if tag in ("th","td") and self.cell is not None:
            self.row.append(_celula(self.cell));self.cell=None
        elif tag=="tr" and self.row is not None:
            if self.row:self.table.append(self.row)
            self.row=None
        elif tag=="table" and self.table is not None:
            if self.table:self.tables.append(self.table)
            self.table=None


def _ton(valor: str) -> float:
    s=valor.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{3})*(?:,[0-9]{1,3})?",s):
        raise ErroCDP("quantidade em toneladas desconhecida")
    try:
        d=Decimal(s.replace(".","").replace(",","."))
    except InvalidOperation as exc:
        raise ErroCDP("quantidade numérica inconsistente") from exc
    if not d.is_finite() or not 0<d<=1000000:
        raise ErroCDP("tonelagem fora da faixa aceitável")
    return float(d)


def _data(s: str):
    if not s.strip():return None
    try:return datetime.strptime(s.strip(),"%d/%m/%Y").date()
    except ValueError as exc:raise ErroCDP("data CDP no formato dd/mm/yyyy inválida") from exc


def interpretar_santarem(html: str, *, coletado_em: str, fonte_url: str=URL_SANTAREM,
                        horizonte_dias: int=30) -> dict:
    parsed=urlsplit(fonte_url)
    if parsed.scheme!="https" or parsed.hostname!="www.cdp.com.br" or parsed.path!=urlsplit(URL_SANTAREM).path:
        raise ErroCDP("URL diferente do portal oficial de Santarém")
    if not isinstance(html,str) or not html.strip() or len(html)>8_000_000:
        raise ErroCDP("HTML ausente ou excessivo")
    agora=instante(coletado_em)
    if not 1<=horizonte_dias<=90:raise ErroCDP("janela inválida")
    p=_Tabelas();p.feed(html);p.close()
    registros=[];antigos=0;identificadores=set();tabelas=0
    for tab in p.tables:
        head=[_nome(x) for x in tab[0]]
        obrigatorios={"WDT_ID","NAVIO","CARGA","QUANTIDADE(T)"}
        if not obrigatorios.issubset(set(head)):continue
        if len(head)!=len(set(head)):raise ErroCDP("colunas CDP duplicadas")
        ix={col:head.index(col) for col in head}
        tabelas+=1
        for index,row in enumerate(tab[1:],start=2):
            if len(row)!=len(head):raise ErroCDP("tabela CDP com linha desalinhada")
            rid=row[ix["WDT_ID"]].strip()
            navio=row[ix["NAVIO"]].strip()
            if not rid.isdigit() or not navio:raise ErroCDP("navio ou WDT ID inválidos")
            # WDT é registro de tabela, NÃO identificador nacional da viagem.
            key=(tabelas,rid)
            if key in identificadores:raise ErroCDP("registro WDT repetido")
            identificadores.add(key)
            produtos=[x.strip() for x in row[ix["CARGA"]].split("\n") if x.strip()]
            valores=[x.strip() for x in row[ix["QUANTIDADE(T)"]].split("\n") if x.strip()]
            if not produtos or len(produtos)!=len(valores):
                raise ErroCDP("carga e toneladas com cardinalidade diferente")
            datas=[]
            for field in ("CHEGADA","ATRACACAO","DESATRACACAO"):
                # Acentos são normalizados no cabeçalho; datas são somente contexto.
                if field in ix:
                    value=_data(row[ix[field]])
                    if value:datas.append(value)
            if not datas:
                antigo=True
                referencia=None
            else:
                referencia=max(datas)
                antigo=(referencia<agora.date()-timedelta(days=horizonte_dias) or
                        referencia>agora.date()+timedelta(days=horizonte_dias))
            if antigo:antigos+=1
            for produto,volume in zip(produtos,valores):
                registros.append({
                    "porto_id":"SANTAREM","registro_wdt":rid,
                    "tabela_origem":tabelas,"navio":navio,
                    "produto_original":produto,"toneladas_na_pagina":_ton(volume),
                    "unidade":"T_DECLARADA_NA_TABELA", "duv":None,
                    "situacao":"PROGRAMACAO_INFORMATIVA_NAO_EVENTO_FISICO",
                    "referencia_data":referencia.isoformat() if referencia else None,
                    "coletado_em":agora.isoformat(),"publicado_em":None,
                    "linha_antiga_ou_sem_referencia":antigo,
                    "fonte_url":fonte_url,
                    "apto_briefing":False,
                })
    if not tabelas or not registros:
        raise ErroCDP("nenhuma tabela Santarém compatível e com registros")
    return {"porto_id":"SANTAREM","registros":registros,
            "linhas_origem":len(identificadores),
            "linhas_antigas_ou_sem_data":antigos,
            "status":"EXTRAIDO_OFFLINE_SEM_DUV_NEM_DATA_PUBLICACAO",
            "aviso":"WDT não equivale a DUV; produtos da mesma linha não contam como navios adicionais."}
