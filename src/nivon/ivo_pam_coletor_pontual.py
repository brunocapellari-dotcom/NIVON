"""IVO — transporte HTTP pontual e controlado para PAM/SIDRA/IBGE.

Completa a camada de rede que faltava ao normalizador sidra_pam; não cria
novo parser, não faz crawling, varredura, buscas por links, login, escrita,
treinamento ou autorização automática. Cada coleta é uma URL explícita,
um único GET, somente após liberação da fonte no catálogo e dos direitos.
A resposta permanece CANDIDATO (sem data de publicação atestada).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .sidra_pam import planejar_pam_1612, normalizar_pam_1612, ErroSIDRAPAM
from .ivo_pam_semantica import conferir_semantica_pam_1612, ErroSemanticaPAM


class ErroColetaPAM(ValueError):
    pass


class _SemRedirecionamento(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ErroColetaPAM("redirecionamento HTTP bloqueado; revisar URL exata")


def _utc(v):
    if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroColetaPAM("coleta exige datetime com timezone")
    return v.astimezone(timezone.utc)


def _url(v, *, tipo):
    if not isinstance(v, str) or not 15 <= len(v) <= 1200:
        raise ErroColetaPAM("URL ausente ou extensa")
    try:
        p=urlsplit(v)
        port=p.port
    except ValueError as exc:
        raise ErroColetaPAM("URL malformada") from exc
    if (p.scheme!="https" or p.username is not None or p.password is not None
            or port is not None or p.fragment or p.query or p.path.startswith("//")):
        raise ErroColetaPAM("endereço não é HTTPS canônico")
    if tipo=="SIDRA_JSON":
        if p.hostname!="apisidra.ibge.gov.br" or not p.path.startswith("/values/t/1612/"):
            raise ErroColetaPAM("URL não é SIDRA PAM 1612")
    elif tipo=="PDF_IBGE":
        if (p.hostname not in ("www.ibge.gov.br","biblioteca.ibge.gov.br")
                or not p.path.lower().endswith(".pdf")):
            raise ErroColetaPAM("PDF fora do portal/biblioteca IBGE")
    elif tipo=="ARQUIVO_LEGADO":
        if (p.hostname!="ftp.ibge.gov.br" or
                not p.path.startswith("/Producao_Agricola/Producao_Agricola_Municipal_")
                or not p.path.lower().endswith((".xls",".xlsx",".csv",".zip"))):
            raise ErroColetaPAM("arquivo legado fora do diretório IBGE/PAM")
    else:
        raise ErroColetaPAM("tipo de aquisição desconhecido")
    if re.search(r"%(?:2f|5c|00|2e|3a)",p.path,re.I) or ".." in p.path.split("/"):
        raise ErroColetaPAM("codificação/path traversal não autorizados")
    return v


def _fonte_liberada(catalogo, direitos):
    if not isinstance(catalogo,dict) or not isinstance(catalogo.get("datasets"),list):
        raise ErroColetaPAM("catálogo NIVON obrigatório")
    sources=[d for d in catalogo["datasets"] if isinstance(d,dict)
             and d.get("id")=="IBGE_PAM" and d.get("source_id")=="IBGE"]
    if len(sources)!=1:
        raise ErroColetaPAM("fonte IBGE_PAM ausente/duplicada")
    if sources[0].get("enabled") is not True or sources[0].get("collection_authorized") is not True:
        raise PermissionError("coleta real IBGE_PAM bloqueada por política no catálogo")
    if (not isinstance(direitos,dict)
            or direitos.get("operacoes") != frozenset({"COLETA","ARMAZENAMENTO"})
            or not isinstance(direitos.get("evidencia_ref"),str)
            or not re.fullmatch(r"[A-Za-z0-9._:/-]{6,160}",direitos["evidencia_ref"])):
        raise PermissionError("coleta exige referência explícita de direitos por operação")
    return direitos["evidencia_ref"]


def _fetch_once(url, limit, timeout):
    """Uma única requisição, sem cookies, proxies, redirects ou credenciais."""
    req=urllib.request.Request(url,headers={
        "User-Agent":"NIVON-Research-NonCommercial/0.1 (manual approved source)",
        "Accept":"application/json,application/pdf,application/octet-stream",
        "Accept-Encoding":"identity",
    },method="GET")
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SemRedirecionamento,
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(req, timeout=timeout) as response:
            status=getattr(response,"status",None)
            if status!=200:
                raise ErroColetaPAM(f"status HTTP {status}; arquivo não aceito")
            if response.headers.get("Content-Encoding","identity").lower()!="identity":
                raise ErroColetaPAM("codificação comprimida/inesperada bloqueada")
            data=response.read(limit+1)
            if len(data)>limit or not data:
                raise ErroColetaPAM("payload ausente ou excede limite")
            return data,response.headers.get("Content-Type","")
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,
            socket.timeout,OSError) as exc:
        raise ErroColetaPAM("falha HTTP/rede; não se deve inferir indisponibilidade do IBGE") from exc


def coletar_candidato_pam(*, catalogo:dict, direitos:dict, tipo:str,
        coletado_em:datetime, plano:dict|None=None, url_documento:str|None=None,
        transporte=None, timeout:int=12)->dict:
    """Coleta por chamada explícita e retorna bytes para quarentena.

    `transporte` é injeção de teste, NUNCA evidência de fetch real.
    Nenhuma escrita em `registro_snapshots`: só depois de guardar os bytes
    em armazenamento autorizado e obter metadados públicos atestados.
    """
    ref=_fonte_liberada(catalogo,direitos)
    instante=_utc(coletado_em)
    # No HTTP real a data não pode ser fornecida livremente como histórica.
    # Um teste com transporte injetado é fixture, não prova de coleta.
    if transporte is None and abs((datetime.now(timezone.utc)-instante).total_seconds())>120:
        raise ErroColetaPAM("instante de coleta real não coincide com o relógio atual")
    if type(timeout) is not int or not 1<=timeout<=20:
        raise ErroColetaPAM("timeout fora de limites")
    if transporte is not None and not callable(transporte):
        raise ErroColetaPAM("transporte não é callable")
    if tipo=="SIDRA_JSON":
        if not isinstance(plano,dict) or url_documento is not None:
            raise ErroColetaPAM("SIDRA exige exclusivamente plano canônico")
        try:
            esperado=planejar_pam_1612(
                municipio_ibge=plano.get("municipio_ibge"),ano=plano.get("ano"),
                codigo_produto_c81=plano.get("categoria_c81"),
                codigo_variavel=plano.get("variavel"))
            if plano!=esperado:
                raise ErroColetaPAM("plano SIDRA alterado")
            # Ativar somente pares de cultura/grandeza conhecidos no IVO.
            v=plano["variavel"]
            conferir_semantica_pam_1612(variavel=v,
                categoria_c81=plano["categoria_c81"],
                unidade="Toneladas" if v=="214" else "Hectares")
        except (ErroSIDRAPAM,ErroSemanticaPAM) as exc:
            raise ErroColetaPAM("códigos SIDRA sem validação") from exc
        url=_url(plano["url"],tipo=tipo)
        limit=2_000_000
    else:
        if plano is not None or url_documento is None:
            raise ErroColetaPAM("documento exige URL explícita e nenhum plano")
        url=_url(url_documento,tipo=tipo)
        limit=8_000_000
    output=(transporte or _fetch_once)(url,limit,timeout)
    if (not isinstance(output,tuple) or len(output)!=2
            or not isinstance(output[0],bytes)
            or not isinstance(output[1],str)):
        raise ErroColetaPAM("transporte devolveu contrato inválido")
    raw,mime=output
    if not raw or len(raw)>limit:
        raise ErroColetaPAM("payload vazio ou acima de limite")
    mimetype=mime.split(";",1)[0].strip().lower()
    if tipo=="SIDRA_JSON":
        if mimetype not in ("application/json","text/json","text/plain",
                             "application/octet-stream"):
            raise ErroColetaPAM("Content-Type incoerente com SIDRA JSON")
        try:
            normalized=normalizar_pam_1612(
                raw,plano=plano,coletado_em=instante.isoformat())
        except (ErroSIDRAPAM,UnicodeError,ValueError) as exc:
            raise ErroColetaPAM("JSON SIDRA fora do contrato, sem evidência candidata") from exc
        if len(normalized["observacoes"])!=1:
            raise ErroColetaPAM("SIDRA precisa retornar exatamente uma célula")
        marker=normalized["observacoes"][0]["estado_valor"]
    elif tipo=="PDF_IBGE":
        if mimetype not in ("application/pdf","application/octet-stream"):
            raise ErroColetaPAM("Content-Type não é PDF")
        if not raw.startswith(b"%PDF-"):
            raise ErroColetaPAM("PDF não reconhecido")
        marker="DOCUMENTO_NAO_VERIFICADO"
    else:
        if mimetype not in ("application/vnd.ms-excel",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "application/zip","application/octet-stream","text/csv"):
            raise ErroColetaPAM("arquivo legado com formato inesperado")
        marker="LEGADO_SEM_PARSER_HOMOLOGADO"
    return {
        "estado":"CAPTURA_PONTUAL_PAM_QUARENTENA_NAO_HOMOLOGADA",
        "url_exata":url,"tipo":tipo,
        "coletado_em":instante.isoformat(),
        "fonte":"IBGE","dataset_id":"IBGE_PAM",
        "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
        "content_type":mimetype,"estado_valor":marker,
        "conteudo_original":raw,
        "http_real_executado":transporte is None,
        "evidencia_direitos_declarada":ref,
        "autenticidade_documental_verificada":False,
        "publicacao_oficial_verificada":False,
        "treinamento_autorizado":False,
        "gravado_em_snapshot_ledger":False,
        "aviso":"Captura candidata não equivale a acervo preservado, publicação oficial ou liberação para treino.",
    }
