"""Pré-homologação OFFLINE de três XLSX semanais ANP/LPC.

Aceita somente bytes já obtidos legitimamente, não faz download, não
persiste dados e jamais promove uma edição para REAL_AUTORIZADO.
Um SHA prova integridade referencial, NÃO prova identidade do publicador,
data efetiva de publicação ou permissões legais.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from hashlib import sha256
from typing import Mapping, Sequence

from .anp_indice_lpc import descobrir_semanas_lpc
from .anp_resumo_lpc import ler_resumo_semanal_lpc
from .anp_semanal_store import _sha, _tempo


class ErroHomologacaoLPC(ValueError):
    pass


def auditar_tres_edicoes_lpc(
    *, indice_html: bytes, indice_sha256_esperado: str,
    capturado_indice_em: str, edicoes: Sequence[Mapping],
    ano: int, municipios_mt: frozenset[str] | None = None,
) -> dict:
    """Valida três semanas CONTÍGUAS somente para revisão independente.

    Para cada edição exigir: url, bytes XLSX, SHA, publicado_em declarado,
    coletado_em e prova_publicacao_sha256. Não concluir que esse SHA
    autentique a data; saída sempre NAO_HOMOLOGADO.
    """
    if not isinstance(indice_html, bytes):
        raise ErroHomologacaoLPC("snapshot HTML em bytes obrigatório")
    _sha(indice_sha256_esperado, "indice_sha256_esperado")
    if sha256(indice_html).hexdigest() != indice_sha256_esperado:
        raise ErroHomologacaoLPC("SHA do índice não confere")
    coleta_indice = _tempo(capturado_indice_em, "capturado_indice_em")
    if not isinstance(edicoes, (list, tuple)) or len(edicoes) != 3:
        raise ErroHomologacaoLPC("homologação estrutural exige exatamente três edições")
    indice = descobrir_semanas_lpc(indice_html, ano=ano)
    mapa = {r["url_pagina"]: r for r in indice["semanas"]}

    periodos = set()
    shas = set()
    auditorias = []
    cobertura = defaultdict(set)
    for pos, e in enumerate(edicoes, 1):
        if not isinstance(e, Mapping) or set(e) != {
            "url", "xlsx", "sha256", "publicado_em",
            "coletado_em", "prova_publicacao_sha256",
        }:
            raise ErroHomologacaoLPC(f"edição {pos}: contrato de entrada incompleto")
        url = e["url"]
        if not isinstance(url, str) or url not in mapa:
            raise ErroHomologacaoLPC("arquivo não listado no índice oficial fornecido")
        if not isinstance(e["xlsx"], bytes):
            raise ErroHomologacaoLPC("XLSX deve ser bytes locais")
        sha = _sha(e["sha256"], "sha256_xlsx")
        _sha(e["prova_publicacao_sha256"], "prova_publicacao_sha256")
        if sha256(e["xlsx"]).hexdigest() != sha:
            raise ErroHomologacaoLPC("arquivo XLSX alterado ou SHA divergente")
        if sha in shas:
            raise ErroHomologacaoLPC("mesmo XLSX reapresentado como semana distinta")
        shas.add(sha)
        pub = _tempo(e["publicado_em"], "publicado_em")
        coleta = _tempo(e["coletado_em"], "coletado_em")
        if pub > coleta or pub > coleta_indice or coleta < coleta_indice:
            raise ErroHomologacaoLPC("publicação/captura cronologicamente incompatíveis")
        info = mapa[url]
        inicio = date.fromisoformat(info["semana_inicio"])
        fim = date.fromisoformat(info["semana_fim"])
        if fim > pub.date():
            raise ErroHomologacaoLPC("semana ainda não encerrada na data de publicação declarada")
        periodo = (inicio, fim)
        if periodo in periodos:
            raise ErroHomologacaoLPC("edição da mesma semana duplicada")
        periodos.add(periodo)

        resumo = ler_resumo_semanal_lpc(
            e["xlsx"], coletado_em=coleta.isoformat(),
            origem_url=url, municipios_mt=municipios_mt,
        )
        if (resumo["sha256"] != sha or resumo["semanas_distintas"] != 1 or
            any(r["semana_inicio_oficial"] != inicio.isoformat() or
                r["semana_fim_oficial"] != fim.isoformat()
                for r in resumo["observacoes"])):
            raise ErroHomologacaoLPC("período XLSX difere do índice; não homologar")
        produtos = set()
        municipios = set()
        for linha in resumo["observacoes"]:
            chave = (linha["municipio"], linha["produto"])
            cobertura[chave].add(inicio)
            produtos.add(linha["produto"])
            municipios.add(linha["municipio"])
        auditorias.append({
            "semana_inicio": inicio.isoformat(),
            "semana_fim": fim.isoformat(),
            "url": url,
            "sha256": sha,
            "registros_municipio_produto": len(resumo["observacoes"]),
            "municipios_amostrados": len(municipios),
            "produtos_observados": sorted(produtos),
            "publicacao_declarada_em": pub.isoformat(),
            "captura_declarada_em": coleta.isoformat(),
            "prova_publicacao_sha256_referenciada": e["prova_publicacao_sha256"],
            "layout_validado": "CONTRATO_CANDIDATO_FIXTURE_OU_ARQUIVO_NAO_HOMOLOGADO",
            "revisao_humana_pendente": True,
        })

    ordenados = sorted(periodos)
    if any((b[0] - a[0]).days != 7 for a, b in zip(ordenados, ordenados[1:])):
        raise ErroHomologacaoLPC("três semanas não são consecutivas")
    ausentes = sorted([
        {"municipio": nome, "produto": produto, "semanas_presentes": len(semanas)}
        for (nome, produto), semanas in cobertura.items()
        if len(semanas) != 3
    ], key=lambda x: (x["municipio"], x["produto"]))
    return {
        "status": "PRONTO_PARA_REVISAO_INDEPENDENTE_NAO_HOMOLOGADO",
        "numero_edicoes": 3,
        "semana_inicial": ordenados[0][0].isoformat(),
        "semana_final": ordenados[-1][1].isoformat(),
        "indice_url": indice["indice_url"],
        "indice_sha256": indice_sha256_esperado,
        "captura_indice_declarada_em": coleta_indice.isoformat(),
        "edicoes": sorted(auditorias, key=lambda x: x["semana_inicio"]),
        "lacunas_cobertura": ausentes,
        "semana_oficial": True,
        "semana_inferida_csv_mensal": False,
        "preco_amostral_diesel_revendido_nao_preco_frete": True,
        "layout_real_homologado": False,
        "datas_publicacao_independentemente_comprovadas": False,
        "permissoes_uso_comprovadas_por_avaliacao_juridica": False,
        "validacao_humana": "OBRIGATORIA",
        "precos_publicados": False,
        "dados_reais_persistidos": False,
        "publicavel": False,
    }
