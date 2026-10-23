"""Inspeção offline e estritamente descritiva de um RONI ASCII fornecido.

Só valida bytes, formato, domínio e cobertura da amostra. Não baixa nada,
não escreve os dados e NÃO transforma coleta atual em vintage histórico.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from re import fullmatch

from .noaa_roni import (
    ENDPOINT_OFICIAL, ErroRONI, classificar_episodios_roni,
    importar_roni_ascii,
)


def inspecionar_amostra_roni_offline(
    *, raw: bytes, coletado_em: str, endereco_declarado: str,
    sha256_recebido: str, escopo: str = "EXCERTO_24_OU_MAIS",
) -> dict:
    """Inspeciona bytes locais; devolve só resumo, jamais RAW nem séries.

    Escopo HISTORICO_DESDE_1950 exige primeira competência 1950-01
    e ao menos 900 temporadas sobrepostas consecutivas: preserva
    distinção entre arquivo histórico extenso e simples excerto de teste.
    Mesmo então não há autenticação de origem nem prova point-in-time.
    """
    if endereco_declarado != ENDPOINT_OFICIAL:
        raise ErroRONI("endereço não corresponde à rota NOAA CPC RONI ERSSTv6")
    if not isinstance(raw, bytes) or not raw:
        raise ErroRONI("bytes brutos devem ser fornecidos localmente")
    digest = sha256(raw).hexdigest()
    if (not isinstance(sha256_recebido, str)
            or not fullmatch(r"[a-f0-9]{64}", sha256_recebido)
            or sha256_recebido != digest):
        raise ErroRONI("SHA-256 de entrada divergente do conteúdo bruto")
    if escopo not in ("EXCERTO_24_OU_MAIS", "HISTORICO_DESDE_1950"):
        raise ErroRONI("escopo de inspeção desconhecido")
    pacote = importar_roni_ascii(
        raw=raw, coletado_em=coletado_em, versao_ersst="6")
    first = pacote["centro_primeiro"]
    last = pacote["centro_ultimo"]
    count = pacote["quantidade"]
    if escopo == "HISTORICO_DESDE_1950" and (
            first != "1950-01" or count < 900):
        raise ErroRONI("suposto histórico completo contém somente excerto")
    events = classificar_episodios_roni(pacote)["eventos"]
    # A coleta do arquivo está registrada, mas o instante histórico de
    # publicação de cada valor é desconhecido e não é inferido.
    return {
        "dataset_id": "NOAA_ENSO_RONI",
        "origem_url_declarada": endereco_declarado,
        "origem_autenticada_externamente": False,
        "sha256_bruto_conferido": digest,
        "sha256_ancorado_externamente": False,
        "tamanho_bytes": len(raw),
        "escopo_verificado": escopo,
        "quantidade_temporadas": count,
        "competencia_primeira": first,
        "competencia_ultima": last,
        "numero_episodios_retrospectivos": len(events),
        "coletado_em_utc": pacote["coletado_em_utc"],
        "observacoes_reais_comprovadas": False,
        "licencas_e_atribuicao_auditadas": False,
        "publicacao_individual_conhecida": False,
        "reconstrucao_historica_asof_aprovada": False,
        "aptidao_uso_preditivo": False,
        "pode_ativar_coletor": False,
        "homologado": False,
        "estado": "INSPECAO_LOCAL_SEM_PROVA_ORIGEM_NEM_VINTAGE",
    }
