"""Motor de tendência PAREADA auditável, portado da PR #30.

Mantido em módulo isolado para não sobrescrever o motor legado da PR #18
enquanto ambas as PRs draft são reconciliadas pelo integrador.
Adições: identidade de descarga, PF/PJ e condições econômicas obrigatórias.
Nunca é média ou preço municipal de frete. Não autoriza publicação.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from statistics import median
from typing import Mapping, Sequence
import json

from .motor_tendencias import (
    ErroTendencia, _data, _fonte, _metadados, tendencia_observada,
)
from .tendencias_mercados import PEDAGIO, _ibge, _identidade, _dinheiro


def tendencia_frete_pareado(
    ofertas: Sequence[Mapping], *, origem_ibge: str, destino_ibge: str,
    produto: str, veiculo: str, pedagio: str, as_of: str,
    descarga_entity_id: str, regime: str,
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
    descarga_entity_id = _identidade(descarga_entity_id, "descarga_entity_id", tamanho=150)
    if regime not in {"PF", "PJ", "NAO_INFORMADO"}:
        raise ErroTendencia("regime PF/PJ obrigatório")
    if pedagio not in PEDAGIO:
        raise ErroTendencia("condição de pedágio precisa ser informada")
    if tolerancia_relativa != 0:
        raise ErroTendencia("limiar relativo de frete exige normalização pareada própria; usar tolerância absoluta em BRL/T")
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
            obs.get("descarga_entity_id") != descarga_entity_id,
            obs.get("regime") != regime,
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
        "descarga_entity_id": descarga_entity_id, "regime": regime,
        "metrica_tendencia": "VARIACAO_PAREADA_POR_ESTABELECIMENTO_TRANSPORTADORA",
        "escopo_economico": "MESMA_DESCARGA_REGIME_PRODUTO_EQUIPAMENTO_PEDAGIO_BASE",
        "identidades_comparaveis": [
            {"pickup_entity_id": a, "transportadora_id": b} for a, b in pares
        ],
        "observacoes_brutas": len(ofertas), "reenvios_deduplicados": repetidos,
        "lotes_distintos_total_por_dia": sum(x["identidades_observadas"] for x in coverage),
        "cobertura_amostral": coverage, "direitos_publicacao_verificados": False,
        "alerta": "Variação pareada de FRETES ANUNCIADOS; não é média municipal, preço de mercado, contrato, embarque ou volume realizado.",
    }
