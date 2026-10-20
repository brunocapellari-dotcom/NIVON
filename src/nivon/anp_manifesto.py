"""Descoberta OFFLINE de planilhas ANP diesel/GNV do índice anual.

Os nomes e rotas mudaram em 2026; nunca construir URL do CSV com template.
Uma landing page não equivale a autorização ou URL de download homologada.
"""
from __future__ import annotations
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit

_INDEX="https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsan/"

class ErroManifestoANP(ValueError):
    pass

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.links=[];self._href=None;self._text=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a":
            self._href=dict(attrs).get("href");self._text=[]
    def handle_data(self,text):
        if self._href:self._text.append(text)
    def handle_endtag(self,tag):
        if tag.lower()=="a" and self._href:
            self.links.append((self._href," ".join(self._text)))
            self._href=None;self._text=[]

def manifestar_anp_diesel(html_paginas: list[bytes], *, ano: int,
                          meses_solicitados:frozenset[int])->dict:
    """Recebe 1+ páginas de listagem já obtidas por via autorizada.

    Apenas identifica arquivos publicados; não baixa CSV nem consulta rede.
    """
    if type(ano) is not int or not 2023<=ano<=2100:
        raise ErroManifestoANP("ano fora do contrato de arquivos mensais diesel")
    if (not isinstance(meses_solicitados,frozenset) or not meses_solicitados
        or any(type(m) is not int or not 1<=m<=12 for m in meses_solicitados)):
        raise ErroManifestoANP("meses explícitos entre 1 e 12 obrigatórios")
    if not isinstance(html_paginas,list) or not 1<=len(html_paginas)<=12:
        raise ErroManifestoANP("listagem anual inválida")
    links={}
    base=_INDEX+str(ano)
    provas=[]
    for pagina in html_paginas:
        if not isinstance(pagina,bytes) or not 100<=len(pagina)<=1_000_000:
            raise ErroManifestoANP("HTML ausente ou grande demais")
        try: text=pagina.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ErroManifestoANP("index ANP não está em UTF-8") from exc
        if "<a " not in text.lower():
            raise ErroManifestoANP("sem âncoras na listagem ANP")
        provas.append(hashlib.sha256(pagina).hexdigest())
        rd=_Links();rd.feed(text)
        for href,title in rd.links:
            uri=urlsplit(urljoin(base+"/",href))
            if (uri.scheme!="https" or uri.hostname!="www.gov.br"
                or uri.username or uri.password or uri.port not in (None,443)
                or uri.fragment or uri.query):
                continue
            prefix="/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsan/"+str(ano)+"/"
            if not uri.path.startswith(prefix):continue
            slug=uri.path[len(prefix):].strip("/")
            if not slug or "/" in slug and not slug.endswith(("/view","/@@download/file")):
                continue
            tokens=(slug+" "+title).lower()
            if "diesel" not in tokens or "gnv" not in tokens:continue
            month_match=re.match(r"^(0[1-9]|1[0-2])(?=[-. _])",slug)
            if month_match is None:continue
            mes=int(month_match.group(1))
            if mes not in meses_solicitados:continue
            key=(ano,mes)
            if key in links:
                if links[key]["url_pagina"]!=uri.geturl():
                    raise ErroManifestoANP("mês com múltiplos recursos: revisar vintage")
                continue
            links[key]={"competencia":f"{ano}-{mes:02d}",
                "url_pagina":uri.geturl(),
                "tipo_recurso":"PAGINA_OU_ITEM_ANP_SEM_DOWNLOAD_HOMOLOGADO",
                "natureza":"PRECO_REVENDA_AMOSTRAL",
                "evidencia":"LINK_OBSERVADO_NO_INDICE_ANP"}
    ausentes=[f"{ano}-{m:02d}" for m in sorted(meses_solicitados) if (ano,m) not in links]
    return {"dataset_id":"ANP_PRECO_REVENDA_DIESEL",
        "ano":ano,"fontes_paginas_sha256":provas,
        "arquivos": [links[k] for k in sorted(links)],
        "meses_sem_link":ausentes,
        "downloads_realizados":0,
        "status":"METADADOS_INDEX_VERIFICAR_DIREITOS_LAYOUT_E_VIGENCIA",
        "limite":"Arquivos mensais de diesel/GNV não são o histórico semanal agregado 2004+, nem diesel no atacado"}
