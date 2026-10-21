"""Prova OFFLINE de vínculo entre levantamento CONAB, página do anexo e XLSX.

Verifica bytes e referências de uma CAPTURA, não a versão publicada no passado.
Os artefatos brutos são fornecidos pelo adquirente; não há rede, storage,
parser de células, inferência de série agrícola ou habilitação de backtest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlsplit
from zipfile import BadZipFile, ZipFile
import re


class ErroDocumentoConab(ValueError):
    pass


ANEXO = "tabela-de-dados-producao-e-balanco-de-oferta-e-demanda-de-graos"
_RAIZ = "/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-graos/boletim-da-safra-de-graos/"
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self.urls.append(href)


def _instant(s, label):
    if not isinstance(s, str) or "T" not in s:
        raise ErroDocumentoConab(label + ": timestamp ISO com fuso requerido")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroDocumentoConab(label + ": inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroDocumentoConab(label + ": sem fuso")
    return d.astimezone(timezone.utc)


def _govbr(url, label):
    if not isinstance(url, str):
        raise ErroDocumentoConab(label + ": URL não textual")
    u = urlsplit(url)
    if (u.scheme != "https" or u.netloc != "www.gov.br"
            or not u.path.startswith(_RAIZ) or
            u.query or u.fragment or u.username or u.password):
        raise ErroDocumentoConab(label + ": URL não oficial ou alterada")
    return u


def _links(raw, origem):
    if not isinstance(raw, bytes) or not 10 <= len(raw) <= 3_000_000:
        raise ErroDocumentoConab("HTML ausente ou excessivo")
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroDocumentoConab("HTML sem codificação UTF-8") from exc
    doc = _Anchors()
    doc.feed(html)
    doc.close()
    return {urljoin(origem, href) for href in doc.urls}


def _estrutura_zip_xlsx(raw):
    if not isinstance(raw, bytes) or not 100 <= len(raw) <= 15_000_000:
        raise ErroDocumentoConab("XLSX ausente ou excessivo")
    if not raw.startswith(b"PK\x03\x04"):
        raise ErroDocumentoConab("XLSX não inicia com cabeçalho ZIP")
    try:
        with ZipFile(BytesIO(raw)) as book:
            info = book.infolist()
            if not 3 <= len(info) <= 3000:
                raise ErroDocumentoConab("número de entradas ZIP inesperado")
            names = [x.filename for x in info]
            if len(set(names)) != len(names):
                raise ErroDocumentoConab("entrada ZIP duplicada")
            required = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"}
            if not required.issubset(names):
                raise ErroDocumentoConab("estrutura mínima XLSX ausente")
            total = 0
            for entry in info:
                name = entry.filename
                parts = name.split("/")
                if (not name or name.startswith("/") or "\\" in name or
                    ":" in name or any(x in (".", "..", "") for x in parts if x != "") or
                    entry.flag_bits & 1 or
                    ((entry.external_attr >> 16) & 0o170000) == 0o120000):
                    raise ErroDocumentoConab("caminho inseguro, link ou ZIP criptografado")
                lower = name.lower()
                if (lower.endswith(".bin") or "externalLinks".lower() in lower or
                        lower.startswith("xl/activex/") or
                        lower.startswith("xl/embeddings/") or
                        lower.startswith("customui/")):
                    raise ErroDocumentoConab("XLSX contém recurso ativo, externo ou binário")
                if entry.file_size > 25_000_000:
                    raise ErroDocumentoConab("entrada ZIP acima do limite")
                total += entry.file_size
                if (total > 80_000_000 or
                        (entry.file_size > 1_000_000 and
                         entry.file_size > max(1, entry.compress_size) * 200)):
                    raise ErroDocumentoConab("possível descompressão excessiva")
            return len(info), total
    except (BadZipFile, OSError, EOFError) as exc:
        raise ErroDocumentoConab("ZIP XLSX corrompido") from exc


def conferir_anexo_xlsx_levantamento(
    *, safra: str, numero_levantamento: int,
    pagina_levantamento_url: str, pagina_anexo_url: str, arquivo_xlsx_url: str,
    html_levantamento_raw: bytes, html_anexo_raw: bytes, xlsx_raw: bytes,
    coletado_levantamento_em: str, coletado_anexo_em: str,
    coletado_xlsx_em: str, sha256_xlsx_esperado: str,
) -> dict:
    """Só aceita par levant./anexo canônico e três capturas simultâneas.

    O XLSX é ZIP-inspecionado, mas as células NÃO são lidas. Mesmo um RAW
    íntegro coletado hoje não autentica a disponibilidade histórica.
    """
    import re as _re
    m = _re.fullmatch(r"(20\d\d)/(\d\d)", safra) if isinstance(safra, str) else None
    if not m or (int(m[1])+1) % 100 != int(m[2]):
        raise ErroDocumentoConab("safra inválida")
    if type(numero_levantamento) is not int or not 1 <= numero_levantamento <= 12:
        raise ErroDocumentoConab("número de levantamento inválido")
    pai = _govbr(pagina_levantamento_url, "levantamento")
    anexo = _govbr(pagina_anexo_url, "anexo")
    arquivo = _govbr(arquivo_xlsx_url, "XLSX")
    parent_path = pai.path.rstrip("/")
    basename = parent_path.removeprefix(_RAIZ)
    y, yy = int(m[1]), int(m[2])
    if basename not in (
        f"{numero_levantamento}o-levantamento-safra-{y}-{yy:02d}",
        f"{numero_levantamento}o-levantamento-safra-{y}-{y+1}",
    ):
        raise ErroDocumentoConab("levantamento não corresponde à safra/edição")
    if anexo.path != parent_path + "/" + ANEXO + "/view":
        raise ErroDocumentoConab("anexo não corresponde ao levantamento")
    # Gov.br serve o XLSX diretamente no item de arquivo sem /view.
    if arquivo.path != anexo.path.removesuffix("/view"):
        raise ErroDocumentoConab("download XLSX não corresponde à página de anexo")
    urls_pai = _links(html_levantamento_raw, pagina_levantamento_url)
    if pagina_anexo_url not in urls_pai and arquivo_xlsx_url not in urls_pai:
        raise ErroDocumentoConab("anexo não encontrado no HTML do levantamento")
    urls_anexo = _links(html_anexo_raw, pagina_anexo_url)
    # Algumas páginas de visualização exibem apenas o nome; link para o
    # binário pode não existir no HTML. URL de arquivo vem da estrutura
    # canônica, não de uma suposição de que houve download.
    _ = urls_anexo
    timestamps = [
        _instant(coletado_levantamento_em, "coletado_levantamento_em"),
        _instant(coletado_anexo_em, "coletado_anexo_em"),
        _instant(coletado_xlsx_em, "coletado_xlsx_em"),
    ]
    if (max(timestamps) - min(timestamps)).total_seconds() > 600:
        raise ErroDocumentoConab("capturas separadas por mais de 10 minutos")
    if not isinstance(sha256_xlsx_esperado, str) or not _SHA.fullmatch(sha256_xlsx_esperado):
        raise ErroDocumentoConab("hash de aquisição obrigatório")
    digest = sha256(xlsx_raw).hexdigest() if isinstance(xlsx_raw, bytes) else ""
    if not compare_digest(digest, sha256_xlsx_esperado):
        raise ErroDocumentoConab("SHA do binário XLSX não corresponde à aquisição")
    entries, uncompressed = _estrutura_zip_xlsx(xlsx_raw)
    return {
        "estado": "ANEXO_XLSX_VINCULADO_A_CAPTURA_SEM_PROVA_HISTORICA",
        "safra": safra, "numero_levantamento": numero_levantamento,
        "pagina_levantamento_url": pagina_levantamento_url,
        "pagina_anexo_url": pagina_anexo_url,
        "arquivo_xlsx_url": arquivo_xlsx_url,
        "levantamento_html_sha256": sha256(html_levantamento_raw).hexdigest(),
        "anexo_html_sha256": sha256(html_anexo_raw).hexdigest(),
        "arquivo_raw_sha256": digest,
        "captura_primeira_utc": min(timestamps).isoformat(),
        "captura_ultima_utc": max(timestamps).isoformat(),
        "zip_entradas": entries, "zip_bytes_descomprimidos_declarados": uncompressed,
        "estrutura_xlsx_basica_verificada": True,
        "celulas_xlsx_lidas": False,
        "edicao_historica_autenticada": False,
        "disponibilidade_asof_comprovada": False,
        "habilita_treino": False, "habilita_backtest": False,
        "habilita_publicacao": False,
        "alerta": "A captura atual não prova os bytes publicados na edição histórica.",
    }
