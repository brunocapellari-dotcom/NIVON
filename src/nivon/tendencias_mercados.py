"""Adaptações do Motor de Tendências para frete rodoviário, CBOT e mercado físico.

Somente análise offline. Não coleta dados, publica previsões ou presume direitos
de redistribuição. Dados de ofertas de frete não são contratos executados.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from statistics import median
from typing import Mapping, Sequence

from .motor_tendencias import (
    ErroTendencia, _data, _fonte, _metadados, tendencia_observada,
)


CBOT_PRODUTOS = frozenset({"SOJA", "MILHO", "TRIGO"})
CBOT_TIPOS = frozenset({"FECHAMENTO", "AJUSTE"})
FISICO_TIPOS = frozenset({"INDICADOR_FISICO", "OFERTA", "NEGOCIADO"})
FISICO_UNIDADES = frozenset({"BRL/SC60KG", "BRL/T", "BRL/ARROBA"})
PEDAGIO = frozenset({"INCLUSO", "ADICIONAL", "NAO_INFORMADO"})


def _identidade(valor: object, nome: str, *, tamanho: int = 100) -> str:
    if not isinstance(valor, str) or not valor.strip() or len(valor) > tamanho:
        raise ErroTendencia(f"{nome} inválido ou ausente")
    return valor.strip()


def _ibge(valor: object, nome: str) -> str:
    if not isinstance(valor, str) or len(valor) != 7 or not valor.isascii() or not valor.isdecimal():
        raise ErroTendencia(f"{nome}: código IBGE municipal de 7 dígitos obrigatório")
    return valor


def _dinheiro(valor: object, nome: str) -> Decimal:
    if type(valor) not in (str, int, float, Decimal):
        raise ErroTendencia(f"{nome}: decimal obrigatório")
    try:
        d = Decimal(str(valor))
    except InvalidOperation as exc:
        raise ErroTendencia(f"{nome}: valor inválido") from exc
    if not d.is_finite() or d <= 0 or len(d.as_tuple().digits) > 20:
        raise ErroTendencia(f"{nome}: preço finito positivo obrigatório")
    return d


def _validar_mercado(serie: Sequence[Mapping], *, as_of: str, fonte_id: str) -> None:
    corte = _data(as_of, "as_of")
    fonte_id = _fonte(fonte_id)
    if not isinstance(serie, (list, tuple)):
        raise ErroTendencia("série inválida")
    for obs in serie:
        _metadados(obs, asof=corte, fonte_id=fonte_id, nao_negativo=True)
        if _dinheiro(obs["valor"], "valor") <= 0:
            raise ErroTendencia("preço inválido")


def tendencia_cbot(
    serie: Sequence[Mapping], *, produto: str, contrato: str,
    tipo: str, fonte_id: str, as_of: str, janela: int = 6,
    tolerancia_absoluta: float = 0, tolerancia_relativa: float = 0,
) -> dict:
    """Série do MESMO contrato/vencimento, em centavos de dólar por bushel.

    Não monta série contínua nem rola contrato automaticamente; não compara
    preços de fechamento com preços de ajuste.
    """
    if produto not in CBOT_PRODUTOS:
        raise ErroTendencia("produto CBOT não suportado")
    if tipo not in CBOT_TIPOS:
        raise ErroTendencia("tipo fechamento/ajuste inválido")
    if not isinstance(contrato, str) or len(contrato) != 7 or contrato[4] != "-":
        raise ErroTendencia("contrato CBOT deve ser AAAA-MM")
    try:
        data_contrato = date.fromisoformat(contrato + "-01")
    except ValueError as exc:
        raise ErroTendencia("vencimento CBOT inválido") from exc
    if data_contrato.year < 2000 or data_contrato.year > 2100:
        raise ErroTendencia("contrato fora da janela permitida")
    _validar_mercado(serie, as_of=as_of, fonte_id=fonte_id)
    for item in serie:
        if any((
            item.get("mercado") != "CME",
            item.get("produto") != produto,
            item.get("contrato") != contrato,
            item.get("tipo") != tipo,
            item.get("unidade") != "USC/BU",
        )):
            raise ErroTendencia("CBOT: contrato, produto, unidade ou tipo misturados")
        if item.get("serie_continua") is True:
            raise ErroTendencia("CBOT: série contínua exige política de rolagem e ajustes auditados")
    result = tendencia_observada(
        serie, as_of=as_of, fonte_id=fonte_id, unidade="USC/BU",
        frequencia="SESSOES", janela=janela,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=tolerancia_relativa,
    )
    return {**result, "segmento": "CBOT", "produto": produto,
            "contrato": contrato, "tipo_cotacao": tipo,
            "comparabilidade": "MESMO_CONTRATO_SEM_ROLAGEM",
            "direitos_publicacao_verificados": False}


def tendencia_preco_fisico(
    serie: Sequence[Mapping], *, produto: str, localidade_ibge: str,
    tipo: str, unidade: str, fonte_id: str, as_of: str,
    janela: int = 6, tolerancia_absoluta: float = 0,
    tolerancia_relativa: float = 0,
) -> dict:
    """Preço físico por produto/praça/tipo de observação e unidade homogênea."""
    produto = _identidade(produto, "produto", tamanho=60)
    localidade_ibge = _ibge(localidade_ibge, "localidade_ibge")
    if tipo not in FISICO_TIPOS or unidade not in FISICO_UNIDADES:
        raise ErroTendencia("tipo ou unidade de preço físico inválidos")
    _validar_mercado(serie, as_of=as_of, fonte_id=fonte_id)
    for item in serie:
        if any((
            item.get("produto") != produto,
            item.get("localidade_ibge") != localidade_ibge,
            item.get("tipo") != tipo,
            item.get("unidade") != unidade,
        )):
            raise ErroTendencia("preço físico mistura produto, praça, tipo ou unidade")
    result = tendencia_observada(
        serie, as_of=as_of, fonte_id=fonte_id, unidade=unidade,
        frequencia="SESSOES", janela=janela,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=tolerancia_relativa,
    )
    return {**result, "segmento": "MERCADO_FISICO", "produto": produto,
            "localidade_ibge": localidade_ibge, "tipo_cotacao": tipo,
            "direitos_publicacao_verificados": False}


def tendencia_frete_anunciado(
    ofertas: Sequence[Mapping], *, origem_ibge: str, destino_ibge: str,
    produto: str, veiculo: str, pedagio: str, as_of: str,
    janela: int = 6, minimo_lotes_dia: int = 2,
    tolerancia_absoluta: float = 0, tolerancia_relativa: float = 0,
) -> dict:
    """Mediana diária por lotes únicos; sem misturar corredores ou tipos de oferta.

    O identificador de lote deve ser previamente resolvido pelo WhatsApp AI
    ou outro coletor autorizado. Mesmo lote e dia com preços divergentes bloqueia
    a análise; reenvios idênticos não pesam duas vezes.
    """
    origem_ibge = _ibge(origem_ibge, "origem_ibge")
    destino_ibge = _ibge(destino_ibge, "destino_ibge")
    if origem_ibge == destino_ibge:
        raise ErroTendencia("origem e destino iguais")
    produto = _identidade(produto, "produto", tamanho=60)
    veiculo = _identidade(veiculo, "veiculo", tamanho=60)
    if pedagio not in PEDAGIO:
        raise ErroTendencia("condição de pedágio precisa ser informada")
    if type(minimo_lotes_dia) is not int or not 2 <= minimo_lotes_dia <= 100:
        raise ErroTendencia("minimo_lotes_dia fora do intervalo")
    if not isinstance(ofertas, (tuple, list)) or len(ofertas) > 10000:
        raise ErroTendencia("ofertas inválidas ou excessivas")
    corte = _data(as_of, "as_of")
    dias: dict[str, dict[str, dict]] = defaultdict(dict)
    repetidos = 0
    for obs in ofertas:
        if not isinstance(obs, Mapping):
            raise ErroTendencia("oferta deve ser um objeto")
        fonte = _fonte(obs.get("fonte_id"))
        ref, _ = _metadados(obs, asof=corte, fonte_id=fonte, nao_negativo=True)
        if any((
            obs.get("origem_ibge") != origem_ibge,
            obs.get("destino_ibge") != destino_ibge,
            obs.get("produto") != produto,
            obs.get("veiculo") != veiculo,
            obs.get("pedagio") != pedagio,
            obs.get("natureza") != "OFERTA",
            obs.get("unidade") != "BRL/T",
        )):
            raise ErroTendencia("frete mistura corredor, produto, veículo, pedágio, natureza ou unidade")
        lote = _identidade(obs.get("lote_id"), "lote_id", tamanho=150)
        preco = _dinheiro(obs.get("preco_rs_t"), "preco_rs_t")
        # O núcleo genérico exige obs.valor. Ele precisa ser o mesmo preço sem arredondamento oculto.
        if Decimal(str(obs["valor"])) != preco:
            raise ErroTendencia("preço anunciado e valor de série divergem")
        periodo = ref.isoformat()
        anterior = dias[periodo].get(lote)
        if anterior:
            if anterior["preco"] != preco:
                raise ErroTendencia("ofertas conflitantes do mesmo lote/dia: reconciliação obrigatória")
            repetidos += 1
            anterior["sha"].add(obs["edicao_sha256"])
            anterior["fontes"].add(fonte)
            anterior["publicacao"] = max(anterior["publicacao"], obs["publicacao"])
            anterior["coleta"] = max(anterior["coleta"], obs["coleta"])
        else:
            dias[periodo][lote] = {
                "preco": preco, "publicacao": obs["publicacao"],
                "coleta": obs["coleta"], "fontes": {fonte},
                "sha": {obs["edicao_sha256"]},
            }

    samples = []
    coverage = []
    for periodo, lotes in sorted(dias.items()):
        if len(lotes) < minimo_lotes_dia:
            return {"status": "AMOSTRA_INSUFICIENTE", "tendencia": "INDETERMINADA",
                    "orientacao": "OBSERVADA", "publicavel": False,
                    "motivo": "dia com poucos lotes econômicos independentes",
                    "dia": periodo, "lotes_distintos": len(lotes),
                    "minimo_lotes_dia": minimo_lotes_dia}
        preco_mediano = median(x["preco"] for x in lotes.values())
        provas = sorted((k, str(v["preco"]), sorted(v["sha"]), sorted(v["fontes"]))
                        for k, v in lotes.items())
        digest = sha256(json.dumps(provas, ensure_ascii=True,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()
        sample = {
            "periodo": periodo, "publicacao": max(x["publicacao"] for x in lotes.values()),
            "coleta": max(x["coleta"] for x in lotes.values()),
            "valor": float(preco_mediano), "fonte_id": "NIVON_FRETE_LOTES_UNICOS",
            "edicao_sha256": digest,
        }
        samples.append(sample)
        coverage.append({
            "periodo": periodo, "lotes_distintos": len(lotes),
            "preco_mediano_rs_t": str(preco_mediano),
            "fontes_distintas": len(set().union(*(x["fontes"] for x in lotes.values()))),
            "prova_sha256": digest,
        })
    result = tendencia_observada(
        samples, as_of=as_of, fonte_id="NIVON_FRETE_LOTES_UNICOS",
        unidade="BRL/T", frequencia="SESSOES", janela=janela,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=tolerancia_relativa,
    )
    return {
        **result, "segmento": "FRETE_ANUNCIADO",
        "origem_ibge": origem_ibge, "destino_ibge": destino_ibge,
        "produto": produto, "veiculo": veiculo, "pedagio": pedagio,
        "observacoes_brutas": len(ofertas), "reenvios_deduplicados": repetidos,
        "lotes_distintos_total_por_dia": sum(r["lotes_distintos"] for r in coverage),
        "cobertura_amostral": coverage, "direitos_publicacao_verificados": False,
        "alerta": "Tendência de OFERTAS anunciadas; não é valor contratado, embarque realizado, frete médio do mercado ou volume transportado.",
    }
