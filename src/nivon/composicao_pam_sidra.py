"""Montagem PAM SIDRA 1612 com área colhida, produção e rendimento em unidade explícita.

Sem rede. Três arquivos RAW validados individualmente pelo adaptador SIDRA.
A montagem não prova publicação, edição original comum, completude territorial
nem licence; sob nenhuma hipótese liberar vintage point-in-time automaticamente.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
import unicodedata

from .agregacao_pam_ibge import _PRODUTOS, C81_PAM_POR_CULTURA, ErroAgregacaoIBGE
from .sidra_pam import planejar_pam_1612, normalizar_pam_1612, ErroSIDRAPAM

_VARIAVEIS={"AREA_COLHIDA_HA":"216","PRODUCAO_T":"214","RENDIMENTO_KG_HA":"112"}
# SIDRA 1612: dicionário C81 compartilhado com o agregador estadual.
# O módulo reexporta C81_PAM_POR_CULTURA por compatibilidade de contrato.

_UNIDADES={
    "AREA_COLHIDA_HA":{"HECTARES","HECTARE"},
    "PRODUCAO_T":{"TONELADAS","TONELADA"},
    "RENDIMENTO_KG_HA":{"QUILOGRAMASPORHECTARE","QUILOGRAMA POR HECTARE","KG/HA"},
}
_HASH=re.compile(r"[a-f0-9]{64}\Z")
_ZERO={"ZERO_ABSOLUTO","ZERO_ARREDONDADO"}
_INVALIDOS={"SUPRIMIDO_SIGILO","NAO_APLICAVEL","NAO_DISPONIVEL"}


class ErroComposicaoPAM(ValueError):
    pass


def _normal(v):
    if not isinstance(v,str):return ""
    s=unicodedata.normalize("NFKD",v).encode("ascii","ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9/]","",s.upper())


def _stamp(v):
    try:dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except (ValueError,AttributeError,TypeError) as exc:
        raise ErroComposicaoPAM("coleta com fuso obrigatório") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroComposicaoPAM("coleta sem fuso")
    return dt.astimezone(timezone.utc)


def _valor_exato(raw):
    if not isinstance(raw,str) or not re.fullmatch(r"\d+(?:[.,]\d+)?",raw):
        raise ErroComposicaoPAM("valor bruto deve ser numérico decimal não negativo")
    # Texto como 3.750 pode ser decimal ou separador de milhares.
    # Sem convenção oficial autenticada, bloquear risco de erro 1000x.
    if re.fullmatch(r"\\d{1,3}\\.\\d{3}",raw):
        raise ErroComposicaoPAM(
            "formatação numérica ambígua: ponto decimal ou milhar")
    try:val=Decimal(raw.replace(",","."))
    except InvalidOperation as exc:raise ErroComposicaoPAM("decimal inválido") from exc
    if not val.is_finite() or val>=Decimal("1e16") or len(val.as_tuple().digits)>35:
        raise ErroComposicaoPAM("número fora do domínio")
    return val


def montar_pam_municipal(
    *,raws:dict[str,bytes],coletas:dict[str,str],
    municipio_ibge:str,ano:int,cultura:str,codigo_c81:str,
    prova_categoria_url:str,
    resolucoes_oficiais:dict[str,str],
    prova_resolucoes_sha256:str,
) -> dict:
    """Produz um registro compatível com agregacao_pam_ibge.agregar_municipios_pam.

    O usuário do módulo fornece o código c81 e evidência de dicionário para
    a cultura, mas essa evidência ainda exige auditoria contra o IBGE.
    Não aceitar código c81 baseado apenas no nome comercial inferido.
    """
    if cultura not in _PRODUTOS:
        raise ErroComposicaoPAM("cultura fora da PAM temporária suportada")
    # A falha detectada em 20/10/2026: código 2702 (feijão) foi usado
    # indevidamente em fixture com rótulo de SOJA; a API validaria o
    # filtro e o pipeline atribuiria uma cultura falsa sem este bloqueio.
    if codigo_c81 != C81_PAM_POR_CULTURA[cultura]:
        raise ErroComposicaoPAM(
            "C81 incompatível com cultura: esperada categoria "+
            C81_PAM_POR_CULTURA[cultura])
    if cultura=="GERGELIM" and ano<2025:
        raise ErroComposicaoPAM("PAM gergelim não era publicado para esses anos")
    if not isinstance(prova_categoria_url,str) or not prova_categoria_url.startswith(
        "https://sidra.ibge.gov.br/"):
        raise ErroComposicaoPAM("categoria c81 exige referência oficial SIDRA")
    if not isinstance(prova_resolucoes_sha256,str) or not _HASH.fullmatch(prova_resolucoes_sha256):
        raise ErroComposicaoPAM("prova da precisão reportada obrigatória")
    if (not isinstance(raws,dict) or not isinstance(coletas,dict)
        or set(raws)!=set(_VARIAVEIS) or set(coletas)!=set(_VARIAVEIS)):
        raise ErroComposicaoPAM("três arquivos SIDRA e coletas distintas obrigatórias")
    if not isinstance(resolucoes_oficiais,dict) or set(resolucoes_oficiais)!=set(_VARIAVEIS):
        raise ErroComposicaoPAM("resoluções oficiais por variável obrigatórias")
    resolutions={}
    for k,v in resolucoes_oficiais.items():
        try:r=Decimal(str(v))
        except InvalidOperation as exc:raise ErroComposicaoPAM("resolução inválida") from exc
        if not r.is_finite() or r<=0 or r>1000000:raise ErroComposicaoPAM("resolução fora do domínio")
        resolutions[k]=str(r)
    timestamps=[];hashes={};obs={};result={}
    for key,codigo in _VARIAVEIS.items():
        plano=planejar_pam_1612(municipio_ibge=municipio_ibge,ano=ano,
            codigo_produto_c81=codigo_c81,codigo_variavel=codigo)
        time=_stamp(coletas[key])
        timestamps.append(time)
        raw=raws[key]
        normalized=normalizar_pam_1612(raw,plano=plano,coletado_em=coletas[key])
        if len(normalized["observacoes"])!=1:
            raise ErroComposicaoPAM("consulta precisa conter exatamente uma observação")
        item=normalized["observacoes"][0]
        if _normal(item["unidade_original"]) not in {_normal(z) for z in _UNIDADES[key]}:
            raise ErroComposicaoPAM("unidade declarada pelo SIDRA incompatível com a variável")
        status=item["estado_valor"]
        if status in _INVALIDOS:
            raise ErroComposicaoPAM("marcador de sigilo/ausência não equivale a zero")
        if status=="ZERO_ARREDONDADO":
            raise ErroComposicaoPAM("zero arredondado não equivale a zero físico exato")
        if status=="ZERO_ABSOLUTO":
            val=Decimal(0)
        elif status=="OBSERVADO_NUMERICO":
            row=json.loads(raw.decode("utf-8-sig"))[1]
            val=_valor_exato(row["V"])
        else:
            raise ErroComposicaoPAM("estado SIDRA desconhecido")
        result[key]=val
        hashes[key]=sha256(raw).hexdigest()
        obs[key]={"estado":status,"valor_decimal":str(val),"unidade":item["unidade_original"],
                  "raw_sha256":hashes[key],"consulta":plano["url"]}
    if (max(timestamps)-min(timestamps)).total_seconds()>600:
        raise ErroComposicaoPAM("consultas distantes mais que dez minutos; evitar cortes de edição")
    # Digest do pacote não equivale a ID da edição pública IBGE.
    digest=sha256("|".join(f"{x}:{hashes[x]}" for x in sorted(hashes)).encode()).hexdigest()
    record={
        "municipio_ibge":municipio_ibge,"ano":ano,"cultura":cultura,
        "codigo_categoria_c81":codigo_c81,
        "produto_ibge":_PRODUTOS[cultura],
        "area_colhida_ha":str(result["AREA_COLHIDA_HA"]),
        "quantidade_produzida_t":str(result["PRODUCAO_T"]),
        "rendimento_reportado_kg_ha":str(result["RENDIMENTO_KG_HA"]),
        "resolucao_area_ha":resolutions["AREA_COLHIDA_HA"],
        "resolucao_producao_t":resolutions["PRODUCAO_T"],
        "resolucao_rendimento_kg_ha":resolutions["RENDIMENTO_KG_HA"],
        "edicao_id":"PACOTE_SIDRA_"+digest[:24].upper(),
        "raw_sha256":digest,
    }
    return {"registro_agregavel":record,"observacoes":obs,
        "hash_pacote":digest,
        "coletado_primeiro_utc":min(timestamps).isoformat(),
        "coletado_ultimo_utc":max(timestamps).isoformat(),
        "prova_categoria_url":prova_categoria_url,
        "codigo_categoria_c81":codigo_c81,
        "mapping_c81":"SIDRA_1612_TEMPORARIAS_2026_10_20",
        "prova_resolucoes_sha256":prova_resolucoes_sha256,
        "status":"PACOTE_SIDRA_OFFLINE_SEM_EDICAO_OU_PUBLICACAO_COMPROVADA",
        "publicado_em":None,"disponivel_em":None,
        "vintage_asof_permitida":False,
        "homologado":False,
        "nota":"Pacote técnico não prova edição histórica comum. Não extrapolar produto, unidade ou município.",
    }
