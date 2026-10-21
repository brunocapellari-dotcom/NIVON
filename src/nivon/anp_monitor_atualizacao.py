"""Auditoria de atualidade das publicações ANP, sem baixar planilhas.

O índice semanal e o histórico anual são fontes DISTINTAS: alteração da página
não prova atualização das séries ou preços; semana publicada não é observação
homologada. O controle só compara metadados observados e checksums.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from .anp_indice_lpc import URL_INDICE, descobrir_semanas_lpc
from .lineup_nacional import instante

URL_SERIE_2026 = (
    "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
    "precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/"
    "semanal-municipios-2026.xlsx/view"
)


class ErroMonitorANP(ValueError):
    pass


def _validar_metadado(m: dict, *, gerado_em: str) -> dict:
    """Meta vem de coleta de página, não de suposição baseada no nome do arquivo."""
    agora = instante(gerado_em)
    if not isinstance(m, dict) or m.get("pagina_url") != URL_SERIE_2026:
        raise ErroMonitorANP("origem do histórico anual não verificada")
    if m.get("arquivo_baixado") is not False or m.get("schema_homologado") is not False:
        raise ErroMonitorANP("monitor não declara download/schema já homologados")
    atualizado = instante(m.get("pagina_atualizada_em"))
    coletado = instante(m.get("pagina_coletada_em"))
    if atualizado > coletado or coletado > agora:
        raise ErroMonitorANP("atualização e captura do histórico incoerentes")
    sha = m.get("html_sha256")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha):
        raise ErroMonitorANP("prova SHA da página anual ausente")
    return {"atualizado": atualizado, "coletado": coletado, "hash": sha}


def auditar_publicacoes_anp(
    indice_semanal_html: bytes, *,
    indice_coletado_em: str, gerado_em: str,
    anual: dict | None = None,
    indice_anterior_sha256: str | None = None,
    semanas_anteriormente_observadas: frozenset[str] | None = None,
    atraso_limite_dias: int = 14,
) -> dict:
    """Última semana comprovadamente LINKADA no índice e alertas de atualização.

    Não conclui que dado é atual se só a página anual mudou; não pode afirmar
    'preço do dia' nem publicar uma média sem arquivo e layout real auditados.
    """
    agora = instante(gerado_em)
    coleta = instante(indice_coletado_em)
    if coleta > agora:
        raise ErroMonitorANP("captura de índice no futuro")
    if type(atraso_limite_dias) is not int or not 1 <= atraso_limite_dias <= 30:
        raise ErroMonitorANP("tolerância de atraso inválida")
    if indice_anterior_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", indice_anterior_sha256):
        raise ErroMonitorANP("SHA do índice anterior inválido")
    if semanas_anteriormente_observadas is not None and (
        not isinstance(semanas_anteriormente_observadas,frozenset) or
        any(not isinstance(s,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",s)
            for s in semanas_anteriormente_observadas)
    ):
        raise ErroMonitorANP("snapshot anterior de competências inválido")

    descoberto = descobrir_semanas_lpc(
        indice_semanal_html, ano=agora.year, url_indice=URL_INDICE
    )
    novas = {x["semana_fim"] for x in descoberto["semanas"]}
    anterior = semanas_anteriormente_observadas or frozenset()
    retirada = sorted(anterior - novas)
    novidades = sorted(novas - anterior)
    alertas=[]
    if retirada:
        alertas.append("SEMANAS_ANTES_PRESENTES_REMOVIDAS_DO_INDICE")
    if indice_anterior_sha256 is not None and (
        descoberto["indice_sha256"] != indice_anterior_sha256
        and not novidades and not retirada
    ):
        alertas.append("HTML_ALTERADO_SEM_NOVA_SEMANA_VERIFICADA")
    anual_evidencia = None
    if anual is not None:
        m = _validar_metadado(anual,gerado_em=gerado_em)
        anual_evidencia = {
            "pagina_url": URL_SERIE_2026,
            "pagina_atualizada_em": m["atualizado"].isoformat(),
            "pagina_sha256": m["hash"],
            "arquivo_baixado": False,
            "schema_homologado": False,
        }
    ultima = descoberto["semanas"][-1] if descoberto["semanas"] else None
    atraso = (agora.date()-date.fromisoformat(ultima["semana_fim"])).days if ultima else None
    if ultima is None:
        alertas.append("SEM_SEMANA_LOCALIZADA_NO_INDICE")
    elif atraso < 0:
        alertas.append("PERIODO_SEMANAL_TERMINA_NO_FUTURO")
    elif atraso > atraso_limite_dias:
        alertas.append("INDICE_SEMANAL_DEFASADO")
    if anual_evidencia and ultima and (
        m["atualizado"].date() > date.fromisoformat(ultima["semana_fim"])
    ):
        alertas.append("PAGINA_ANUAL_ATUALIZADA_NAO_PROVA_DADOS_DA_SEMANA")

    return {
        "dataset_id": "ANP_PRECO_REVENDA_DIESEL",
        "indice_url": URL_INDICE,
        "indice_sha256": descoberto["indice_sha256"],
        "indice_coletado_em": coleta.isoformat(),
        "ultima_semana_linkada": ultima,
        "dias_desde_fim_semana": atraso,
        "semanas_indexadas": descoberto["total_semanas"],
        "novas_competencias_observadas": novidades,
        "competencias_removidas": retirada,
        "alertas": alertas,
        "arquivo_anual": anual_evidencia,
        "coleta_preco_executada": False,
        "publicacao_autorizada": False,
        "natureza": "METADADOS_DE_INDICE_NAO_PRECOS",
        "proxima_acao": "Obter XLSX licitamente, conferir SHA, schema, semana e direitos antes do indicador",
    }
