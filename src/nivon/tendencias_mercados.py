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
    """Tendência de variações PAREADAS por ponto de embarque e transportadora.

    Não agrega níveis de frete por município/corredor. Compara somente
    identidade econômica presente em TODOS os dias da janela e mesmas
    condições comerciais; mudanças de composição não geram tendência falsa.
    Lote/ anúncio é proveniência, não unidade estatística independente.
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
    dias: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
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
        pickup = _identidade(obs.get("pickup_entity_id"), "pickup_entity_id", tamanho=150)
        transportadora = _identidade(obs.get("transportadora_id"), "transportadora_id", tamanho=150)
        preco = _dinheiro(obs.get("preco_rs_t"), "preco_rs_t")
        if Decimal(str(obs["valor"])) != preco:
            raise ErroTendencia("preço anunciado e valor de série divergem")
        periodo = ref.isoformat()
        identidade = (pickup, transportadora)
        anterior = dias[periodo].get(identidade)
        if anterior:
            if anterior["preco"] != preco:
                raise ErroTendencia(
                    "ofertas conflitantes do mesmo estabelecimento/transportadora/dia: reconciliação obrigatória"
                )
            repetidos += 1
            anterior["lotes"].add(lote)
            anterior["sha"].add(obs["edicao_sha256"])
            anterior["fontes"].add(fonte)
            anterior["publicacao"] = max(anterior["publicacao"], obs["publicacao"])
            anterior["coleta"] = max(anterior["coleta"], obs["coleta"])
        else:
            dias[periodo][identidade] = {
                "preco": preco, "publicacao": obs["publicacao"],
                "coleta": obs["coleta"], "fontes": {fonte},
                "sha": {obs["edicao_sha256"]}, "lotes": {lote},
            }

    ordenados = sorted(dias.items())
    if len(ordenados) < janela:
        return {"status": "DADOS_INSUFICIENTES", "tendencia": "INDETERMINADA",
                "orientacao": "OBSERVADA", "publicavel": False,
                "necessarias": janela, "disponiveis": len(ordenados)}
    selecionados = ordenados[-janela:]
    for periodo, itens in selecionados:
        if len(itens) < minimo_lotes_dia:
            return {"status": "AMOSTRA_INSUFICIENTE", "tendencia": "INDETERMINADA",
                    "orientacao": "OBSERVADA", "publicavel": False,
                    "motivo": "dia com poucos estabelecimentos/transportadoras distintos",
                    "dia": periodo, "lotes_distintos": len(itens),
                    "minimo_lotes_dia": minimo_lotes_dia}

    painel = set.intersection(*(set(itens) for _, itens in selecionados))
    if len(painel) < minimo_lotes_dia:
        return {"status": "PAINEL_INCOMPARAVEL", "tendencia": "INDETERMINADA",
                "orientacao": "OBSERVADA", "publicavel": False,
                "motivo": "composição de estabelecimentos/transportadoras varia sem painel pareado suficiente",
                "pares_comparaveis": len(painel), "minimo_pares": minimo_lotes_dia}
    pares = sorted(painel)
    base = selecionados[0][1]
    samples = []
    coverage = []
    for periodo, itens in selecionados:
        # Diferença do MESMO estabelecimento e transportadora contra sua
        # própria primeira observação. Não calcula média nem preço municipal.
        variacoes = [itens[k]["preco"] - base[k]["preco"] for k in pares]
        variacao_mediana = median(variacoes)
        provas = [(list(k), str(itens[k]["preco"]), sorted(itens[k]["lotes"]),
                   sorted(itens[k]["sha"]), sorted(itens[k]["fontes"])) for k in pares]
        digest = sha256(json.dumps(provas, ensure_ascii=True,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()
        sample = {
            "periodo": periodo,
            "publicacao": max(itens[k]["publicacao"] for k in pares),
            "coleta": max(itens[k]["coleta"] for k in pares),
            "valor": float(variacao_mediana),
            "fonte_id": "NIVON_FRETE_VARIACAO_PAREADA",
            "edicao_sha256": digest,
        }
        samples.append(sample)
        coverage.append({
            "periodo": periodo,
            "identidades_observadas": len(itens),
            "pares_comparaveis": len(pares),
            "variacao_pareada_mediana_rs_t": str(variacao_mediana),
            "fontes_distintas": len(set().union(*(itens[k]["fontes"] for k in pares))),
            "prova_sha256": digest,
        })
    result = tendencia_observada(
        samples, as_of=as_of, fonte_id="NIVON_FRETE_VARIACAO_PAREADA",
        unidade="BRL/T", frequencia="SESSOES", janela=janela,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=tolerancia_relativa, nao_negativo=False,
    )
    return {
        **result, "segmento": "FRETE_ANUNCIADO",
        "origem_ibge": origem_ibge, "destino_ibge": destino_ibge,
        "produto": produto, "veiculo": veiculo, "pedagio": pedagio,
        "metrica_tendencia": "VARIACAO_PAREADA_POR_ESTABELECIMENTO_TRANSPORTADORA",
        "identidades_comparaveis": [
            {"pickup_entity_id": a, "transportadora_id": b} for a, b in pares
        ],
        "observacoes_brutas": len(ofertas), "reenvios_deduplicados": repetidos,
        "lotes_distintos_total_por_dia": sum(x["identidades_observadas"] for x in coverage),
        "cobertura_amostral": coverage, "direitos_publicacao_verificados": False,
        "alerta": "Variação pareada de FRETES ANUNCIADOS; não é média municipal, preço de mercado, contrato, embarque ou volume realizado.",
    }
