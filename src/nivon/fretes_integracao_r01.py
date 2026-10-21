"""Pipeline offline: registros NIVON -> painel R01 -> tendência pareada.

Port da metodologia da PR #30, com controles de identidade e divulgação da
PR #18. Não cria preço médio municipal, probabilidade calibrada ou publicação.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from .fretes_registros import OfertaFrete
from .fretes_painel_pr30 import preparar_painel_pr30
from .fretes_tendencia_pareada import tendencia_frete_pareado


def tendencia_ofertas_pareadas(
    ofertas: Sequence[OfertaFrete], *,
    origem_ibge: str, destino_ibge: str,
    descarga_entity_id: str, produto: str, equipamento: str,
    regime: str, pedagio: str, as_of: datetime, janela: int = 6,
    minimo_pares: int = 2, tolerancia_absoluta: float = 2.0,
) -> dict:
    """Tendência DESCRITIVA de mudanças dos mesmos pontos e transportadoras.

    Exige data de observação e corte as-of. Registros chegam de caminho
    confiável auditado pelo chamador; resultados nunca habilitam publicação.
    """
    prep = preparar_painel_pr30(
        ofertas,
        origem_ibge=origem_ibge, destino_ibge=destino_ibge,
        descarga_entity_id=descarga_entity_id, produto=produto,
        equipamento=equipamento, regime=regime, pedagio=pedagio, as_of=as_of,
    )
    corte_local = as_of.astimezone(ZoneInfo("America/Cuiaba")).date().isoformat()
    resultado = tendencia_frete_pareado(
        prep["observacoes"],
        origem_ibge=origem_ibge, destino_ibge=destino_ibge,
        descarga_entity_id=descarga_entity_id, produto=produto,
        veiculo=equipamento, pedagio=pedagio, regime=regime,
        as_of=corte_local, janela=janela,
        minimo_lotes_dia=minimo_pares,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=0,
    )
    return {
        **resultado,
        "motor": "R01_PR30_PAREADO_PORTADO_NA_PR18",
        "tipo_de_valor": "VARIACAO_PRECO_BASE_ANUNCIADO_NAO_PRECO_MUNICIPAL",
        "as_of_instante": prep["as_of"],
        "quantidade_bruta": prep["quantidade_bruta"],
        "identidades_dia": prep["identidades_dia"],
        "repeticoes_mesmo_ponto_e_preco": prep["repeticoes_mesmo_ponto_e_preco"],
        "direitos_publicacao_verificados": False,
        "publicavel": False,
        "probabilidades_calibradas": None,
        "homologacao_origem": "PENDENTE",
    }
