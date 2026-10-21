"""Linha canônica de divulgação de transportadora, sem médias municipais.

Cada linha preserva o estabelecimento e transportadora, além das condições
comerciais observadas. É uma renderização offline; não aprova a origem.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import unicodedata

CORREDORES = frozenset({
    ("SORRISO", "MT", "RONDONOPOLIS", "MT"),
    ("SORRISO", "MT", "DOM AQUINO", "MT"),
    ("SINOP", "MT", "MIRITITUBA", "PA"),
    ("SORRISO", "MT", "PARANAGUA", "PR"),
    ("SORRISO", "MT", "SANTOS", "SP"),
    ("SORRISO", "MT", "UBERABA", "MG"),
})


def _normal(valor: str) -> str:
    return unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode().upper().strip()


def _campo(item: dict, chave: str, *, tamanho: int = 150) -> str:
    valor = item.get(chave)
    if not isinstance(valor, str) or not valor.strip() or len(valor) > tamanho:
        raise ValueError("frete exige identificação comercial: " + chave)
    if any(ord(ch) < 32 or ch in "|\u2028\u2029" for ch in valor):
        raise ValueError("caractere inválido na identificação de frete: " + chave)
    return valor.strip()


def _decimal(valor: object, chave: str, *, casas: int) -> Decimal:
    if type(valor) not in (int, float, Decimal, str):
        raise ValueError("número de frete inválido: " + chave)
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as exc:
        raise ValueError("número de frete inválido: " + chave) from exc
    if not numero.is_finite() or numero <= 0 or numero > Decimal("100000000"):
        raise ValueError("número de frete fora do domínio: " + chave)
    if numero != numero.quantize(Decimal(1).scaleb(-casas)):
        raise ValueError("precisão comercial excessiva: " + chave)
    return numero


def _br(numero: Decimal, casas: int) -> str:
    return f"{numero:.{casas}f}".replace(".", ",")


def formatar_linha_frete(item: dict) -> str:
    """Retorna UMA linha auditável, ou falha sem texto parcial."""
    if not isinstance(item, dict) or item.get("tipo") != "FRETE_ANUNCIADO":
        raise ValueError("frete não é anúncio individual")
    nomes = {
        chave: _campo(item, chave)
        for chave in ("origem", "uf_origem", "destino", "uf_destino",
                      "ponto_embarque", "pickup_entity_id", "transportadora",
                      "produto", "equipamento", "regime_pf_pj", "condicao_pedagio")
    }
    rota = tuple(_normal(nomes[k]) for k in ("origem", "uf_origem", "destino", "uf_destino"))
    if rota not in CORREDORES:
        raise ValueError("corredor de frete fora do escopo")
    if nomes["regime_pf_pj"].upper() not in {"PF", "PJ"}:
        raise ValueError("regime PF/PJ inválido")
    valor = _decimal(item.get("valor_rs_t"), "valor_rs_t", casas=2)
    referencia = _campo(item, "referencia", tamanho=40)
    try:
        horario = datetime.fromisoformat(referencia.replace("Z", "+00:00"))
        if horario.tzinfo is None or horario.utcoffset() is None:
            raise ValueError("sem fuso")
    except ValueError as exc:
        raise ValueError("referência de frete sem fuso/horário") from exc

    linha = (
        "• " + rota[0] + "/" + rota[1] + " → " + rota[2] + "/" + rota[3] +
        " | embarque: " + nomes["ponto_embarque"] + " [" + nomes["pickup_entity_id"] + "]" +
        " | transportadora: " + nomes["transportadora"] +
        " | produto: " + nomes["produto"] +
        " | equipamento: " + nomes["equipamento"] +
        " | PF/PJ: " + nomes["regime_pf_pj"].upper() +
        " | pedágio: " + nomes["condicao_pedagio"] +
        " | frete anunciado: R$ " + _br(valor, 2) + "/t"
    )
    if item.get("local_descarga") is not None:
        linha += " | descarga: " + _campo(item, "local_descarga")
    volume = item.get("volume_t_dia")
    if volume is not None:
        qtde = _decimal(volume, "volume_t_dia", casas=3)
        classe = item.get("classificacao_volume")
        if classe not in ("OBSERVADO", "REFERENCIA", "ESTIMADO"):
            raise ValueError("volume sem classe de observação")
        if item.get("volume_realizado") is True and classe != "OBSERVADO":
            raise ValueError("volume de referência declarado realizado")
        linha += " | volume " + _br(qtde.normalize(), max(0, -qtde.normalize().as_tuple().exponent)) + \
                 " t/dia (volume " + classe + ")"
    elif item.get("volume_realizado") is True:
        raise ValueError("volume declarado realizado sem quantidade")
    return linha + " | ref. " + referencia


def linha_identificada(texto: str) -> bool:
    """Reconhece linha comercial NIVON sem depender de posição no boletim."""
    return (texto.lstrip().startswith("• ") and
            " | embarque: " in texto and " | transportadora: " in texto and
            " | frete anunciado: R$ " in texto)
