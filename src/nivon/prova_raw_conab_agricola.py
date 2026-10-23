"""Verificação OFFLINE de bytes de séries históricas CONAB (soja/milho).

Verifica integridade criptográfica dos bytes, formato OLE2 e associação a
um link da página oficial anteriormente capturada. NÃO prova a edição XLS,
a data em que o conteúdo ficou disponível, licença, ou valores da planilha.
Nenhuma requisição HTTP, escrita em disco ou ativação operacional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
import re

from .conab_catalogo import descobrir_planilhas, ErroCatalogoConab
from .conab_series import ARQUIVOS
from urllib.parse import urlsplit


class ErroProvaRawConab(ValueError):
    pass


_OLE2 = bytes.fromhex("d0cf11e0a1b11ae1")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _data(value: str, name: str) -> datetime:
    if not isinstance(value, str):
        raise ErroProvaRawConab(name + ": timestamp ISO com fuso requerido")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroProvaRawConab(name + ": timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroProvaRawConab(name + ": sem fuso")
    return dt.astimezone(timezone.utc)


def verificar_raw_conab(
    *, cultura: str, arquivo: str, pagina_html_raw: bytes,
    planilha_raw: bytes, url_documento: str,
    coletado_html_em: str, coletado_xls_em: str,
    sha256_xls_esperado: str,
) -> dict:
    """Retorna manifesto e metadados sem publicação/edição presumidas.

    Somente o par URL + HTML bruto capturado permite afirmar que o link
    apareceu naquela CAPTURA; não que era publicado na data de um backtest.
    SHA esperado deve vir do registro de aquisição externo, não desta rotina.
    """
    if cultura not in ("SOJA", "MILHO"):
        raise ErroProvaRawConab("cultura fora do piloto CONAB")
    if arquivo not in ARQUIVOS or ARQUIVOS[arquivo][0] != cultura:
        raise ErroProvaRawConab("planilha não pertence à cultura")
    if (not isinstance(pagina_html_raw, bytes) or
            not 0 < len(pagina_html_raw) <= 3_000_000):
        raise ErroProvaRawConab("HTML bruto ausente ou fora do limite")
    if (not isinstance(planilha_raw, bytes) or
            not 512 <= len(planilha_raw) <= 30_000_000):
        raise ErroProvaRawConab("planilha bruta ausente ou fora do limite")
    if not planilha_raw.startswith(_OLE2):
        raise ErroProvaRawConab("arquivo não possui cabeçalho XLS/OLE2 legado")
    if not isinstance(sha256_xls_esperado, str) or not _SHA.fullmatch(
            sha256_xls_esperado):
        raise ErroProvaRawConab("SHA do adquirente ausente ou malformado")
    digest = sha256(planilha_raw).hexdigest()
    if not compare_digest(digest, sha256_xls_esperado):
        raise ErroProvaRawConab("SHA dos bytes XLS diverge do registro de captura")
    capturado_html = _data(coletado_html_em, "coletado_html_em")
    capturado_xls = _data(coletado_xls_em, "coletado_xls_em")
    # Este limite é uma regra de consistência do PAR de capturas,
    # nunca certificação da publicação ou estabilidade entre requisições.
    if abs((capturado_xls - capturado_html).total_seconds()) > 600:
        raise ErroProvaRawConab("HTML e XLS coletados a mais de 10 minutos")
    if not isinstance(url_documento, str) or not url_documento:
        raise ErroProvaRawConab("URL XLS ausente")
    try:
        html = pagina_html_raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroProvaRawConab("HTML não é UTF-8; exige adaptador autorizado") from exc
    try:
        lista = descobrir_planilhas(html, cultura)
    except (ErroCatalogoConab, ValueError) as exc:
        raise ErroProvaRawConab("catálogo HTML oficial incompatível") from exc
    matches = [item for item in lista if item["arquivo"] == arquivo]
    if len(matches) != 1:
        raise ErroProvaRawConab("arquivo não foi identificado uma vez no HTML bruto")
    item = matches[0]
    # O portal oficial aponta para /view e o binário é entregue via
    # /@@download/file. Os dois endereços não são intercambiáveis.
    url_catalogo = item["url"]
    part = urlsplit(url_catalogo)
    if part.query or part.fragment:
        raise ErroProvaRawConab("catálogo com parâmetros de download ambíguos")
    if part.path.lower().endswith(".xls/view"):
        url_esperada = url_catalogo[:-len("/view")] + "/@@download/file"
    elif part.path.lower().endswith(".xls"):
        url_esperada = url_catalogo
    else:
        raise ErroProvaRawConab("link oficial não aponta para arquivo XLS conhecido")
    if url_documento != url_esperada:
        raise ErroProvaRawConab("URL XLS não corresponde ao link de download do catálogo")

    meta = {
        "fonte_id": "CONAB", "edicao_id": "DESCONHECIDA",
        "raw_sha256": digest,
        "publicado_em": None, "disponivel_em": None,
        "coletado_em": capturado_xls.isoformat(),
        "prova_disponibilidade_sha256": None,
        "disponibilidade_verificada": False,
    }
    return {
        "status": "CAPTURA_SHA_OLE2_LINK_SEM_VALIDACAO_XLS_OU_VINTAGE",
        "cultura": cultura, "arquivo": arquivo,
        "subdivisao_safra": ARQUIVOS[arquivo][1],
        "url_documento": url_documento,
        "url_link_catalogo": url_catalogo,
        "estrutura_xls_validada": False,
        "abas_xls_lidas": False,
        "pagina_publicacao": item["pagina_publicacao"],
        "html_raw_sha256": sha256(pagina_html_raw).hexdigest(),
        "xls_raw_sha256": digest,
        "tamanho_html_bytes": len(pagina_html_raw),
        "tamanho_xls_bytes": len(planilha_raw),
        "coletado_html_em": capturado_html.isoformat(),
        "coletado_xls_em": capturado_xls.isoformat(),
        "snapshot_meta": meta,
        "publicacao_original_comprovada": False,
        "vintage_asof_comprovada": False,
        "habilita_backtest": False,
        "habilita_treino": False,
        "habilita_publicacao": False,
    }
