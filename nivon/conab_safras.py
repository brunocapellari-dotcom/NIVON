"""NIVON — verificação de safras CONAB por produto, UF, safra e levantamento.

Consulta diretamente conab.safras (agrobr); NÃO usa fallback IBGE nem CEPEA.
Valida os dados antes de propor persistência. Não grava banco de produção.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re

PRODUTOS_PILOTO = frozenset({"soja", "milho", "algodao"})
UFS = frozenset({"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS",
                 "MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"})
PERIODO = re.compile(r"^\d{4}/\d{2}$")
METRICAS = ("area_plantada", "produtividade", "producao")
UNIDADES = {"area_plantada": "mil_ha", "produtividade": "kg/ha",
            "producao": "mil_t"}
FONTE = "Companhia Nacional de Abastecimento (CONAB)"


class DadosConabNaoHomologados(ValueError):
    pass


def parametros(produto: str, safra: str, uf: str, levantamento: int):
    if produto not in PRODUTOS_PILOTO:
        raise ValueError("Produto não aprovado para o piloto")
    if not isinstance(safra,str) or not PERIODO.fullmatch(safra):
        raise ValueError("Ano-safra precisa ser AAAA/AA")
    if int(safra[:4]) % 100 + 1 != int(safra[-2:]) and not (
        int(safra[:4]) % 100 == 99 and safra.endswith("/00")
    ):
        raise ValueError("Ano-safra inconsistente")
    if uf not in UFS:
        raise ValueError("UF inválida")
    if isinstance(levantamento,bool) or not isinstance(levantamento,int) or not 1 <= levantamento <= 12:
        raise ValueError("Levantamento da própria safra é obrigatório (1..12)")


def numero_nao_negativo(item, metrica):
    if item is None or item == "":
        return None
    if isinstance(item,bool):
        raise DadosConabNaoHomologados(f"{metrica}: booleano inválido")
    try:
        val = Decimal(str(item))
    except (InvalidOperation, TypeError):
        raise DadosConabNaoHomologados(f"{metrica}: decimal inválido")
    if not val.is_finite() or val < 0:
        raise DadosConabNaoHomologados(f"{metrica}: número negativo ou não finito")
    return format(val,"f")


def checar_meta(meta) -> dict:
    if meta is None:
        raise DadosConabNaoHomologados("Metadados de origem ausentes")
    source = str(getattr(meta,"source", "") or "").lower()
    if source != "conab":
        raise DadosConabNaoHomologados(f"Fonte primária inesperada: {source[:60]}")
    selected = str(getattr(meta, "selected_source", "") or "").lower()
    if selected and selected != "conab":
        raise DadosConabNaoHomologados("Fallback de fonte não aprovado")
    providers = getattr(meta,"data_sources",None)
    if providers:
        if isinstance(providers,dict):
            providers = list(providers)
        elif isinstance(providers,str):
            providers = [providers]
        if any(str(p).lower() not in ("conab","conab.gov.br") for p in providers):
            raise DadosConabNaoHomologados("Conjunto de origens inclui fonte diferente da CONAB")
    return {"fonte":"conab", "source_details": getattr(meta,"source_details",None),
            "schema_version":getattr(meta,"schema_version",None)}


def validar_linhas(linhas: list[dict], produto: str, safra: str, uf: str,
                  levantamento: int, *, coletado_em:datetime | None = None):
    parametros(produto,safra,uf,levantamento)
    if not isinstance(linhas,list) or not linhas:
        raise DadosConabNaoHomologados("Nenhuma linha CONAB para o recorte solicitado")
    now=coletado_em or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("data_coleta precisa ter timezone")
    validas=[];rejeicoes=[]
    for i,row in enumerate(linhas):
        try:
            if not isinstance(row,dict):
                raise DadosConabNaoHomologados("Registro não estruturado")
            if str(row.get("fonte","")).lower().strip() != "conab":
                raise DadosConabNaoHomologados("Fonte do registro não é CONAB")
            if str(row.get("produto","")).lower().strip() != produto or row.get("uf")!=uf:
                raise DadosConabNaoHomologados("Produto ou UF divergente")
            if row.get("safra") != safra:
                raise DadosConabNaoHomologados("Safra divergente")
            if row.get("levantamento") is None or int(row["levantamento"]) != levantamento:
                raise DadosConabNaoHomologados("Levantamento divergente")
            refpub=row.get("data_publicacao")
            if refpub is None:
                raise DadosConabNaoHomologados("Data de publicação ausente; checar rota de série histórica")
            if isinstance(refpub,(date,datetime)):
                pub=refpub.date().isoformat() if isinstance(refpub,datetime) else refpub.isoformat()
            else:
                pub=date.fromisoformat(str(refpub)[:10]).isoformat()
            if pub > now.date().isoformat():
                raise DadosConabNaoHomologados("Publicação posterior à coleta")
            met={k:numero_nao_negativo(row.get(k),k) for k in METRICAS}
            if all(v is None for v in met.values()):
                raise DadosConabNaoHomologados("Métricas da safra ausentes")
            if row.get("area_colhida") is not None:
                raise DadosConabNaoHomologados("CONAB safra não publica área colhida distinta")
            validas.append({
                "fonte":"CONAB", "produto":produto,"uf":uf,"safra":safra,
                "levantamento":levantamento,"data_publicacao":pub,
                "data_referencia":None,"competencia":safra,
                "data_coleta":now.isoformat(),
                "area_plantada_mil_ha":met["area_plantada"],
                "produtividade_kg_ha":met["produtividade"],
                "producao_mil_t":met["producao"],
                "area_colhida_mil_ha":None,
                "natureza":"PROJETADO","qualidade":"CANDIDATO_VALIDADO_NAO_GRAVADO",
            })
        except (DadosConabNaoHomologados, ValueError, TypeError) as exc:
            rejeicoes.append({"indice":i,"motivo":str(exc)[:120]})
    return {"validas":validas,"rejeicoes":rejeicoes,"quantidade_validas":len(validas),
            "quantidade_rejeitadas":len(rejeicoes)}


async def diagnostico_safra(produto: str = "soja", safra: str = "2026/27",
                           uf: str = "MT", levantamento:int = 1)->dict:
    """Uma consulta oficial limitada, em memória; resposta de auditoria sem valores."""
    parametros(produto,safra,uf,levantamento)
    try:
        from agrobr import conab
    except ImportError as exc:
        raise RuntimeError("Instalar agrobr em runner isolado") from exc
    df,meta=await conab.safras(produto,safra=safra,uf=uf,
                              levantamento=levantamento,return_meta=True)
    metadados=checar_meta(meta)
    resultado=validar_linhas(df.to_dict(orient="records"),produto,safra,uf,levantamento)
    return {
        "status":"DADOS_VALIDOS_EM_MEMORIA" if resultado["quantidade_validas"] else "CONAB_SEM_LINHAS_VALIDAS",
        "fonte":"CONAB",
        "produto":produto,"uf":uf,"safra":safra,"levantamento":levantamento,
        "quantidade_validas":resultado["quantidade_validas"],
        "quantidade_rejeitadas":resultado["quantidade_rejeitadas"],
        "rejeicoes":resultado["rejeicoes"][:5],
        "source":"conab",
        "schema_version":str(metadados["schema_version"]),
        "armazenado_no_neon":False,
        "execucao":"CONSULTA_SEM_PERSISTENCIA",
    }
