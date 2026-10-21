"""Pipeline ANP LPC SEMANAL OFICIAL, totalmente offline e sem publicação.

Conecta os contratos da PR #8 (índice HTML + resumo semanal XLSX) com
o histórico isolado da PR #42. A ingestão real é propositalmente
BLOQUEADA até homologação de layout, publicação, licença e atestador.
Hash documental não é atestação autenticada.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import sqlite3
from typing import Mapping

from .anp_indice_lpc import descobrir_semanas_lpc
from .anp_resumo_lpc import ler_resumo_semanal_lpc
from .anp_semanal_store import (
    ErroANPOficial, _tempo, _sha, gravar_edicao_semanal,
)


class ErroIntegracaoLPC(ErroANPOficial):
    """Inconsistência de identidade, período ou linha de proveniência LPC."""


def integrar_lpc_semanal_offline(
    db: sqlite3.Connection, *, html_indice: bytes, xlsx: bytes,
    arquivo_url: str, ano: int, coletado_indice_em: str,
    coletado_arquivo_em: str, publicado_em: str,
    indice_sha256_esperado: str, arquivo_sha256_esperado: str,
    prova_publicacao_sha256: str,
    municipios_mt: frozenset[str] | None = None,
    classe: str = "SINTETICO",
) -> dict:
    """Registra UMA edição listada no índice, com cronologia verificável.

    O HTML e o XLSX devem ser artefatos já obtidos por meios autorizados.
    Realizar coleta, afirmar data oficial de disponibilização e interpretar
    direitos depende de agentes externos confiáveis, NÃO implementados aqui.
    Este adaptador só aceita fixtures SINTETICAS até homologação independente.
    """
    if classe != "SINTETICO":
        raise PermissionError(
            "ingestão real bloqueada: layout, licença, data de disponibilização "
            "e provas independentes ainda não homologados"
        )
    _sha(indice_sha256_esperado, "indice_sha256_esperado")
    _sha(arquivo_sha256_esperado, "arquivo_sha256_esperado")
    prova = _sha(prova_publicacao_sha256, "prova_publicacao_sha256")
    if not isinstance(html_indice, bytes) or not isinstance(xlsx, bytes):
        raise ErroIntegracaoLPC("artefatos precisam ser bytes já coletados")
    if sha256(html_indice).hexdigest() != indice_sha256_esperado:
        raise ErroIntegracaoLPC("snapshot do índice não corresponde ao SHA esperado")
    if sha256(xlsx).hexdigest() != arquivo_sha256_esperado:
        raise ErroIntegracaoLPC("XLSX não corresponde ao SHA esperado")

    coletado_indice = _tempo(coletado_indice_em, "coletado_indice_em")
    coletado_arquivo = _tempo(coletado_arquivo_em, "coletado_arquivo_em")
    publicado = _tempo(publicado_em, "publicado_em")
    if not (publicado <= coletado_indice <= coletado_arquivo):
        raise ErroIntegracaoLPC(
            "cronologia índice/publicação/arquivo impossível ou anti point-in-time"
        )

    indice = descobrir_semanas_lpc(html_indice, ano=ano)
    encontrados = [e for e in indice["semanas"] if e["url_pagina"] == arquivo_url]
    if len(encontrados) != 1:
        raise ErroIntegracaoLPC(
            "URL do XLSX ausente ou ambígua no índice ANP verificado"
        )
    info = encontrados[0]
    inicio = date.fromisoformat(info["semana_inicio"])
    fim = date.fromisoformat(info["semana_fim"])
    if fim > publicado.date():
        raise ErroIntegracaoLPC(
            "semana do índice é posterior à publicação declarada"
        )

    resumo = ler_resumo_semanal_lpc(
        xlsx,
        coletado_em=coletado_arquivo.isoformat(),
        origem_url=info["url_pagina"],
        municipios_mt=municipios_mt,
    )
    if (resumo.get("sha256") != arquivo_sha256_esperado
            or resumo.get("semanas_distintas") != 1
            or any(
                row["semana_inicio_oficial"] != inicio.isoformat()
                or row["semana_fim_oficial"] != fim.isoformat()
                for row in resumo["observacoes"]
            )):
        raise ErroIntegracaoLPC(
            "período, URL ou hash dentro do XLSX não coincide com o índice"
        )

    gravacao = gravar_edicao_semanal(
        db, resumo=resumo, data_publicacao=publicado.isoformat(),
        prova_publicacao_sha=prova, classe="SINTETICO",
    )
    return {
        **gravacao,
        "status": "LPC_SINTETICO_INTEGRADO_OFFLINE",
        "semana_inicio_oficial": inicio.isoformat(),
        "semana_fim_oficial": fim.isoformat(),
        "indice_sha256": indice_sha256_esperado,
        "arquivo_sha256": arquivo_sha256_esperado,
        "fonte_url": info["url_pagina"],
        "prova_publicacao_sha256": prova,
        "classe_origem": "FIXTURE_SINTETICA_SEM_HOMOLOGACAO",
        "natureza_preco": "MEDIA_AMOSTRAL_MUNICIPAL_REVENDA_DIESEL_B_NAO_FRETE",
        "publicavel": False,
        "preco_atual_verificado": False,
        "semana_calendario_inferida": False,
        "direitos_comerciais": "NAO_HOMOLOGADOS",
        "fonte_real_baixada": False,
    }
