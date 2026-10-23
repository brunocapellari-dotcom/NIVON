"""Public source connectors NIVON: PTAX and IBGE PAM -> existing RAW/SQLite staging.

No hardcoded credential, no arbitrary URL and no implicit schedule. A source
needs an explicit operation grant. Run with Workload Identity for Cloud upload.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .bcb_ptax import normalizar_ptax_odata
from .sidra_pam import planejar_pam_1612, normalizar_pam_1612
from .ptax_plano import planejar_consultas_ptax
from .coleta_web import FonteWeb, adquirir_fonte
from .ingestao_fontes_reais import gravar_lote

FONTES = frozenset({"BCB_PTAX", "IBGE_PAM"})
OPERACOES = frozenset({"COLETA", "ARMAZENAMENTO"})
MAX_PAM = 2000


class ErroConectorNuvem(ValueError):
    pass


def _json_fechado(payload: bytes):
    def hook(pares):
        out = {}
        for k, v in pares:
            if k in out:
                raise ErroConectorNuvem("chave JSON repetida")
            out[k] = v
        return out
    try:
        return json.loads(payload.decode("utf-8-sig"), object_pairs_hook=hook)
    except (UnicodeError, ValueError) as exc:
        raise ErroConectorNuvem("JSON oficial invalido") from exc


def preparar_consulta(fonte: str, **kwargs) -> dict:
    if fonte == "BCB_PTAX":
        p = planejar_consultas_ptax(
            moeda=kwargs.get("moeda", "USD"),
            inicio=kwargs["inicio"], fim=kwargs["fim"], dias_janela=20)
        if len(p) != 1:
            raise ErroConectorNuvem("PTAX somente janela de ate 20 dias por lote")
        return p[0]
    if fonte == "IBGE_PAM":
        return planejar_pam_1612(
            municipio_ibge=kwargs["municipio_ibge"], ano=kwargs["ano"],
            codigo_produto_c81=kwargs["codigo_produto_c81"],
            codigo_variavel=kwargs["codigo_variavel"])
    raise ErroConectorNuvem("fonte ainda sem adapter especifico homologado")


def coletar(*, fonte: str, plano: dict, banco: str | Path, raw_dir: str | Path,
            autorizacoes: frozenset[str] = frozenset(),
            executar: bool = False, abridor=None,
            instante: datetime | None = None) -> dict:
    """HTTP autorizado -> parser existente -> RAW e observacoes versionadas."""
    if fonte not in FONTES or plano.get("dataset_id") != fonte:
        raise ErroConectorNuvem("plano/dataset divergente")
    if executar is not True or not OPERACOES <= set(autorizacoes):
        raise PermissionError("coleta exige COLETA e ARMAZENAMENTO aprovados")
    if fonte == "BCB_PTAX":
        original = preparar_consulta(fonte, moeda=plano.get("moeda"),
                                    inicio=plano.get("inicio"), fim=plano.get("fim"))
    else:
        original = preparar_consulta(
            fonte, municipio_ibge=plano.get("municipio_ibge"),
            ano=plano.get("ano"), codigo_produto_c81=plano.get("categoria_c81"),
            codigo_variavel=plano.get("variavel"))
    if original != plano:
        raise ErroConectorNuvem("plano adulterado")
    url = plano["url"]
    from urllib.parse import urlsplit
    dominio = urlsplit(url).hostname
    fonte_web = FonteWeb(
        fonte_id=fonte, url=url, dominio_autorizado=dominio,
        formato="JSON", status_direitos="APROVADA",
        operacoes_permitidas=frozenset({"COLETA"}), limite_bytes=2_000_000)
    adquirido = adquirir_fonte(fonte_web, abridor=abridor, instante=instante)
    data_coleta = adquirido["capturado_em"]
    raw = adquirido["conteudo"]
    if fonte == "BCB_PTAX":
        norm = normalizar_ptax_odata(
            _json_fechado(raw), moeda=plano["moeda"],
            coletado_em=data_coleta, consulta_url=url)
        registros = []
        for x in norm["observacoes"]:
            identidade = "|".join((
                x["moeda"], x["referencia_data_hora_utc"],
                x["tipo_boletim"] or "SEM_TIPO"))
            ref = x["competencia"]
            registros.append({
                "identidade": identidade, "referencia": ref,
                "competencia": ref[:7], "publicacao": None,
                "natureza": "INFORMADO", "unidade": "BRL/moeda",
                "valor": x["cotacao_venda_brl_por_moeda"],
                "campos": {**x, "valor_canonico": x["cotacao_venda_brl_por_moeda"],
                           "classificacao": "COTACAO_OFICIAL_NAO_REALIZACAO_COMERCIAL"},
            })
    else:
        norm = normalizar_pam_1612(raw, plano=plano, coletado_em=data_coleta)
        registros = []
        for x in norm["observacoes"]:
            identidade = "|".join(map(str, (
                x["municipio_ibge"],x["ano_civil"],x["variavel_sidra"],
                x["produto_categoria_c81"])))
            referencia = f'{x["ano_civil"]}-01-01'
            registros.append({
                "identidade": identidade, "referencia": referencia,
                "competencia": str(x["ano_civil"]), "publicacao": None,
                "natureza": "INFORMADO", "unidade": x["unidade_original"],
                "valor": x["valor"],
                "campos": {**x, "referencia_ano_civil": x["ano_civil"],
                           "tipo": "PAM_HISTORICO_NAO_PREVISAO"},
            })
    if not registros:
        raise ErroConectorNuvem("fonte nao retornou linhas; nunca persistir zero artificial")
    info = gravar_lote(
        banco=banco, diretorio_bruto=raw_dir, dataset_id=fonte,
        origem=url, raw=raw, tipo="application/json",
        coletado_em=data_coleta, registros=registros, estado="NORMALIZED")
    return {
        "status": "COLETA_LOCAL_VERSIONADA", "dataset": fonte,
        "registros": len(registros), "novos": info["novas_observacoes"],
        "snapshot_id": info["snapshot_id"], "sha256": info["sha256"],
        "data_coleta": data_coleta, "persistencia_gcp": False,
    }


def coletar_selic_diaria(*, banco: str | Path, raw_dir: str | Path,
                        executar: bool = False,
                        autorizacoes: frozenset[str] = frozenset(),
                        abridor=None, instante: datetime | None = None) -> dict:
    """SGS/BCB 11: conecta fonte publica oficial ao MESMO ledger NIVON.

    Taxa diaria observada no SGS nao deve ser reclassificada como meta Selic
    anual. Sem publicacao oficial timestamp nao presumir data de publicacao.
    """
    from .bcb_sgs_selic import URL_PONTUAL, normalizar_selic_diaria
    if executar is not True or not OPERACOES <= set(autorizacoes):
        raise PermissionError("SGS requer COLETA e ARMAZENAMENTO")
    fonte=FonteWeb(
        fonte_id="BCB_SGS_TAXA_SELIC_DIARIA", url=URL_PONTUAL,
        dominio_autorizado="api.bcb.gov.br", formato="JSON",
        status_direitos="APROVADA",operacoes_permitidas=frozenset({"COLETA"}),
        limite_bytes=250_000)
    adquirido=adquirir_fonte(fonte,abridor=abridor,instante=instante)
    normalizado=normalizar_selic_diaria(adquirido["conteudo"],
                                        coletado_em=adquirido["capturado_em"])
    rows=[]
    for item in normalizado["observacoes"]:
        referencia=item["data_referencia"]
        rows.append({
            "identidade":f"BCB_SGS_11|{referencia}",
            "referencia":referencia,
            "competencia":item["competencia"],
            "publicacao":None,
            "natureza":"INFORMADO",
            "unidade":"PERCENTUAL_AO_DIA",
            "valor":item["valor_pct_ao_dia"],
            "campos":{"fonte":"BCB","serie":11,
                      "data_referencia":referencia,
                      "valor_pct_ao_dia":item["valor_pct_ao_dia"],
                      "referencia_oficial_de_publicacao":False,
                      "nao_equivale_a_selic_meta_anual":True,
                      "promovido_a_indicador":False}
        })
    if not rows:
        raise ErroConectorNuvem("BCB sem observacoes, nao gravar zeros artificiais")
    info=gravar_lote(
        banco=banco,diretorio_bruto=raw_dir,
        dataset_id="BCB_SGS_TAXA_SELIC_DIARIA",
        origem=URL_PONTUAL,raw=adquirido["conteudo"],
        tipo="application/json",coletado_em=adquirido["capturado_em"],
        registros=rows,estado="NORMALIZED")
    return {"status":"COLETA_LOCAL_VERSIONADA",
            "dataset":"BCB_SGS_TAXA_SELIC_DIARIA",
            "registros":len(rows),"novos":info["novas_observacoes"],
            "snapshot_id":info["snapshot_id"],
            "sha256":info["sha256"],
            "data_coleta":adquirido["capturado_em"],
            "persistencia_gcp":False,
            "publicacao_automatica":False}
