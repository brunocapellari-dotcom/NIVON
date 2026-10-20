"""Descoberta automatizável dos documentos oficiais de Paranaguá.

Fase 1: índice HTML -> edição/serie; fase 2: página de edição -> PDF único.
Nunca atribui homologação automaticamente, nem segue redirects/provedores não listados.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from ._agrolog_portos_pdf import discover_paranagua_landing_pages, discover_pdf_link_from_landing
from .coleta_web import FonteWeb, adquirir_fonte
from .portos_automaticos import ContratoPorto, processar_documento_porto, ErroPorto, PORTO_HOSTS


@dataclass(frozen=True)
class IndiceParanagua:
    fonte: FonteWeb
    serie: str

    def verificar(self):
        if self.serie not in {"EXPORT_OESTE","EXPORT_LESTE","IMPORT_SOLIDOS"}:
            raise ErroPorto("série não cadastrada")
        if self.fonte.formato != "HTML" or urlsplit(self.fonte.url).hostname not in PORTO_HOSTS["PARANAGUA"]:
            raise ErroPorto("índice incompatível com Paranaguá")
        self.fonte.verificar()


def descobrir_edicao_paranagua(indice: IndiceParanagua, *, abridor=None) -> dict:
    """Retorna URL da edição selecionada, sem afirmar que o PDF foi extraído."""
    indice.verificar()
    pagina=adquirir_fonte(indice.fonte,abridor=abridor)
    try:
        links=discover_paranagua_landing_pages(
           pagina["conteudo"].decode("utf-8-sig"),indice.fonte.url)
    except UnicodeError as exc:
        raise ErroPorto("índice sem charset UTF-8 homologado") from exc
    url=links.get(indice.serie)
    if not url:
        raise ErroPorto("série oficial não identificada no índice")
    if urlsplit(url).hostname not in PORTO_HOSTS["PARANAGUA"]:
        raise ErroPorto("série fora da autoridade portuária")
    return {
        "serie":indice.serie,"url_edicao":url,
        "fonte_indice":pagina["url"],
        "sha256_indice":pagina["sha256"],
        "status":"DESCOBERTO_PENDENTE_EXTRAÇÃO",
    }


def processar_edicao_paranagua(
    edicao: dict, *,
    referencia: date, direitos_confirmados: bool = False,
    abridor=None
) -> dict:
    """Baixa edição PDF diretamente ou localiza um único PDF na página de edição.

    É necessário verificar direitos separadamente da autorização da página índice.
    """
    if direitos_confirmados is not True:
        raise PermissionError("coleta de documento PDF exige autorização")
    if edicao.get("serie") not in {"EXPORT_OESTE","EXPORT_LESTE","IMPORT_SOLIDOS"}:
        raise ErroPorto("série inexistente")
    url=edicao.get("url_edicao")
    host=urlsplit(url or "").hostname
    if host not in PORTO_HOSTS["PARANAGUA"]:
        raise ErroPorto("URL de edição fora do domínio portuário")
    url_lower=urlsplit(url).path.lower()
    if not url_lower.endswith(".pdf"):
        pagina=FonteWeb(
            "PARANAGUA_EDICAO_HTML",url,host,"HTML",
            status_direitos="APROVADA",
            operacoes_permitidas=frozenset({"COLETA"}),
        )
        arquivo=adquirir_fonte(pagina,abridor=abridor)
        try:
            url=discover_pdf_link_from_landing(
                arquivo["conteudo"].decode("utf-8-sig"),url)
        except (ValueError,UnicodeError) as exc:
            raise ErroPorto("edição sem documento PDF único autorizado") from exc
        host=urlsplit(url).hostname
    fonte=FonteWeb(
        "PARANAGUA_PDF",url,host,"PDF",
        status_direitos="APROVADA",
        operacoes_permitidas=frozenset({"COLETA"}),
    )
    contrato=ContratoPorto("PARANAGUA",fonte,"PDF_PARANAGUA",
                           data_referencia=referencia,serie=edicao["serie"])
    contrato.validar()
    arquivo=adquirir_fonte(fonte,abridor=abridor)
    return processar_documento_porto(contrato,arquivo)
