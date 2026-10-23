"""Pré-voo OFFLINE de cobertura temporal de ofertas R01 (7/30/90 DIAS).

Identifica pares ponto/transportadora que têm observações nas duas pontas
de cada horizonte em DIAS CORRIDOS. Não prevê, não produz fold OOS e não
confunde mensagens com contratos, caminhões ou toneladas transportadas.
Proveniência fornecida/derivada ainda exige auditoria externa independente.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Sequence
from zoneinfo import ZoneInfo

from .fretes_painel_pr30 import preparar_painel_pr30
from .fretes_registros import OfertaFrete, ErroRegistroFrete


class ErroCoberturaFrete(ErroRegistroFrete):
    """Configuração de janela ou contrato de análise incompatível."""


def _fingerprint(obj: object) -> str:
    return sha256(json.dumps(
        obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def auditar_cobertura_horizontes_frete(
    ofertas: Sequence[OfertaFrete], *,
    origem_ibge: str, destino_ibge: str, descarga_entity_id: str,
    produto: str, equipamento: str, regime: str, pedagio: str,
    as_of: datetime, horizontes_dias: tuple[int, ...] = (7, 30, 90),
    minimo_pares_por_origem: int = 2,
    minimo_origens_por_horizonte: int = 30,
) -> dict:
    """Conta possíveis ALVOS históricos, não previsões retroativas.

    Mesmo par (pickup_entity_id, transportadora_id) deve existir na origem
    e no alvo EXATAMENTE H dias corridos depois. Não preenche dias ausentes.
    A oferta só entra após os controles comerciais e temporais da R01.
    Um par pode ocorrer em muitos folds e folds podem sobrepor horizontes;
    portanto a quantidade de pares NÃO é N independente nem backtesting.
    """
    if (not isinstance(horizontes_dias, tuple)
            or not 1 <= len(horizontes_dias) <= 8
            or any(type(h) is not int or not 1 <= h <= 365 for h in horizontes_dias)
            or sorted(set(horizontes_dias)) != list(horizontes_dias)):
        raise ErroCoberturaFrete("horizontes_dias devem ser inteiros distintos e crescentes de 1 a 365")
    if (type(minimo_pares_por_origem) is not int
            or not 2 <= minimo_pares_por_origem <= 100):
        raise ErroCoberturaFrete("mínimo de pares por origem inválido")
    if (type(minimo_origens_por_horizonte) is not int
            or not 1 <= minimo_origens_por_horizonte <= 10000):
        raise ErroCoberturaFrete("mínimo de origens por horizonte inválido")
    if (not isinstance(as_of, datetime) or as_of.tzinfo is None
            or as_of.utcoffset() is None):
        raise ErroCoberturaFrete("as_of exige instante timezone-aware")
    painel = preparar_painel_pr30(
        ofertas, origem_ibge=origem_ibge, destino_ibge=destino_ibge,
        descarga_entity_id=descarga_entity_id, produto=produto,
        equipamento=equipamento, regime=regime, pedagio=pedagio,
        as_of=as_of,
    )
    cutoff_day = as_of.astimezone(ZoneInfo("America/Cuiaba")).date()
    dias: dict = {}
    for row in painel["observacoes"]:
        from datetime import date
        dia = date.fromisoformat(row["periodo"])
        chave = (row["pickup_entity_id"], row["transportadora_id"])
        dias.setdefault(dia, {})[chave] = row
    ordenados = sorted(dias)
    resultados = []
    for horizonte in horizontes_dias:
        datas_maturadas = 0
        ainda_imaturas = 0
        sem_alvo = 0
        insuficientes = 0
        origens_comparaveis = 0
        pares_total = 0
        compromissos = []
        amostras_dias = []
        for origem in ordenados:
            alvo = origem + timedelta(days=horizonte)
            if alvo > cutoff_day:
                ainda_imaturas += 1
                continue
            datas_maturadas += 1
            if alvo not in dias:
                sem_alvo += 1
                continue
            mesmos = sorted(dias[origem].keys() & dias[alvo].keys())
            if len(mesmos) < minimo_pares_por_origem:
                insuficientes += 1
                continue
            # Fingerprint inclui evidencia DERIVADA das duas pontas e os
            # pares lógicos, sem divulgar nomes/IDs individuais na saída.
            detalhes = [
                [list(k), dias[origem][k]["edicao_sha256"],
                 dias[alvo][k]["edicao_sha256"]]
                for k in mesmos
            ]
            digest = _fingerprint({
                "origem": origem.isoformat(), "alvo": alvo.isoformat(),
                "horizonte_dias_corridos": horizonte, "pares": detalhes,
            })
            compromissos.append(digest)
            if len(amostras_dias) < 3:
                amostras_dias.append({
                    "data_origem": origem.isoformat(),
                    "data_alvo": alvo.isoformat(),
                    "pares_comparaveis": len(mesmos),
                    "evidencia_derivada_sha256": digest,
                })
            origens_comparaveis += 1
            pares_total += len(mesmos)
        resultado = {
            "horizonte_dias_corridos": horizonte,
            "origens_observadas": len(ordenados),
            "origens_com_alvo_maturado": datas_maturadas,
            "origens_ainda_nao_maturadas": ainda_imaturas,
            "origens_sem_alvo_observado": sem_alvo,
            "origens_com_pares_insuficientes": insuficientes,
            "origens_com_pares_comparaveis": origens_comparaveis,
            "pares_origem_alvo_total_nao_independentes": pares_total,
            "minimo_origens_para_ensaio": minimo_origens_por_horizonte,
            "amostras_de_evidencia": amostras_dias,
            "fingerprint_cobertura_sha256": _fingerprint(compromissos),
            "status": (
                "ALVOS_HISTORICOS_IDENTIFICADOS_SEM_FORECAST_ARQUIVADO"
                if origens_comparaveis >= minimo_origens_por_horizonte
                else "COBERTURA_INSUFICIENTE"
            ),
            "avaliacao_oos_executada": False,
            "observacoes_independentes_comprovadas": False,
            "publicavel": False,
        }
        resultados.append(resultado)
    return {
        "status": "AUDITORIA_COBERTURA_DECLARADA_OFFLINE",
        "orientacao": "PREPARACAO_HISTORICA_SEM_PREVISAO",
        "origem_ibge": origem_ibge,
        "destino_ibge": destino_ibge,
        "descarga_entity_id": descarga_entity_id,
        "produto": produto, "equipamento": equipamento,
        "regime": regime, "pedagio": pedagio,
        "natureza": "OFERTAS_ANUNCIADAS_BASE_NAO_CONTRATADAS",
        "unidade": "BRL/T",
        "as_of": as_of.isoformat(),
        "dias_observados": len(dias),
        "periodo_inicio": ordenados[0].isoformat(),
        "periodo_fim": ordenados[-1].isoformat(),
        "quantidade_bruta": painel["quantidade_bruta"],
        "repeticoes_deduplicadas": painel["repeticoes_mesmo_ponto_e_preco"],
        "horizontes": resultados,
        "calendario_coleta_externo_verificado": False,
        "licenca_de_uso_e_redistribuicao_comprovada": False,
        "integridade_raw_comprovada": False,
        "historico_real_homologado": False,
        "previsoes_arquivadas_validadas": False,
        "backtest_executado": False,
        "probabilidades_calibradas": None,
        "publicavel": False,
        "limitacao": (
            "Contagem de dias e pares com preços anunciados nas duas pontas; "
            "não comprova cobertura integral de dias sem anúncios, independência, "
            "previsão emitida na origem ou habilidade preditiva. "
            "Precisa de calendário de coleta, vintages RAW, forecasts imutáveis, "
            "baseline temporal, backtesting e licenças verificados."
        ),
    }
