"""Controle point-in-time de preços para estudos offline do NIVON.

Não busca cotações nem licencia a sua utilização. Seleciona revisões comprovadas,
mantém identidade econômica e fornece dados ao motor descritivo já existente.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from .motor_tendencias import ErroTendencia, tendencia_observada


class ErroQualidadeMercado(ErroTendencia):
    """Dado de mercado inválido ou sem proveniência suficiente."""


CONTRATOS = {
    ("CME", "SOJA"): "USC/BU",
    ("CME", "MILHO"): "USC/BU",
    ("CME", "TRIGO"): "USC/BU",
    ("ICE", "ACUCAR"): "USC/LB",
    ("ICE", "ALGODAO"): "USC/LB",
    ("ICE", "CAFE"): "USC/LB",
}
UNIDADES_FISICAS = {"BRL/SC60KG", "BRL/T", "BRL/ARROBA", "BRL/L"}
TIPOS_FUTURO = {"FECHAMENTO", "AJUSTE"}
HASH_CHARS = set("0123456789abcdef")


def _texto(v: object, campo: str) -> str:
    if not isinstance(v, str) or not v or v.strip() != v or len(v) > 120:
        raise ErroQualidadeMercado(f"{campo}: identificador inválido")
    return v


def _data(v: object, campo: str) -> date:
    try:
        d = date.fromisoformat(_texto(v, campo))
    except ValueError as exc:
        raise ErroQualidadeMercado(f"{campo}: data inválida") from exc
    if d.isoformat() != v:
        raise ErroQualidadeMercado(f"{campo}: data não canônica")
    return d


def _momento(v: object, campo: str) -> datetime:
    if not isinstance(v, str) or len(v) > 40:
        raise ErroQualidadeMercado(f"{campo}: timestamp ausente")
    try:
        t = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ErroQualidadeMercado(f"{campo}: timestamp inválido") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroQualidadeMercado(f"{campo}: fuso explícito obrigatório")
    return t.astimezone(timezone.utc)


def _sha(v: object, campo: str) -> str:
    if not isinstance(v, str) or len(v) != 64 or not set(v) <= HASH_CHARS:
        raise ErroQualidadeMercado(f"{campo}: SHA256 inválido")
    return v


def _preco(v: object) -> Decimal:
    if type(v) not in (str, int, Decimal):
        raise ErroQualidadeMercado("preço exige decimal textual (não float/bool)")
    try:
        p = Decimal(str(v))
    except InvalidOperation as exc:
        raise ErroQualidadeMercado("preço decimal inválido") from exc
    if not p.is_finite() or p <= 0 or len(p.as_tuple().digits) > 16:
        raise ErroQualidadeMercado("preço fora dos limites ou não finito")
    return p


def _identidade(obs: Mapping) -> tuple:
    mercado = _texto(obs.get("mercado"), "mercado")
    produto = _texto(obs.get("produto"), "produto")
    tipo = _texto(obs.get("tipo"), "tipo")
    unidade = _texto(obs.get("unidade"), "unidade")
    if mercado in ("CME", "ICE"):
        if CONTRATOS.get((mercado, produto)) != unidade or tipo not in TIPOS_FUTURO:
            raise ErroQualidadeMercado("instrumento futuro/tipo/unidade sem contrato validado")
        contrato = _texto(obs.get("contrato"), "contrato")
        try:
            venc = date.fromisoformat(contrato + "-01")
        except ValueError as exc:
            raise ErroQualidadeMercado("vencimento futuro inválido") from exc
        if venc.strftime("%Y-%m") != contrato or not 2000 <= venc.year <= 2100:
            raise ErroQualidadeMercado("vencimento futuro não canônico")
        if obs.get("localidade_ibge") not in (None, ""):
            raise ErroQualidadeMercado("futuro não é preço físico municipal")
        return (mercado, produto, contrato, tipo, unidade, None)
    if mercado == "FISICO":
        ibge = _texto(obs.get("localidade_ibge"), "localidade_ibge")
        if len(ibge) != 7 or not ibge.isascii() or not ibge.isdecimal():
            raise ErroQualidadeMercado("código IBGE de praça inválido")
        if obs.get("contrato") not in (None, ""):
            raise ErroQualidadeMercado("preço físico não pode ter vencimento futuro")
        if tipo not in ("INDICADOR_FISICO", "OFERTA", "NEGOCIADO") or unidade not in UNIDADES_FISICAS:
            raise ErroQualidadeMercado("preço físico sem tipologia/unidade válida")
        return (mercado, produto, None, tipo, unidade, ibge)
    raise ErroQualidadeMercado("mercado não homologado por este contrato")


def _validar_obs(obs: Mapping, corte: datetime) -> dict:
    if not isinstance(obs, Mapping):
        raise ErroQualidadeMercado("observação inválida")
    identidade = _identidade(obs)
    periodo = _data(obs.get("data_referencia"), "data_referencia")
    competencia = _texto(obs.get("competencia"), "competencia")
    if competencia != periodo.strftime("%Y-%m"):
        raise ErroQualidadeMercado("competência não corresponde à data de referência")
    ref_original = obs.get("referencia_em")
    ref = _momento(ref_original, "referencia_em")
    pub = _momento(obs.get("publicacao_em"), "publicacao_em")
    coleta = _momento(obs.get("coleta_em"), "coleta_em")
    if not (ref <= pub <= coleta <= corte):
        raise ErroQualidadeMercado("publicação, coleta ou corte point-in-time inválidos")
    # Data da sessão no fuso declarado pelo provedor, não no UTC arbitrário.
    if datetime.fromisoformat(ref_original).date() != periodo:
        raise ErroQualidadeMercado("sessão diverge da data de referência local")
    url = urlsplit(_texto(obs.get("fonte_url"), "fonte_url"))
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.fragment or url.port not in (None, 443)):
        raise ErroQualidadeMercado("fonte URL insegura")
    fonte_id = _texto(obs.get("fonte_id"), "fonte_id")
    edicao = _sha(obs.get("edicao_sha256"), "edicao_sha256")
    anterior = obs.get("revisao_de_sha256")
    if anterior is not None:
        anterior = _sha(anterior, "revisao_de_sha256")
        if anterior == edicao:
            raise ErroQualidadeMercado("revisão não pode apontar para si mesma")
    return dict(obs, _identidade=identidade, _periodo=periodo, _ref=ref,
                _pub=pub, _coleta=coleta, _preco=_preco(obs.get("preco")),
                _fonte=fonte_id, _hash=edicao, _revisao=anterior)


def preparar_serie_precos(
    registros: Sequence[Mapping], *, as_of: str, max_registros: int = 10000,
) -> dict:
    """Resolve vintages sem esconder conflitos; retorna série comparável para tendência.

    O histórico é submetido por um coletor separado. Nunca declarar que o
    conteúdo é real, licenciado ou redistribuível a partir desse resultado.
    """
    corte = _momento(as_of, "as_of")
    if (not isinstance(registros, (tuple, list)) or not registros
            or type(max_registros) is not int or max_registros < 1
            or len(registros) > min(max_registros, 10000)):
        raise ErroQualidadeMercado("lote vazio, inválido ou excessivo")
    validadas = [_validar_obs(o, corte) for o in registros]
    identidades = {o["_identidade"] for o in validadas}
    fontes = {o["_fonte"] for o in validadas}
    if len(identidades) != 1 or len(fontes) != 1:
        raise ErroQualidadeMercado("mistura de praça, fonte, unidade, vencimento ou tipo")
    por_periodo = defaultdict(list)
    for row in validadas:
        por_periodo[row["_periodo"]].append(row)
    selecao = []
    descartadas = 0
    for periodo, grupo in sorted(por_periodo.items()):
        grupo.sort(key=lambda x: (x["_pub"], x["_coleta"], x["_hash"]))
        por_hash = {}
        for row in grupo:
            anterior = por_hash.get(row["_hash"])
            if anterior is not None:
                if (row["_preco"] != anterior["_preco"] or
                        row["_pub"] != anterior["_pub"] or
                        row["_revisao"] != anterior["_revisao"]):
                    raise ErroQualidadeMercado("mesmo SHA com dados divergentes")
                descartadas += 1
                continue
            if not por_hash:
                if row["_revisao"] is not None:
                    raise ErroQualidadeMercado("revisão sem edição anterior disponível")
            else:
                anterior = next(reversed(por_hash.values()))
                if (row["_revisao"] != anterior["_hash"] or
                        row["_pub"] <= anterior["_pub"] or
                        row["_coleta"] <= anterior["_coleta"]):
                    raise ErroQualidadeMercado("revisão não comprovada ou retroativa")
            por_hash[row["_hash"]] = row
        selecao.append(next(reversed(por_hash.values())))
    registros_normalizados = [
        {
            "periodo": o["_periodo"].isoformat(),
            "publicacao": o["_pub"].date().isoformat(),
            "coleta": o["_coleta"].date().isoformat(),
            "valor": float(o["_preco"]),
            "valor_decimal": str(o["_preco"]),
            "fonte_id": o["_fonte"],
            "edicao_sha256": o["_hash"],
            "mercado": o["_identidade"][0],
            "produto": o["_identidade"][1],
            "contrato": o["_identidade"][2],
            "tipo": o["_identidade"][3],
            "unidade": o["_identidade"][4],
            "localidade_ibge": o["_identidade"][5],
        }
        for o in selecao
    ]
    return {
        "status": "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO",
        "identidade_economica": list(next(iter(identidades))),
        "fonte_id": next(iter(fontes)),
        "periodos": len(selecao),
        "revisoes_resolvidas": len(validadas) - len(selecao) - descartadas,
        "duplicatas_identicas": descartadas,
        "serie": registros_normalizados,
        "publicavel": False,
        "probabilidades_calibradas": None,
    }


def tendencia_preco_auditada(
    registros: Sequence[Mapping], *, as_of: str, janela: int = 6,
    tolerancia_absoluta: float = 0.0, tolerancia_relativa: float = 0.0,
) -> dict:
    """Integra QC temporal à tendência observada; não produz previsão."""
    preparado = preparar_serie_precos(registros, as_of=as_of)
    serie = preparado["serie"]
    if any(abs(Decimal(x["valor_decimal"]) - Decimal(str(x["valor"]))) >
           Decimal("0.000000001") for x in serie):
        raise ErroQualidadeMercado("perda de precisão na ponte descritiva")
    resultado = tendencia_observada(
        serie, as_of=_momento(as_of, "as_of").date().isoformat(),
        fonte_id=preparado["fonte_id"],
        unidade=preparado["identidade_economica"][4],
        frequencia="SESSOES", janela=janela,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=tolerancia_relativa,
    )
    return {**resultado, "contrato_qualidade": preparado["status"],
            "identidade_economica": preparado["identidade_economica"],
            "revisoes_resolvidas": preparado["revisoes_resolvidas"],
            "duplicatas_identicas": preparado["duplicatas_identicas"],
            "publicavel": False}
