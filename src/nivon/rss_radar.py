"""Parser offline de RSS 2.0 e Atom para o Radar NIVON.

Sem HTTP, IA, classificação automática nem autorização para republicar.
Descarta notícias sem data ORIGINAL com hora e fuso; updated_at NÃO substitui published.
XML não confiável: proíbe DTD/entidades, limita volume de entrada e de resultados.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from .lineup_nacional import instante

ATOM = "{http://www.w3.org/2005/Atom}"
MAX_BYTES = 2_000_000
MAX_ITEMS = 200


class ErroFeed(ValueError):
    pass


class _Texto(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes=[]
    def handle_data(self,data):
        self.partes.append(data)


def _limpar(valor: str, limite: int) -> str:
    if not isinstance(valor,str):
        raise ErroFeed("campo de notícia não textual")
    p=_Texto()
    p.feed(valor[:limite*8])
    s=" ".join(" ".join(p.partes).split())
    return html.unescape(s)[:limite]


def _data(valor: str) -> str:
    if not isinstance(valor,str) or not valor.strip():
        raise ErroFeed("publicação original sem timestamp")
    try:
        if "T" in valor:
            d=instante(valor)
        else:
            d=parsedate_to_datetime(valor)
    except (TypeError,ValueError,IndexError) as exc:
        raise ErroFeed("timestamp original inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroFeed("timestamp original sem fuso")
    return d.astimezone(timezone.utc).isoformat()


def _url(url: str, dominios: frozenset[str]) -> str:
    if not isinstance(url,str) or len(url)>1900:
        raise ErroFeed("link de notícia inválido")
    parsed=urlsplit(url.strip())
    if (parsed.scheme!="https" or not parsed.hostname or
        parsed.username or parsed.password or parsed.port not in (None,443) or
        parsed.hostname.lower() not in dominios):
        raise ErroFeed("link não corresponde a domínio HTTPS autorizado")
    return url.strip()


def ler_feed_xml(payload: bytes, *, fonte_id: str, dominios_artigos: set[str],
                 coletado_em: str, url_feed: str) -> dict:
    """Retorna candidatos NÃO PUBLICÁVEIS e recusas auditáveis por item."""
    instante(coletado_em)
    if not isinstance(fonte_id,str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,70}",fonte_id):
        raise ErroFeed("fonte_id incompatível com catálogo")
    if not isinstance(payload,bytes) or not 20<=len(payload)<=MAX_BYTES:
        raise ErroFeed("feed XML vazio ou acima do limite")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)",payload,re.I):
        raise ErroFeed("XML com entidades ou DTD não permitido")
    dominios=frozenset(x.lower() for x in dominios_artigos)
    if not dominios or any(not re.fullmatch(r"[a-z0-9][a-z0-9.-]+",d) for d in dominios):
        raise ErroFeed("lista de hosts de notícia deve ser explícita")
    _url(url_feed, frozenset({urlsplit(url_feed).hostname or ""}))
    try:
        root=ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ErroFeed("XML de feed inválido") from exc
    if root.tag=="rss":
        nodes=root.findall("./channel/item")
        formato="RSS2"
    elif root.tag==ATOM+"feed":
        nodes=root.findall(ATOM+"entry")
        formato="ATOM"
    else:
        raise ErroFeed("formato RSS/Atom não reconhecido")
    if len(nodes)>MAX_ITEMS:
        raise ErroFeed("mais notícias do que limite de segurança")
    noticias=[]
    rejeicoes=[]
    for i,node in enumerate(nodes):
        try:
            if formato=="RSS2":
                titulo=node.findtext("title") or ""
                link=node.findtext("link") or ""
                original=node.findtext("pubDate") or ""
                guid=node.findtext("guid") or link
                resumo=node.findtext("description") or ""
            else:
                titulo=node.findtext(ATOM+"title") or ""
                original=node.findtext(ATOM+"published") or ""
                guid=node.findtext(ATOM+"id") or ""
                resumo=node.findtext(ATOM+"summary") or ""
                link=""
                for e in node.findall(ATOM+"link"):
                    if e.attrib.get("rel","alternate")=="alternate":
                        link=e.attrib.get("href","")
                        break
            publicado=_data(original)
            titulo=_limpar(titulo,240)
            if len(titulo)<5:
                raise ErroFeed("título curto ou ausente")
            link=_url(link,dominios)
            texto=_limpar(resumo,900)
            if len(texto)<10:
                raise ErroFeed("resumo insuficiente: requer curadoria antes de gerar briefing")
            if not isinstance(guid,str) or not guid.strip() or len(guid)>1000:
                raise ErroFeed("identificador GUID ausente")
            noticias.append({
                "fonte_id":fonte_id,"feed_url":url_feed,
                "guid":guid.strip(),"titulo":titulo,"url":link,"resumo_bruto":texto,
                "publicado_em_original":publicado,"coletado_em":instante(coletado_em).isoformat(),
                "estado":"EXTRAIDO_NAO_CLASSIFICADO_NAO_AUTORIZADO_PARA_PUBLICACAO",
            })
        except (ErroFeed,ValueError,TypeError) as exc:
            rejeicoes.append({"indice":i,"motivo":str(exc)})
    return {"fonte_id":fonte_id,"formato":formato,"candidatos":noticias,
            "rejeicoes":rejeicoes,
            "aviso":"Published é original. Updated, hora da coleta ou data-only não renova notícia antiga."}
