"""Coleta supervisionada de portos a partir das próprias páginas oficiais.

Adaptadores conservadores reaproveitados do AgroLogMT, sem Cloud Run/BigQuery.
Nenhum porto torna-se homologado apenas por este módulo.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit
from .coleta_web import FonteWeb, adquirir_fonte
from .portos import Programacao, PORTOS_BR, contar_escalas
from ._agrolog_portos_html import parse_official_lineup_html
from ._agrolog_portos_pdf import (
    extract_pdf_tables, parse_itaqui_tables, parse_paranagua_tables,
    discover_pdf_link_from_landing,
)


class ErroPorto(ValueError):
    pass


# A URL efetiva deve continuar idêntica à autorizada na aquisição HTTPS.
PORTO_HOSTS = {
    "SANTOS": {"www.portodesantos.com.br"},
    "SANTAREM": {"www.cdp.com.br"},
    "BARCARENA_VILA_DO_CONDE": {"www.cdp.com.br"},
    "PARANAGUA": {"www.portosdoparana.pr.gov.br", "portosdoparana.pr.gov.br"},
    "ITAQUI": {"www.portodoitaqui.com", "portodoitaqui.com"},
    "RIO_GRANDE": {"www.portosrs.com.br"},
    "SAO_FRANCISCO_DO_SUL": {"www.portosaofrancisco.com.br"},
    "SALVADOR": {"www.codeba.gov.br"},
    "ILHEUS": {"www.codeba.gov.br"},
    "TUBARAO": set(),  # sem endpoint público homologado: falha fechado
}

MODOS = {
    "SANTOS": "HTML_SANTOS_SCHEDULE",
    "SANTAREM": "HTML_CDP_BERTH_TABLE",
    "BARCARENA_VILA_DO_CONDE": "HTML_CDP_BERTH_TABLE",
    "PARANAGUA": "PDF_PARANAGUA",
    "ITAQUI": "PDF_ITAQUI",
}


@dataclass(frozen=True)
class ContratoPorto:
    porto: str
    fonte: FonteWeb
    modo: str
    data_referencia: date | None = None
    serie: str | None = None

    def validar(self):
        if self.porto not in PORTOS_BR or self.porto not in PORTO_HOSTS:
            raise ErroPorto("porto desconhecido")
        if self.modo != MODOS.get(self.porto):
            raise ErroPorto("parser não homologado para este porto")
        host = urlsplit(self.fonte.url).hostname
        if host not in PORTO_HOSTS[self.porto] or host != self.fonte.dominio_autorizado:
            raise ErroPorto("endereço não corresponde à autoridade portuária")
        if self.modo.startswith("PDF") and not isinstance(self.data_referencia, date):
            raise ErroPorto("PDF exige data de referência documental")
        if self.porto == "PARANAGUA" and self.serie not in {
            "EXPORT_OESTE", "EXPORT_LESTE", "IMPORT_SOLIDOS"
        }:
            raise ErroPorto("série Paranaguá não identificada")
        formato = "HTML" if self.modo.startswith("HTML") else "PDF"
        if self.fonte.formato != formato:
            raise ErroPorto("formato de fonte divergente")
        self.fonte.verificar()


def processar_documento_porto(contrato: ContratoPorto, documento: dict) -> dict:
    """Arquivo real ou fixture já adquirido; não converte programação em realizado."""
    contrato.validar()
    dados = documento.get("conteudo")
    if not isinstance(dados, bytes) or not dados:
        raise ErroPorto("documento ausente")
    if documento.get("url") != contrato.fonte.url:
        raise ErroPorto("proveniência não corresponde ao contrato")
    sha=documento.get("sha256")
    if not isinstance(sha,str) or not re.fullmatch(r"[a-f0-9]{64}",sha):
        raise ErroPorto("SHA-256 obrigatório e com 64 caracteres hexadecimais")
    if hashlib.sha256(dados).hexdigest()!=sha:
        raise ErroPorto("documento alterado após coleta: SHA-256 divergente")
    if documento.get("bytes") is not None and (
            type(documento["bytes"]) is not int or documento["bytes"]!=len(dados)):
        raise ErroPorto("tamanho declarado diverge dos bytes originais")
    if documento.get("fonte_id") is not None and documento["fonte_id"]!=contrato.fonte.fonte_id:
        raise ErroPorto("fonte_id divergente do contrato")
    capturado=documento.get("capturado_em")
    if not isinstance(capturado,str):
        raise ErroPorto("timestamp obrigatório")
    try:
        momento=datetime.fromisoformat(capturado.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroPorto("timestamp ISO inválido") from exc
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ErroPorto("timestamp sem timezone")
    mime=documento.get("mime")
    if mime is not None:
        permitidos=({"text/html","application/xhtml+xml"} if contrato.modo.startswith("HTML")
                    else {"application/pdf"})
        if mime not in permitidos:
            raise ErroPorto("MIME do documento divergente do parser")
    if contrato.modo.startswith("PDF") and not dados.startswith(b"%PDF-"):
        raise ErroPorto("assinatura PDF não corresponde ao contrato")
    if contrato.modo.startswith("HTML"):
        try:
            texto = dados.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ErroPorto("HTML não UTF-8; requer adaptação documentada") from exc
        registros = parse_official_lineup_html(texto, contrato.modo)
    else:
        tabelas = extract_pdf_tables(dados)  # pdfplumber instalado sob demanda
        if contrato.modo == "PDF_ITAQUI":
            registros = parse_itaqui_tables(tabelas, reference_date=contrato.data_referencia)
            # Itaqui publica ATRACADO/FUNDEADO/ESPERADO; registrar somente
            # programação para não alegar observação física por leitura de PDF.
            registros = [r for r in registros if r.get("status") == "ESPERADO"]
        else:
            registros = parse_paranagua_tables(
                tabelas, reference_date=contrato.data_referencia, series=contrato.serie
            )
    if not registros:
        raise ErroPorto("nenhuma programação compatível; layout requer revisão")
    saida = []
    for r in registros:
        if r.get("status") not in {"PROGRAMMED", "ESPERADO"}:
            raise ErroPorto("status não programado retornado pelo parser")
        volume = r.get("quantidade_t")
        if volume not in (None, ""):
            try:
                from .importadores import decimal_ptbr
                tonelada = (float(volume) if contrato.modo.startswith("PDF")
                            else decimal_ptbr(str(volume)))
            except (ValueError, TypeError) as exc:
                raise ErroPorto("quantidade não validada") from exc
        else:
            tonelada = None
        saida.append(Programacao(
            porto=contrato.porto, navio=r["navio"], duv=r.get("duv") or None,
            imo=r.get("imo") or None, produto=r.get("carga") or None,
            toneladas_programadas=tonelada, fonte=contrato.fonte.url,
            coletado_em=documento["capturado_em"], status="PROGRAMADO",
        ))
    return {
        "porto": contrato.porto, "registros": saida,
        "escalas": contar_escalas(saida),
        "documento_sha256": documento["sha256"],
        "fonte": contrato.fonte.url,
        "capturado_em": documento["capturado_em"],
        "status": "EXTRAIDO_AGUARDA_HOMOLOGACAO",
        "classificacao": "PROGRAMADO_NAO_REALIZADO",
    }


def coletar_porto(contrato: ContratoPorto, *, abridor=None,
                 instante: datetime | None = None) -> dict:
    """Realiza aquisição direta com host/MIME/limites e gate de direitos."""
    contrato.validar()
    doc = adquirir_fonte(contrato.fonte, abridor=abridor, instante=instante)
    return processar_documento_porto(contrato, doc)


def descobrir_pdf_portuario(*, contrato_pagina: FonteWeb,
                            porto: str, abridor=None) -> str:
    """Descobre um único PDF no índice oficial, sem baixar automaticamente outro host.

    Fontes com múltiplos PDFs devem ter uma página de série por documento.
    """
    if porto not in {"PARANAGUA", "ITAQUI"}:
        raise ErroPorto("descoberta de PDF não suportada neste porto")
    if contrato_pagina.formato != "HTML":
        raise ErroPorto("índice precisa ser HTML")
    host = urlsplit(contrato_pagina.url).hostname
    if host not in PORTO_HOSTS[porto]:
        raise ErroPorto("índice de autoridade incompatível")
    doc = adquirir_fonte(contrato_pagina, abridor=abridor)
    try:
        url = discover_pdf_link_from_landing(
            doc["conteudo"].decode("utf-8-sig", errors="strict"), contrato_pagina.url
        )
    except (ValueError, UnicodeError) as exc:
        raise ErroPorto("nenhum PDF único verificado na página") from exc
    if urlsplit(url).hostname not in PORTO_HOSTS[porto]:
        raise ErroPorto("PDF externo à autoridade")
    return url
