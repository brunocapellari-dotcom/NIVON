"""Diagnóstico histórico de FORÇA de frete anunciado por painel pareado R01.

Evita tendência artificial de mudança na composição de estabelecimentos:
usa os MESMOS pares ponto de embarque/transportadora em AMBAS as janelas.
Não é cotação de mercado, frete contratado, previsão nem probabilidade.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from .dinamica_tendencias import comparar_forca_tendencia
from .fretes_registros import OfertaFrete
from .fretes_painel_pr30 import preparar_painel_pr30
from .motor_tendencias import ErroTendencia
from .tendencias_mercados import tendencia_frete_anunciado


def dinamica_ofertas_pareadas(
    ofertas: Sequence[OfertaFrete], *,
    origem_ibge: str, destino_ibge: str, descarga_entity_id: str,
    produto: str, equipamento: str, regime: str, pedagio: str,
    as_of: datetime, janela: int = 6, minimo_pares: int = 2,
    tolerancia_absoluta: float = 2.0,
    mudanca_minima_forca_em_limiares: float = 1.0,
) -> dict:
    """Compara 2 janelas disjuntas com identidade econômica CONSTANTE.

    Os dados entram pelo contrato OfertaFrete e pelo painel da integração
    logística; sua autorização/proveniência externa é uma pré-condição.
    O motor pareado constrói série de diferenças históricas contra a primeira
    observação dos MESMOS pares, nunca mediana de nível dos fretes municipais.
    """
    if type(janela) is not int or not 4 <= janela <= 24:
        raise ErroTendencia("janela deve conter de 4 a 24 sessões (2 janelas)")
    if type(minimo_pares) is not int or not 2 <= minimo_pares <= 100:
        raise ErroTendencia("mínimo de pares inválido")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ErroTendencia("as_of deve ser instante com fuso explícito")
    if not isinstance(mudanca_minima_forca_em_limiares, (int, float)) or isinstance(
        mudanca_minima_forca_em_limiares, bool
    ):
        raise ErroTendencia("limiar de força numérico obrigatório")
    painel = preparar_painel_pr30(
        ofertas, origem_ibge=origem_ibge, destino_ibge=destino_ibge,
        descarga_entity_id=descarga_entity_id, produto=produto,
        equipamento=equipamento, regime=regime, pedagio=pedagio, as_of=as_of,
    )
    data_local = as_of.astimezone(ZoneInfo("America/Cuiaba")).date().isoformat()
    # A mesma interseção de (pickup, transportadora) vale por 2*janela sessões.
    base = tendencia_frete_anunciado(
        painel["observacoes"], origem_ibge=origem_ibge,
        destino_ibge=destino_ibge, descarga_entity_id=descarga_entity_id,
        produto=produto, veiculo=equipamento, regime=regime,
        pedagio=pedagio, as_of=data_local, janela=2*janela,
        minimo_lotes_dia=minimo_pares, tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=0, incluir_serie_pareada=True,
    )
    if "serie_pareada" not in base:
        return {
            "status": base["status"], "orientacao": "OBSERVADA",
            "tendencia_atual": "INDETERMINADA", "dinamica": "INDETERMINADA",
            "motivo": base.get("motivo", "sem painel econômico comparável em ambas as janelas"),
            "pares_comparaveis": base.get("pares_comparaveis", 0),
            "necessarias": 2*janela, "publicavel": False,
            "probabilidades_calibradas": None,
            "homologacao_origem": "PENDENTE",
        }
    amostras = base["serie_pareada"]
    dinamica = comparar_forca_tendencia(
        amostras, as_of=data_local,
        fonte_id="NIVON_FRETE_VARIACAO_PAREADA",
        unidade="BRL/T", frequencia="SESSOES", janela=janela,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=0,
        mudanca_minima_forca_em_limiares=mudanca_minima_forca_em_limiares,
        nao_negativo=False,  # diferenças de preço podem ser negativas
    )
    return {
        **dinamica,
        "tendencia": dinamica["tendencia_atual"],
        "segmento": "FRETE_ANUNCIADO",
        "metrica_tendencia": "DINAMICA_DE_VARIACOES_PAREADAS_BRLT_BASE",
        "origem_ibge": origem_ibge, "destino_ibge": destino_ibge,
        "descarga_entity_id": descarga_entity_id, "produto": produto,
        "equipamento": equipamento, "regime": regime,
        "pedagio": pedagio,
        "identidades_comparaveis": base["identidades_comparaveis"],
        "pares_comparaveis": len(base["identidades_comparaveis"]),
        "cobertura_amostral": base["cobertura_amostral"],
        "quantidade_bruta": painel["quantidade_bruta"],
        "identidades_dia": painel["identidades_dia"],
        "repeticoes_mesmo_ponto_e_preco": painel["repeticoes_mesmo_ponto_e_preco"],
        "as_of_instante": painel["as_of"],
        "metodologia_painel": "PARES_CONSTANTES_DUAS_JANELAS",
        "valor_analisado": "FRETE_BASE_ANUNCIADO_SEM_PEDAGIO",
        "edicao_sha256_classe": painel["edicao_sha256_classe"],
        "direitos_publicacao_verificados": False,
        "homologacao_origem": "PENDENTE",
        "probabilidades_calibradas": None,
        "publicavel": False,
        "alerta": (
            "Força histórica de variações em ofertas dos mesmos estabelecimentos "
            "e transportadoras; NÃO é preço de frete médio municipal, cotação "
            "contratada, volume observado ou previsão de 7/30/90 dias."
        ),
    }
