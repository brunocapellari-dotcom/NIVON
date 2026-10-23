"""Registro encadeado e reconciliação offline de previsões NIVON.

SHA256 prova integridade relativa a uma âncora externa confiável; NÃO prova
que uma previsão existia no passado. Sem carimbo independente imutável,
dados autorizados e verificação de arquivo bruto, o resultado não é auditado
para publicação ou skill real.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Mapping, Sequence

from .calendario_sessoes_mercado import indexar_calendario_sessoes
from .qualidade_mercados import preparar_serie_precos
from .validacao_tendencias_mercado import CLASSES


class ErroRegistroPrevisao(ValueError):
    """Falha de identidade, vínculo, data ou integridade da previsão."""


VERSAO = "NIVON_FORECAST_V1"
GENESIS = "0" * 64
CAMPOS = frozenset({
    "previsao_id", "serie_id", "modelo_versao", "identidade_economica",
    "emitido_em", "registrado_em", "treinado_ate", "sessao_base",
    "sessao_alvo", "horizonte_sessoes", "preco_base",
    "base_edicao_sha256", "regra_rotulagem", "banda_relativa",
    "probabilidades", "evidencia_registro_id", "evidencia_registro_sha256",
})


def _texto(v: object, nome: str) -> str:
    if not isinstance(v, str) or not 1 <= len(v) <= 160 or v.strip() != v:
        raise ErroRegistroPrevisao(f"{nome}: identificador inválido")
    return v


def _hash(v: object, nome: str) -> str:
    if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise ErroRegistroPrevisao(f"{nome}: SHA256 inválido")
    return v


def _hora(v: object, nome: str) -> datetime:
    if not isinstance(v, str) or len(v) > 45:
        raise ErroRegistroPrevisao(f"{nome}: timestamp ausente")
    try:
        t = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ErroRegistroPrevisao(f"{nome}: timestamp inválido") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroRegistroPrevisao(f"{nome}: fuso obrigatório")
    return t.astimezone(timezone.utc)


def _data(v: object, nome: str) -> date:
    if not isinstance(v, str) or len(v) != 10:
        raise ErroRegistroPrevisao(f"{nome}: sessão AAAA-MM-DD obrigatória")
    try:
        d = date.fromisoformat(v)
    except ValueError as exc:
        raise ErroRegistroPrevisao(f"{nome}: sessão inválida") from exc
    if d.isoformat() != v:
        raise ErroRegistroPrevisao(f"{nome}: sessão não canônica")
    return d


def _decimal(v: object, nome: str, *, permite_zero: bool = False) -> Decimal:
    if type(v) is not str or len(v) > 80:
        raise ErroRegistroPrevisao(f"{nome}: decimal textual obrigatório")
    try:
        d = Decimal(v)
    except InvalidOperation as exc:
        raise ErroRegistroPrevisao(f"{nome}: decimal inválido") from exc
    if not d.is_finite() or len(d.as_tuple().digits) > 16 or (d < 0 if permite_zero else d <= 0):
        raise ErroRegistroPrevisao(f"{nome}: decimal fora dos limites")
    return d


def _canonico(conteudo: dict) -> bytes:
    return json.dumps(conteudo, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validar_previsao(p: object) -> None:
    if not isinstance(p, dict) or set(p) != CAMPOS:
        raise ErroRegistroPrevisao("campos obrigatórios/extras de previsão divergentes")
    for nome in ("previsao_id", "serie_id", "modelo_versao", "regra_rotulagem",
                 "evidencia_registro_id"):
        _texto(p[nome], nome)
    _hash(p["evidencia_registro_sha256"], "evidencia_registro_sha256")
    _hash(p["base_edicao_sha256"], "base_edicao_sha256")
    identidade = p["identidade_economica"]
    if not isinstance(identidade, list) or len(identidade) != 12:
        raise ErroRegistroPrevisao("identidade econômica canônica de 12 campos obrigatória")
    for i in identidade:
        if i is not None and (not isinstance(i, str) or not i.strip() or len(i) > 160):
            raise ErroRegistroPrevisao("identidade econômica inválida")
    if identidade[0] not in ("CME", "ICE", "FISICO"):
        raise ErroRegistroPrevisao("mercado inválido")
    # A identidade real é confrontada com o adaptador de preços ao reconciliar.
    sessao_base = _data(p["sessao_base"], "sessao_base")
    sessao_alvo = _data(p["sessao_alvo"], "sessao_alvo")
    emitido = _hora(p["emitido_em"], "emitido_em")
    registrado = _hora(p["registrado_em"], "registrado_em")
    treinado = _hora(p["treinado_ate"], "treinado_ate")
    if not (treinado <= emitido <= registrado and
            sessao_base < sessao_alvo and
            datetime.fromisoformat(p["registrado_em"]).date() < sessao_alvo):
        raise ErroRegistroPrevisao("previsão registrada extemporaneamente")
    if type(p["horizonte_sessoes"]) is not int or not 1 <= p["horizonte_sessoes"] <= 252:
        raise ErroRegistroPrevisao("horizonte_sessoes inválido")
    _decimal(p["preco_base"], "preco_base")
    banda = _decimal(p["banda_relativa"], "banda_relativa", permite_zero=True)
    if banda >= 1:
        raise ErroRegistroPrevisao("banda_relativa fora do intervalo")
    probs = p["probabilidades"]
    if not isinstance(probs, dict) or set(probs) != set(CLASSES):
        raise ErroRegistroPrevisao("três probabilidades obrigatórias")
    valores = [_decimal(probs[k], k, permite_zero=True) for k in CLASSES]
    if abs(sum(valores) - 1) > Decimal("0.000001"):
        raise ErroRegistroPrevisao("probabilidades não somam um")


def criar_registro_previsao(previsao: dict, *, anterior_sha256: str = GENESIS) -> dict:
    """Cria compromisso SHA determinístico, sem fingir assinatura ou timestamp confiável."""
    _validar_previsao(previsao)
    _hash(anterior_sha256, "anterior_sha256")
    corpo = {"versao": VERSAO, "anterior_sha256": anterior_sha256,
             "previsao": json.loads(_canonico(previsao))}
    digest = sha256(_canonico(corpo)).hexdigest()
    return {**corpo, "registro_sha256": digest, "publicavel": False}


def verificar_cadeia_previsoes(
    registros: Sequence[Mapping], *, cabeca_esperada_sha256: str,
) -> dict:
    """Valida a cadeia inteira contra digest ancorado fora dos próprios registros.

    A veracidade / imutabilidade dessa âncora NÃO é certificada por esta API.
    """
    _hash(cabeca_esperada_sha256, "cabeca_esperada_sha256")
    if not isinstance(registros, (list, tuple)) or not 1 <= len(registros) <= 10000:
        raise ErroRegistroPrevisao("cadeia vazia ou excessiva")
    anterior = GENESIS
    ids = set()
    instantes = []
    for item in registros:
        if not isinstance(item, Mapping) or set(item) != {
            "versao", "anterior_sha256", "previsao", "registro_sha256", "publicavel"
        } or item["versao"] != VERSAO or item["publicavel"] is not False:
            raise ErroRegistroPrevisao("estrutura de registro adulterada")
        p = item["previsao"]
        _validar_previsao(p)
        digest = _hash(item["registro_sha256"], "registro_sha256")
        if item["anterior_sha256"] != anterior:
            raise ErroRegistroPrevisao("cadeia quebrada ou fora de ordem")
        esperado = sha256(_canonico({
            "versao": VERSAO, "anterior_sha256": anterior, "previsao": p
        })).hexdigest()
        if digest != esperado:
            raise ErroRegistroPrevisao("registro adulterado: digest divergente")
        if p["previsao_id"] in ids:
            raise ErroRegistroPrevisao("previsao_id duplicado")
        ids.add(p["previsao_id"])
        instantes.append(_hora(p["registrado_em"], "registrado_em"))
        anterior = digest
    if any(a > b for a, b in zip(instantes, instantes[1:])):
        raise ErroRegistroPrevisao("cadeia temporal fora de ordem")
    if anterior != cabeca_esperada_sha256:
        raise ErroRegistroPrevisao("cabeça diferente da âncora externa fornecida")
    return {"status": "CADEIA_HASH_CONFERIDA_OFFLINE",
            "quantidade": len(registros), "cabeca_sha256": anterior,
            "ancora_externa_autenticada": False, "publicavel": False}


def _visiveis(registros: Sequence[Mapping], *, corte: str) -> list[Mapping]:
    """Filtra vintages futuros sem descartar silenciosamente timestamps inválidos."""
    instante = _hora(corte, "as_of")
    if not isinstance(registros, (list, tuple)) or len(registros) > 10000:
        raise ErroRegistroPrevisao("vintages inválidas ou excessivas")
    visiveis = []
    for row in registros:
        if not isinstance(row, Mapping):
            raise ErroRegistroPrevisao("cotação inválida")
        pub = _hora(row.get("publicacao_em"), "publicacao_em")
        coleta = _hora(row.get("coleta_em"), "coleta_em")
        if pub > coleta:
            raise ErroRegistroPrevisao("cronologia de publicação/coleta inválida")
        if pub <= instante and coleta <= instante:
            visiveis.append(row)
    if not visiveis:
        raise ErroRegistroPrevisao("sem vintage de cotação visível no corte")
    return visiveis


def reconciliar_previsao(
    registro: Mapping, *, cadeia: Sequence[Mapping], cabeca_esperada_sha256: str,
    precos_base: Sequence[Mapping], precos_alvo: Sequence[Mapping],
    calendario_sessoes: Mapping, as_of: str,
) -> dict:
    """Prepara um único registro de backtest sem look-ahead, sem publicá-lo.

    preços_base são selecionados AS-OF da emissão; revisões posteriores não
    mudam o valor base do forecast. Preços alvo são selecionados AS-OF da
    avaliação. Requer cadeia íntegra com âncora externa declarada.
    """
    prova = verificar_cadeia_previsoes(cadeia,
                                      cabeca_esperada_sha256=cabeca_esperada_sha256)
    if not isinstance(registro, Mapping) or not any(
        dict(x) == dict(registro) for x in cadeia
    ):
        raise ErroRegistroPrevisao("previsão não pertence integralmente à cadeia informada")
    p = registro["previsao"]
    corte = _hora(as_of, "as_of")
    emissao = _hora(p["emitido_em"], "emitido_em")
    registro_em = _hora(p["registrado_em"], "registrado_em")
    if corte <= registro_em:
        raise ErroRegistroPrevisao("avaliação antes do registro da previsão")
    base = preparar_serie_precos(
        _visiveis(precos_base, corte=p["emitido_em"]), as_of=p["emitido_em"])
    alvo = preparar_serie_precos(
        _visiveis(precos_alvo, corte=as_of), as_of=as_of)
    identidade = p["identidade_economica"]
    if base["identidade_economica"] != identidade or alvo["identidade_economica"] != identidade:
        raise ErroRegistroPrevisao("instrumento, praça ou especificação divergentes")
    b = [x for x in base["serie"] if x["periodo"] == p["sessao_base"]]
    a = [x for x in alvo["serie"] if x["periodo"] == p["sessao_alvo"]]
    if len(b) != 1 or len(a) != 1:
        raise ErroRegistroPrevisao("sessão base/alvo ausente ou ambígua")
    b, a = b[0], a[0]
    if b["edicao_sha256"] != p["base_edicao_sha256"] or (
        Decimal(b["valor_decimal"]) != Decimal(p["preco_base"])
    ):
        raise ErroRegistroPrevisao("preço-base ou edição divergente do registro emitido")
    if _hora(a["referencia_em"], "alvo_referencia_em") <= registro_em:
        raise ErroRegistroPrevisao("alvo já era conhecido ao registrar previsão")
    mercado = identidade[0]
    indice, prova_cal = indexar_calendario_sessoes(
        calendario_sessoes, mercado=mercado, as_of=as_of)
    if (p["sessao_base"] not in indice or p["sessao_alvo"] not in indice or
            indice[p["sessao_alvo"]] - indice[p["sessao_base"]] != p["horizonte_sessoes"]):
        raise ErroRegistroPrevisao("horizonte incompatível com calendário")
    banda = Decimal(p["banda_relativa"])
    variacao = (Decimal(a["valor_decimal"]) - Decimal(b["valor_decimal"])) / Decimal(b["valor_decimal"])
    classe = "ALTA" if variacao > banda else ("BAIXA" if variacao < -banda else "ESTABILIDADE")
    # O agregador de backtests não pode confiar em um apelido de série
    # informado manualmente. Usa a identidade econômica COMPLETA de 12 campos.
    fingerprint = sha256(_canonico({
        "identidade_economica": identidade,
    })).hexdigest()
    item = {
        "serie_id": "IDENTIDADE_SHA256:" + fingerprint,
        "modelo_versao": p["modelo_versao"],
        "regra_rotulagem": p["regra_rotulagem"],
        "horizonte_sessoes": p["horizonte_sessoes"],
        "banda_relativa": p["banda_relativa"],
        "emitido_em": p["emitido_em"], "treinado_ate": p["treinado_ate"],
        "base_referencia_em": b["referencia_em"],
        "base_disponivel_em": b["coleta_em"],
        "sessao_base": p["sessao_base"],
        "alvo_referencia_em": a["referencia_em"],
        "alvo_disponivel_em": a["coleta_em"],
        "sessao_alvo": p["sessao_alvo"],
        "valor_base": b["valor_decimal"], "valor_alvo": a["valor_decimal"],
        "classe_realizada": classe, "edicao_real_sha256": a["edicao_sha256"],
        "probabilidades": dict(p["probabilidades"]),
    }
    return {
        "status": "RECONCILIADO_OFFLINE_NAO_HOMOLOGADO",
        "previsao_id": p["previsao_id"],
        "serie_rotulo_declarado": p["serie_id"],
        "serie_fingerprint_sha256": fingerprint,
        "registro_sha256": registro["registro_sha256"],
        "evidencia_registro_sha256": p["evidencia_registro_sha256"],
        "cabeca_sha256": prova["cabeca_sha256"],
        "preco_base_edicao_sha256": b["edicao_sha256"],
        "preco_alvo_edicao_sha256": a["edicao_sha256"],
        "calendario_edicao_sha256": prova_cal["edicao_sha256"],
        "item_backtest": item,
        "ancora_externa_autenticada": False,
        "previsao_historica_independente_comprovada": False,
        "publicavel": False,
        "probabilidades_calibradas": None,
    }
