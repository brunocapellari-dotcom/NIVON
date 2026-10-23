"""IVO: radar de erratas oficiais IBGE/PAM, escopo restrito e fail-closed.

O índice guarda SOMENTE o anúncio público da errata: não inventa os
valores original/corrigido. Nenhum fetch ou treino; dado oficial observado
no site não equivale a documento arquivado e certificado no ledger.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .ivo_pam_semantica import conferir_semantica_pam_1612,ErroSemanticaPAM


class ErroRadarErrataPAM(ValueError):
    pass


def carregar_erratas_pam(caminho: str | Path | None=None) -> dict:
    if caminho is None:
        caminho=Path(__file__).resolve().parents[2]/"config"/"ivo_erratas_pam_identificadas.v1.json"
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def _url_ibge(value):
    if not isinstance(value,str) or len(value)>900:
        raise ErroRadarErrataPAM("URL IBGE inválida")
    try:
        parts=urlsplit(value)
        port=parts.port
    except ValueError as exc:
        raise ErroRadarErrataPAM("URL IBGE malformada") from exc
    if (parts.scheme!="https" or parts.hostname!="www.ibge.gov.br" or
            port is not None or parts.username is not None or
            parts.password is not None or not parts.path.startswith("/")):
        raise ErroRadarErrataPAM("fonte externa não é domínio IBGE autorizado")
    return value


def _dia(s,nome):
    if not isinstance(s,str):
        raise ErroRadarErrataPAM(f"{nome}: ISO date obrigatório")
    try:return date.fromisoformat(s)
    except ValueError as exc:raise ErroRadarErrataPAM(f"{nome}: data inválida") from exc


def _validar(catalogo):
    if (not isinstance(catalogo,dict) or catalogo.get("schema_version")!="1.0.0"
            or catalogo.get("dataset_id")!="IBGE_PAM"
            or catalogo.get("training_enabled") is not False
            or catalogo.get("do_not_infer_original_values") is not True
            or catalogo.get("release_document_bytes_archived") is not False
            or catalogo.get("numerical_revision_values_verified") is not False):
        raise ErroRadarErrataPAM("governança do catálogo de erratas divergente")
    _url_ibge(catalogo.get("source_url"))
    ref=_dia(catalogo.get("reference_date"),"reference_date")
    entries=catalogo.get("notices")
    if not isinstance(entries,list) or not 1<=len(entries)<=150:
        raise ErroRadarErrataPAM("lista de erratas ausente ou extensa")
    seen=set()
    for e in entries:
        if not isinstance(e,dict) or not isinstance(e.get("id"),str):
            raise ErroRadarErrataPAM("errata sem identidade")
        if not re.fullmatch(r"[A-Z0-9_]{6,110}",e["id"]) or e["id"] in seen:
            raise ErroRadarErrataPAM("errata duplicada ou identificador inválido")
        seen.add(e["id"])
        aviso=_dia(e.get("notice_date"),"notice_date")
        if aviso>ref: raise ErroRadarErrataPAM("errata posterior à data de levantamento")
        if (not isinstance(e.get("municipio_ibge"),str)
                or re.fullmatch(r"\d{7}",e["municipio_ibge"]) is None):
            raise ErroRadarErrataPAM("município IBGE sem 7 dígitos")
        uf=e.get("uf")
        if uf not in ("MT","SP"):  # ampliar somente com novas provas oficiais
            raise ErroRadarErrataPAM("UF sem identidade territorial validada no índice")
        if not isinstance(e.get("municipio_nome"),str) or not e["municipio_nome"].strip():
            raise ErroRadarErrataPAM("município sem nome")
        if e.get("original_bytes_known") is not False or e.get("corrected_bytes_known") is not False:
            raise ErroRadarErrataPAM("arquivo conhecido exige novo contrato de evidências, não bool alterado")
        if e.get("scope_validation_required") is not True:
            raise ErroRadarErrataPAM("validar escopo da publicação antes do modelo")
        if not isinstance(e.get("years"),list) or not e["years"]:
            raise ErroRadarErrataPAM("anos afetados ausentes")
        if any(type(y) is not int or not 1974<=y<=ref.year for y in e["years"]) or len(set(e["years"]))!=len(e["years"]):
            raise ErroRadarErrataPAM("anos PAM inválidos")
        if not isinstance(e.get("known_variable_codes"),list) or not e["known_variable_codes"]:
            raise ErroRadarErrataPAM("códigos de variável ausentes")
        for v in e["known_variable_codes"]:
            try:
                conferir_semantica_pam_1612(
                    variavel=v,categoria_c81=e.get("category_c81"),
                    unidade="Toneladas" if v=="214" else "Hectares")
            except ErroSemanticaPAM as exc:
                raise ErroRadarErrataPAM("variável/produto de errata não verificado") from exc
        if (not isinstance(e.get("affected_dimensions"),list)
                or "QUANTIDADE_PRODUZIDA" not in e["affected_dimensions"]):
            raise ErroRadarErrataPAM("dimensões corrigidas não descritas")
        _url_ibge(e.get("source_url"))
        _url_ibge(e.get("municipality_code_source"))
    return entries


def radar_erratas_pam(*, catalogo:dict, municipio_ibge:str,
                      ano:int, categoria_c81:str, variavel:str,
                      corte:date)->dict:
    notices=_validar(catalogo)
    if (not isinstance(municipio_ibge,str) or
            re.fullmatch(r"\d{7}",municipio_ibge) is None):
        raise ErroRadarErrataPAM("município IBGE inválido")
    if type(ano) is not int or not 1974<=ano<=2100:
        raise ErroRadarErrataPAM("ano civil inválido")
    if not isinstance(corte,date) or isinstance(corte,type) or hasattr(corte,"hour"):
        raise ErroRadarErrataPAM("corte deve ser data sem horário")
    if variavel!="214":
        raise ErroRadarErrataPAM("este índice só homologa escopo de quantidade produzida")
    try:
        conferir_semantica_pam_1612(variavel=variavel,
            categoria_c81=categoria_c81,unidade="Toneladas")
    except ErroSemanticaPAM as exc:
        raise ErroRadarErrataPAM("variável ou cultura desconhecida") from exc
    relev=[]
    for e in notices:
        if (e["municipio_ibge"],e["category_c81"])!=(municipio_ibge,categoria_c81):
            continue
        if ano not in e["years"] or variavel not in e["known_variable_codes"]:
            continue
        # No replay as-of, metadados de aviso futuro nao eram conhecidos.
        if _dia(e["notice_date"],"notice_date") > corte:
            continue
        relev.append({
            "id":e["id"],"aviso_em":e["notice_date"],
            "aviso_ja_publicado_no_corte":True,
            "fonte_url":e["source_url"],"tipo_correcao":e["correction_type"],
            "arquivo_original_arquivado":False,
            "arquivo_corrigido_arquivado":False,
            "delta_calculavel":False,
        })
    return {
        "estado":("ERRATA_PAM_PUBLICA_IDENTIFICADA_ARQUIVOS_PENDENTES" if relev
                  else "SEM_ERRATA_NO_CATALOGO_LIMITADO"),
        "municipio_ibge":municipio_ibge,"ano_civil":ano,
        "categoria_c81":categoria_c81,"variavel_sidra":variavel,
        "corte":corte.isoformat(),"erratas":relev,
        "cobertura_catalogo_completa":False,
        "reconstrucao_valor_anterior_possivel":False,
        "publicacao_na_fonte_reconhecida":bool(relev),
        "evidencia_digital_arquivada":False,
        "treinamento_autorizado":False,
        "aviso":"Catálogo parcial de anúncios oficiais, não coleção de versões numéricas nem licença.",
    }
