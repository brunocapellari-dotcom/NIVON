"""Ponte estritamente offline entre evidencia arquivada e parser SIDRA.

A origem HTTP, o esquema oficial das variaveis e a data de publicacao
NAO SAO certificados por esta ponte. Nao habilita coleta ou modelos.
"""
from __future__ import annotations

from collections.abc import Mapping

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido, validar_fonte
from .pecuaria_sidra_arquivo import recuperar_pacote_sidra_offline
from .pecuaria_sidra_abate import normalizar_snapshot_sidra_abate


def normalizar_captura_arquivada_sidra(
    *, banco, id_captura: int, especie: str, tabela_sidra: str,
    dimensoes: Mapping[str, str], totais: Mapping[str, str],
    variaveis: Mapping[str, str], status_fonte: str,
    operacoes_autorizadas: set[str],
) -> dict:
    """Normaliza o byte original validado em arquivo e preserva a origem.

    Mapas DnC, IDs de variaveis e codigos totais sao EXTERNAMENTE fornecidos;
    metadados oficiais precisam de revisao independente antes de homologar.
    """
    validar_fonte(status=status_fonte, operacao="LEITURA",
                  operacoes_autorizadas=operacoes_autorizadas)
    if "ARMAZENAMENTO" not in operacoes_autorizadas:
        raise PermissionError("ARMAZENAMENTO nao autorizado")
    if TABELAS_SIDRA.get(especie) != tabela_sidra:
        raise DadoInvalido("especie e tabela SIDRA incompativeis")

    pacote = recuperar_pacote_sidra_offline(banco=banco, id_captura=id_captura)
    if pacote["especie"] != especie or pacote["tabela_sidra"] != tabela_sidra:
        raise DadoInvalido("captura pertence a outra especie/tabela")

    resultado = normalizar_snapshot_sidra_abate(
        bruto=pacote["bruto_valores"],
        especie=especie, tabela_sidra=tabela_sidra,
        dimensoes=dimensoes, totais=totais, variaveis=variaveis,
        publicacao=pacote["publicacao_declarada"],
        coleta=pacote["coleta_declarada"],
        status_fonte=status_fonte,
        operacoes_autorizadas=operacoes_autorizadas,
    )
    if resultado["origem_sha256"] != pacote["sha256_valores"]:
        raise DadoInvalido("hash do parser e arquivo divergentes")

    resultado.update({
        "id_captura": pacote["id_captura"],
        "sha256_metadados": pacote["sha256_metadados"],
        "url_valores_declarada": pacote["url_valores"],
        "url_metadados_declarada": pacote["url_metadados"],
        "status_arquivo": pacote["status"],
        "identidade_arquivo_verificada": True,
        "mapa_dimensional_homologado": False,
        "amostra_real_homologada": False,
        "resposta_http_autenticada": False,
        "timestamps_autenticados": False,
        "coleta_real_executada": False,
        "previsao_homologada": False,
    })
    return resultado
