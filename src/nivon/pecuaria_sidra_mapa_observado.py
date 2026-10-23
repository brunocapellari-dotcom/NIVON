"""Mapeamento observado diretamente no endpoint SIDRA values, 23/10/2026.

As classificações foram conferidas SOMENTE no recorte Brasil/2026-T2,
não em metadados API v3. Logo, não comprova validade temporal/territorial
global, licença, autenticidade retrospectiva ou homologação operacional.
"""
from __future__ import annotations

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido

_VARIAVEIS = {"284": "ABATE_CABECAS", "285": "PESO_CARCACAS_KG"}
_COMUM = {"territorio": "D1C", "periodo": "D2C", "variavel": "D3C"}
_MAPA = {
    "BOVINO": {
        "dimensoes": {**_COMUM, "rebanho": "D4C",
                      "inspecao": "D5C", "referencia_temporal": "D6C"},
        "totais": {"rebanho": "992", "inspecao": "118225",
                   "referencia_temporal": "115236"},
        "sha256_amostra_nacional": "a6528eeab202faf2c5a0ef1b3133d4304093fcff26a7a3580cacadd148ae2919",
    },
    "SUINO": {
        "dimensoes": {**_COMUM, "inspecao": "D4C",
                      "referencia_temporal": "D5C"},
        "totais": {"inspecao": "118225", "referencia_temporal": "115236"},
        "sha256_amostra_nacional": "c6ba703c71cb2c14a44e6598c01fbe26fb8863b076bae4ca36a113423e6c8a42",
    },
    "FRANGO": {
        "dimensoes": {**_COMUM, "inspecao": "D4C",
                      "referencia_temporal": "D5C"},
        "totais": {"inspecao": "118225", "referencia_temporal": "115236"},
        "sha256_amostra_nacional": "f6bddcb21d92ec1a67bead6217d274f714f4ef52b6e856f1586ee915d9d3481b",
    },
}
_EVIDENCIA = (
    "https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945191701"
)


def contrato_sidra_observado(*, especie, tabela_sidra):
    """Retorna uma COPIA do mapa observado, nunca IDs presumidos por terceiros."""
    if TABELAS_SIDRA.get(especie) != tabela_sidra or especie not in _MAPA:
        raise DadoInvalido("especie/tabela sem evidencia observada")
    dados = _MAPA[especie]
    return {"especie": especie, "tabela_sidra": tabela_sidra,
            "dimensoes": dict(dados["dimensoes"]),
            "totais": dict(dados["totais"]),
            "variaveis": dict(_VARIAVEIS),
            "hash_amostra_nacional_bruta": dados["sha256_amostra_nacional"],
            "referencia_competencia": "2026-T2",
            "fonte_evidencia": _EVIDENCIA,
            "classificacao": "MAPA_OBSERVADO_VALUES_NAO_HOMOLOGADO",
            "validade_outros_periodos_territorios_confirmada": False,
            "metadados_api_v3_verificados": False,
            "licenca_verificada": False,
            "publicacao_permitida": False}
