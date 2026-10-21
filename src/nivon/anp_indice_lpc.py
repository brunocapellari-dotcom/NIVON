"""Descoberta OFFLINE dos resumos LPC semanais publicados pela ANP.

O índice é a fonte de links. Nunca inventa arquivo pela data; nome da planilha
e acesso podem mudar. Descoberta não constitui direito de coletar/redistribuir.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

URL_INDICE = ("https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
              "precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas")
_PATTERN = re.compile(r"^resumo_semanal_lpc_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.xlsx$",re.I)
_PREFIX = "/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc/"


class ErroIndiceLPC(ValueError):
    pass


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a":
            u=dict(attrs).get("href")
            if u:self.urls.append(u)


def descobrir_semanas_lpc(html: bytes, *, ano: int, url_indice: str = URL_INDICE) -> dict:
    if isinstance(ano,bool) or not isinstance(ano,int) or not 2004<=ano<=2100:
        raise ErroIndiceLPC("ano fora do histórico semanal")
    if url_indice != URL_INDICE:
        raise ErroIndiceLPC("índice de origem não autorizado")
    if not isinstance(html,bytes) or not 100<=len(html)<=4_000_000:
        raise ErroIndiceLPC("HTML de índice ANP ausente ou extenso")
    try:
        raw=html.decode("utf-8-sig",errors="strict")
    except UnicodeDecodeError as exc:
        raise ErroIndiceLPC("charset do índice inesperado") from exc
    if "<html" not in raw.lower() or "<a" not in raw.lower():
        raise ErroIndiceLPC("resposta não é índice ANP HTML")
    collector=_Links();collector.feed(raw)
    semanas={}
    for href in collector.urls:
        candidate=urlsplit(urljoin(url_indice,href))
        if (candidate.scheme!="https" or candidate.hostname!="www.gov.br"
            or candidate.username or candidate.password or candidate.port not in (None,443)
            or candidate.query or candidate.fragment):
            continue
        path=candidate.path.removesuffix("/view").removesuffix("/@@download/file")
        if not path.startswith(_PREFIX+str(ano)+"/"):
            continue
        basename=path.rsplit("/",1)[-1]
        m=_PATTERN.fullmatch(basename)
        if not m:
            continue
        inicio,fim=(date.fromisoformat(m.group(i)) for i in (1,2))
        if inicio.year!=ano or (fim-inicio).days!=6:
            continue
        # Arquivo pode ser anunciado em dois lugares da página; preservar 1 registro.
        chave=(inicio.isoformat(),fim.isoformat())
        exact="https://www.gov.br"+path
        if chave in semanas and semanas[chave]["url_pagina"]!=exact:
            raise ErroIndiceLPC("duas versões com a mesma semana; revisar manualmente")
        semanas[chave]={
            "semana_inicio":chave[0],"semana_fim":chave[1],
            "url_pagina":exact,
            "url_confirmada_no_indice":candidate.geturl(),
            "tipo":"RESUMO_SEMANAL_POR_MUNICIPIO_CANDIDATO",
            "aba_esperada":"MUNICIPIOS",
            "baixado":False,"schema_homologado":False,
        }
    return {
        "dataset_id":"ANP_PRECO_REVENDA_DIESEL",
        "indice_url":url_indice,
        "indice_sha256":hashlib.sha256(html).hexdigest(),
        "ano":ano,
        "semanas":sorted(semanas.values(),key=lambda x:x["semana_inicio"]),
        "total_semanas":len(semanas),
        "estado":"LINKS_OFICIAIS_DESCOBERTOS_SEM_DOWNLOAD",
        "alerta":"Ausência de semana na página não significa ausência de pesquisa; a fonte pode estar atrasada ou reorganizada.",
    }
