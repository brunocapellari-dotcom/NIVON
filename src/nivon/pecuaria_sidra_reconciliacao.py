"""Reconciliacao diagnostica BR x UF do SIDRA sem imputacao.

Nao calcula soma das UFs como proxy Brasil quando a cobertura oficial nao
esta autenticada, ainda que o recorte observado contenha 27 UFs.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido
from .pecuaria_sidra_abate import UF_IBGE, INDICADORES
from .pecuaria_sidra_vintages import historico_sidra_asof


def diagnosticar_cobertura_abate(*, snapshots, especie, tabela_sidra, corte_asof):
    """Reúne BR e UFs de snapshots separados, preservando censura e datas."""
    if TABELAS_SIDRA.get(especie) != tabela_sidra:
        raise DadoInvalido("especie/tabela divergentes")
    if not isinstance(snapshots, (list, tuple)) or not 1 <= len(snapshots) <= 10:
        raise DadoInvalido("snapshots ausentes ou excessivos")
    historico = historico_sidra_asof(
        snapshots=snapshots, especie=especie,
        tabela_sidra=tabela_sidra, corte_asof=corte_asof)
    grouped = defaultdict(lambda: {"numericos": set(), "censurados": set(),
                                   "br_numerico": False, "br_censurado": False})
    for obs in historico["observacoes"]:
        g = grouped[(obs.competencia, obs.indicador)]
        if obs.uf == "BR":
            g["br_numerico"] = True
        else:
            g["numericos"].add(obs.uf)
    for c in historico["censuras_vigentes"]:
        g = grouped[(c["competencia"], c["indicador"])]
        if c["uf"] == "BR":
            g["br_censurado"] = True
        else:
            g["censurados"].add(c["uf"])
    known = set(UF_IBGE.values())
    records = []
    for (periodo, indicador), data in sorted(grouped.items()):
        numericos = data["numericos"]
        censurados = data["censurados"]
        if (indicador not in INDICADORES or numericos & censurados
            or (numericos | censurados) - known):
            raise DadoInvalido("status territorial inconsistente")
        restantes = known - (numericos | censurados)
        status = (
            "SEM_BR" if not data["br_numerico"] else
            "UF_INCOMPLETAS_OU_CENSURADAS" if censurados or restantes else
            "27_UFS_OBSERVADAS_MAS_METADADOS_NAO_HOMOLOGADOS")
        records.append({
            "especie": especie, "tabela_sidra": tabela_sidra,
            "competencia": periodo, "indicador": indicador,
            "br_numerico": data["br_numerico"],
            "br_censurado": data["br_censurado"],
            "ufs_numericas": sorted(numericos),
            "ufs_censuradas": sorted(censurados),
            "ufs_nao_presentes": sorted(restantes),
            "quantidade_ufs_numericas": len(numericos),
            "quantidade_ufs_censuradas": len(censurados),
            "quantidade_ufs_nao_presentes": len(restantes),
            "status": status,
            "soma_ufs": None,
            "residuo_brasil": None,
            "cobertura_homologada": False,
            "publicacao_permitida": False,
        })
    return {
        "especie": especie, "tabela_sidra": tabela_sidra,
        "corte_asof": corte_asof, "indicadores": records,
        "revisoes": len(historico["revisoes"]),
        "linhas_vigentes": len(historico["observacoes"]),
        "censuras_vigentes": len(historico["censuras_vigentes"]),
        "metadados_v3_verificados": False,
        "publicacao_permitida": False,
        "classificacao": "DIAGNOSTICO_TERRITORIAL_NAO_HOMOLOGADO",
    }
