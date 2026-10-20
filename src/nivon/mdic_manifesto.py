"""Catálogo de arquivos anuais MDIC por links observados na página oficial.

Não constrói endereços por suposição, não baixa CSV, não redistribui conteúdo.
Somente manifestos NCM e município fiscal SH4 desde 1997, por ano.
"""
from __future__ import annotations
import hashlib
import re
from collections import defaultdict
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit

INDEX="https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta"
_BASE="https://balanca.mdic.gov.br"
_LINKS={
    ("EXPORTACAO","NCM"):r"/balanca/bd/comexstat-bd/ncm/EXP_(\d{4})\.csv",
    ("IMPORTACAO","NCM"):r"/balanca/bd/comexstat-bd/ncm/IMP_(\d{4})\.csv",
    ("EXPORTACAO","MUNICIPIO_SH4"):r"/balanca/bd/comexstat-bd/mun/EXP_(\d{4})_MUN\.csv",
    ("IMPORTACAO","MUNICIPIO_SH4"):r"/balanca/bd/comexstat-bd/mun/IMP_(\d{4})_MUN\.csv",
}

class ErroManifestoMDIC(ValueError):
    pass

class _HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a":
            raw=dict(attrs).get("href")
            if raw:self.links.append(raw)

def catalogar_arquivos_mdic(html:bytes,*,ano_inicial:int,ano_final:int,
                            exigir_completo:bool=True)->dict:
    """Conjunto anual extraído do HTML observado; recusa ano ausente/inventado."""
    if (type(ano_inicial) is not int or type(ano_final) is not int
            or not 1997<=ano_inicial<=ano_final<=date.today().year
            or ano_final-ano_inicial>50):
        raise ErroManifestoMDIC("intervalo anual inválido")
    if type(exigir_completo) is not bool:
        raise ErroManifestoMDIC("exigir_completo deve ser booleano")
    if not isinstance(html,bytes) or not 0<len(html)<=800_000:
        raise ErroManifestoMDIC("HTML de índice ausente ou grande demais")
    try:
        text=html.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroManifestoMDIC("índice não UTF-8") from exc
    if "<html" not in text.lower() and "<a " not in text.lower():
        raise ErroManifestoMDIC("documento não parece HTML do índice")
    parser=_HTMLLinks()
    parser.feed(text)
    resultado={}
    duplicados=[]
    for href in parser.links:
        url=urljoin(INDEX,href)
        uri=urlsplit(url)
        if (uri.scheme!="https" or uri.hostname!="balanca.mdic.gov.br"
            or uri.username is not None or uri.password is not None
            or uri.port not in (None,443) or uri.query or uri.fragment):
            continue
        for (direcao,granularidade),padrao in _LINKS.items():
            encontrado=re.fullmatch(padrao,uri.path)
            if encontrado is None:
                continue
            ano=int(encontrado.group(1))
            if not ano_inicial<=ano<=ano_final:
                continue
            chave=(ano,direcao,granularidade)
            if chave in resultado:
                duplicados.append(chave)
            resultado[chave]={"ano":ano,"direcao":direcao,"granularidade":granularidade,
                              "url":url,"fonte":"MDIC_COMEX_STAT_DADOS_ABERTOS",
                              "estado":"LINK_OFICIAL_DESCOBERTO_SEM_DOWNLOAD"}
    if duplicados:raise ErroManifestoMDIC("dataset/ano duplicado no índice")
    ausentes=[]
    for ano in range(ano_inicial,ano_final+1):
        for direcao,granularidade in _LINKS:
            if (ano,direcao,granularidade) not in resultado:
                ausentes.append({"ano":ano,"direcao":direcao,
                                 "granularidade":granularidade})
    if exigir_completo and ausentes:
        raise ErroManifestoMDIC("índice sem cobertura anual integral; não inventar URL")
    return {"fonte":INDEX,"sha256_html":hashlib.sha256(html).hexdigest(),
            "ano_inicial":ano_inicial,"ano_final":ano_final,
            "arquivos":sorted(resultado.values(),key=lambda x:(x["ano"],x["granularidade"],x["direcao"])),
            "ausentes":ausentes,"quantidade":len(resultado),
            "recurso_coletado":False,"coleta_automatica_ativada":False,
            "limite":"SH4 municipio fiscal diferente da origem da carga; NCM não é municipio"}

def selecionar_incremental(manifesto:dict,*,sha_anteriores:dict|None=None)->list[dict]:
    """Aponta arquivos a baixar futuramente, sem executar downloads.

    Sem hash por arquivo, todos aparecem como candidatos; o índice HTML não
    revela se os bytes de cada CSV mudaram.
    """
    if not isinstance(manifesto,dict) or not isinstance(manifesto.get("arquivos"),list):
        raise ErroManifestoMDIC("manifesto inválido")
    if sha_anteriores is not None and not isinstance(sha_anteriores,dict):
        raise ErroManifestoMDIC("hashes anteriores inválidos")
    return [{**x,"delta":"VERSAO_ARQUIVO_A_VERIFICAR_POR_HASH_SHA256"}
            for x in manifesto["arquivos"]]
