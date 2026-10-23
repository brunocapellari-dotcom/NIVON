"""Ponte offline RSS -> página original -> evidências externas assinadas.

Não executa HTTP nem promove licenças autodeclaradas. A confiança de
emissores é pinada previamente em SQLite pela operação administrativa.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import sqlite3
from html.parser import HTMLParser
from .editorial_evidencias_pipeline import conciliar_complementos
from .editorial_preflight import _instante, _url_chave
from .registry_emissores import emissores_confiaveis
from .rss_radar import ler_feed_xml

PAPEIS = {"PUBLICACAO_ORIGINAL": "REVISAO_EDITORIAL",
          "DIREITOS_PUBLICACAO": "DIREITOS_PUBLICACAO"}
CHAVES = frozenset({"tipo","emissor_id","id_evidencia","fonte_id",
    "url","publicado_em","coletado_em","capturado_em","sha256_feed",
    "sha256_pagina","licenca_id","operacoes","estado"})
ID = re.compile(r"^[A-Za-z0-9_.:-]{8,140}$")
MAX_HTML = 2000000


class ErroProveniencia(ValueError):
    pass


def conteudo_assinado(doc: dict) -> bytes:
    if not isinstance(doc, dict) or set(doc) != CHAVES:
        raise ErroProveniencia("schema do comprovante de origem inválido")
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dentro = False
        self.partes = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.dentro = dict(attrs).get("type", "").lower().strip() == "application/ld+json"
            self.partes = []

    def handle_data(self, data):
        if self.dentro:
            self.partes.append(data)
            if sum(len(v) for v in self.partes) > 200000:
                raise ErroProveniencia("JSON-LD excessivo")

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.dentro:
            if len(self.scripts) >= 20:
                raise ErroProveniencia("muitos JSON-LD")
            self.scripts.append("".join(self.partes))
            self.dentro = False


def data_original_pagina(html: bytes, url: str) -> str:
    """Somente JSON-LD Article/NewsArticle com URL e datePublished."""
    if not isinstance(html, bytes) or not 50 <= len(html) <= MAX_HTML:
        raise ErroProveniencia("snapshot HTML inválido")
    parser = _Scripts()
    try:
        parser.feed(html.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as exc:
        raise ErroProveniencia("HTML original inválido") from exc
    datas = set()
    for raw in parser.scripts:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        root = parsed if isinstance(parsed, list) else [parsed]
        for node in root:
            if not isinstance(node, dict):
                continue
            nodes = node.get("@graph")
            for item in nodes if isinstance(nodes, list) else [node]:
                if not isinstance(item, dict):
                    continue
                tipo = item.get("@type")
                tipos = [tipo] if isinstance(tipo, str) else tipo if isinstance(tipo, list) else []
                if not set(tipos).intersection({"NewsArticle","Article"}):
                    continue
                try:
                    url_item = _url_chave(item.get("url"))
                except ValueError:
                    continue
                if url_item != _url_chave(url):
                    continue
                if isinstance(item.get("datePublished"), str):
                    datas.add(_instante(item["datePublished"]).isoformat())
    if len(datas) != 1:
        raise ErroProveniencia("publicação original única não comprovada na página")
    return next(iter(datas))


def _validar_assinatura(item: dict, *, tipo: str, emissores: dict,
                        noticia: dict, page: dict, feed_sha: str,
                        coleta: str, captura: str) -> str:
    if not isinstance(item, dict) or set(item) != {"documento","assinatura"}:
        raise ErroProveniencia("envelope externo ausente")
    d = item["documento"]
    raw = conteudo_assinado(d)
    if len(raw) > 6000 or d.get("tipo") != tipo:
        raise ErroProveniencia("tipo de atestado inválido")
    fid = d.get("emissor_id")
    info = emissores.get(fid)
    if not isinstance(info, dict) or info.get("tipo") != PAPEIS[tipo]:
        raise PermissionError("emissor ou papel não confiável")
    chave = info.get("chave")
    if not isinstance(chave, bytes) or len(chave) < 32:
        raise PermissionError("chave do emissor ausente")
    sig = item["assinatura"]
    esperado = "sha256=" + hmac.new(chave, raw, hashlib.sha256).hexdigest()
    if not isinstance(sig, str) or not hmac.compare_digest(sig, esperado):
        raise PermissionError("assinatura de origem/direitos inválida")
    if (d["estado"] != "APROVADA"
            or not isinstance(d["id_evidencia"], str) or not ID.fullmatch(d["id_evidencia"])
            or d["fonte_id"] != noticia["fonte_id"]
            or _url_chave(d["url"]) != _url_chave(noticia["url"])
            or _instante(d["publicado_em"]) != _instante(noticia["publicado_em"])
            or _instante(d["coletado_em"]).isoformat() != coleta
            or _instante(d["capturado_em"]).isoformat() != captura
            or d["sha256_feed"] != feed_sha
            or d["sha256_pagina"] != page["sha256"]
            or d["licenca_id"] != noticia.get("evidencia_direitos_id")
            or not isinstance(d["operacoes"], list)
            or set(d["operacoes"]) != {
                "COLETA","ARMAZENAMENTO","RESUMO","PUBLICACAO_DERIVADA"}):
        raise PermissionError("atestado não coincide com dados brutos, escopo ou direitos")
    return d["id_evidencia"]


def conciliar_rss_com_pagina_e_atestados(
    con: sqlite3.Connection, *, candidatos: dict, feeds: list[dict],
    snapshots_xml: dict[str, bytes], paginas: dict[str, dict],
    atestados: dict[str, dict], eventos: dict[str, dict],
    chaves_emissores: dict,
) -> dict:
    """Reconciliador fail-closed e sem persistência, para notícias selecionadas.

    A página vem do coletor existente, pré-capturada. Uma licença declarada
    sem atestado de autoridade cadastrada NUNCA vira prova de direitos.
    """
    if (not isinstance(candidatos, dict)
            or candidatos.get("estado") != "CANDIDATOS_NAO_HOMOLOGADOS"
            or not isinstance(candidatos.get("noticias"), list)
            or not candidatos["noticias"]
            or not all(isinstance(v, dict) for v in (snapshots_xml,paginas,atestados,eventos))
            or not isinstance(feeds,list) or len(feeds) > 30):
        raise ErroProveniencia("lote de proveniência inválido")
    fids = {}
    for feed in feeds:
        fid = feed.get("fonte_id") if isinstance(feed,dict) else None
        if not isinstance(fid,str) or fid in fids:
            raise ErroProveniencia("ID de feed duplicado/inválido")
        raw = snapshots_xml.get(fid)
        if not isinstance(raw,bytes):
            raise ErroProveniencia("snapshot RSS ausente")
        parsed = ler_feed_xml(raw,fonte_id=fid,
            dominios_artigos=set(feed.get("dominios_artigos",[])),
            coletado_em=feed.get("coletado_em"),url_feed=feed.get("url_feed"))
        fids[fid] = (parsed["candidatos"],hashlib.sha256(raw).hexdigest(),feed)
    if con.in_transaction:
        raise ErroProveniencia("conciliador exige conexão fora de transação")
    con.execute("BEGIN IMMEDIATE")
    try:
        trusted = emissores_confiaveis(con,chaves_emissores)
        complementos = []
        vistos = set()
        for noticia in candidatos["noticias"]:
            if not isinstance(noticia,dict) or noticia.get("fonte_id") not in fids:
                raise ErroProveniencia("notícia sem origem capturada")
            registros,hash_rss,feed = fids[noticia["fonte_id"]]
            if noticia.get("sha256_origem") != hash_rss:
                raise PermissionError("RSS original alterado depois da curadoria")
            data = _instante(noticia["publicado_em"]).isoformat()
            coleta = _instante(feed["coletado_em"]).isoformat()
            correspondentes = [reg for reg in registros if
                reg["titulo"] == noticia.get("titulo")
                and _url_chave(reg["url"]) == _url_chave(noticia.get("url"))
                and _instante(reg["publicado_em_original"]).isoformat() == data]
            if len(correspondentes) != 1 or (
                    _instante(noticia["coletado_em"]).isoformat() != coleta):
                raise PermissionError("notícia editorial não coincide com RSS original")
            url = noticia["url"]
            if url in vistos:
                raise ErroProveniencia("URL duplicada na homologação")
            vistos.add(url)
            page = paginas.get(url)
            if (not isinstance(page,dict) or page.get("url") != url
                    or page.get("fonte_id") != noticia["fonte_id"]
                    or page.get("mime") not in ("text/html","application/xhtml+xml")
                    or not isinstance(page.get("conteudo"),bytes)
                    or page.get("sha256") != hashlib.sha256(page["conteudo"]).hexdigest()):
                raise ErroProveniencia("página original sem RAW válido do coletor")
            if data_original_pagina(page["conteudo"],url) != data:
                raise PermissionError("datePublished original diverge do RSS")
            captura = _instante(page["capturado_em"]).isoformat()
            if _instante(captura) < _instante(data):
                raise ErroProveniencia("página capturada antes de publicada")
            if noticia.get("direitos_publicacao") is not True:
                raise PermissionError("fonte sem direito declarado para uso derivado")
            docs = atestados.get(url)
            if not isinstance(docs,dict) or set(docs) != set(PAPEIS):
                raise PermissionError("duas atestações assinadas obrigatórias")
            provados = {}
            emissores_assinantes = set()
            for tipo in PAPEIS:
                provados[tipo] = _validar_assinatura(
                    docs[tipo],tipo=tipo,emissores=trusted,
                    noticia=noticia,page=page,feed_sha=hash_rss,
                    coleta=coleta,captura=captura)
                emissores_assinantes.add(docs[tipo]["documento"]["emissor_id"])
            if len(emissores_assinantes) != 2:
                raise PermissionError("atestações sem segregação de emissor")
            evento = eventos.get(url)
            if (not isinstance(evento,dict)
                    or set(evento) != {"evento_id","evidencia_evento_id"}
                    or not all(isinstance(v,str) and ID.fullmatch(v)
                               for v in evento.values())):
                raise ErroProveniencia("identidade editorial do evento não documentada")
            complementos.append({
                "evento_id":evento["evento_id"],
                "evidencia_evento_id":evento["evidencia_evento_id"],
                "evidencia_publicacao_original_id":provados["PUBLICACAO_ORIGINAL"],
            })
        conciliado = conciliar_complementos(candidatos,{
            "sha256_edicao":candidatos["sha256_edicao"],
            "noticias":complementos,
            "cotacoes":[{} for _ in candidatos.get("cotacoes",[])],
            "fretes":[{} for _ in candidatos.get("fretes",[])],
        })
        for registro in conciliado["noticias"]:
            registro["publicacao_original_verificada"] = True
        return {"estado":"ORIGEM_VERIFICADA_OFFLINE_SEM_PUBLICACAO",
                "sha256_edicao":candidatos["sha256_edicao"],
                "noticias":conciliado["noticias"],"cotacoes":conciliado["cotacoes"],
                "fretes":conciliado["fretes"],"envio_habilitado":False}
    finally:
        con.rollback()
