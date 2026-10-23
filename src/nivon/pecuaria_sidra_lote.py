"""Pipeline em lote SIDRA: preflight -> normalizacao -> qualidade -> persistencia atomica.

Nenhuma rede. Exige contratos de mapeamento fornecidos pelo operador.
Dry-run e padrao: um teste sintetico aprovado NAO comprova origem oficial.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido, validar_fonte
from .pecuaria_sidra_abate import (
    normalizar_snapshot_sidra_abate, auditar_agregados_sidra_abate,
)
from .pecuaria_sidra_arquivo import (
    _conteudo, _validar_url, arquivar_lote_sidra_atomico,
    recuperar_pacote_sidra_offline,
)
from .pecuaria_sidra_vintages import historico_sidra_asof


def executar_lote_sidra_offline(*, capturas, corte_asof, status_fonte,
                               operacoes_autorizadas, banco=None,
                               persistir=False, coberturas=None):
    """Ate 24 pacotes 1092/1093/1094; tudo validado ANTES da transacao.

    Cada captura exige: especie, tabela_sidra, url_valores, url_metadados,
    bruto_valores, bruto_metadados, publicacao_declarada, coleta_declarada,
    dimensoes, totais e variaveis. Nenhuma informacao e completada por IA.
    """
    validar_fonte(status=status_fonte, operacao="LEITURA",
                  operacoes_autorizadas=operacoes_autorizadas)
    if "ARMAZENAMENTO" not in operacoes_autorizadas:
        raise PermissionError("ARMAZENAMENTO nao autorizado no contrato")
    if type(persistir) is not bool:
        raise DadoInvalido("persistir deve ser booleano")
    if persistir and banco is None:
        raise DadoInvalido("persistir requer arquivo SQLite explicito")
    if not isinstance(capturas, (tuple, list)) or not 1 <= len(capturas) <= 24:
        raise DadoInvalido("lote exige 1 a 24 capturas")
    if coberturas is not None and not isinstance(coberturas, Mapping):
        raise DadoInvalido("coberturas esperadas invalidas")
    obrigatorios = {"especie", "tabela_sidra", "url_valores", "url_metadados",
                    "bruto_valores", "bruto_metadados", "publicacao_declarada",
                    "coleta_declarada", "dimensoes", "totais", "variaveis"}
    snapshots, pacotes_persistencia = defaultdict(list), []
    contagens, relatorio_auditoria = {}, []
    capturas_validadas = []
    for idx, cap in enumerate(capturas):
        if not isinstance(cap, Mapping) or set(cap) != obrigatorios:
            raise DadoInvalido("captura sem contrato explicito ou campos inesperados")
        especie, tabela = cap["especie"], cap["tabela_sidra"]
        if TABELAS_SIDRA.get(especie) != tabela:
            raise DadoInvalido("tabela SIDRA incorreta no lote")
        _validar_url(cap["url_valores"], tabela=tabela, metadados=False)
        _validar_url(cap["url_metadados"], tabela=tabela, metadados=True)
        hash_meta = _conteudo(cap["bruto_metadados"], tipo="metadados",
                              max_bytes=1_000_000, tabela=tabela)
        _conteudo(cap["bruto_valores"], tipo="valores",
                  max_bytes=4_000_000, tabela=tabela)
        snap = normalizar_snapshot_sidra_abate(
            cap["bruto_valores"], especie=especie, tabela_sidra=tabela,
            dimensoes=cap["dimensoes"], totais=cap["totais"],
            variaveis=cap["variaveis"], publicacao=cap["publicacao_declarada"],
            coleta=cap["coleta_declarada"], status_fonte=status_fonte,
            operacoes_autorizadas=operacoes_autorizadas)
        snapshots[especie].append(snap)
        cobertura = None if coberturas is None else coberturas.get(especie)
        auditoria = auditar_agregados_sidra_abate(
            resultado=snap, cobertura_por_competencia=cobertura)
        relatorio_auditoria.extend(auditoria)
        contagens[idx] = {"especie": especie, "tabela_sidra": tabela,
                          "registros": len(snap["observacoes"]),
                          "ausentes_ou_inibidos": len(snap["linhas_indisponiveis"]),
                          "pares_incompletos": len(snap["pares_incompletos"]),
                          "sha256_valores": snap["origem_sha256"],
                          "sha256_metadados": hash_meta}
        capturas_validadas.append(cap)
        pacotes_persistencia.append({k: cap[k] for k in obrigatorios -
            {"dimensoes", "totais", "variaveis"}})
    historicos = {}
    for especie, snaps in snapshots.items():
        historicos[especie] = historico_sidra_asof(
            snapshots=snaps, especie=especie,
            tabela_sidra=TABELAS_SIDRA[especie], corte_asof=corte_asof)
    # TODAS as validacoes dos snapshots e vintages ocorrem antes da escrita.
    ids = []
    if persistir:
        gravacao = arquivar_lote_sidra_atomico(
            banco=banco, pacotes=pacotes_persistencia,
            status_fonte=status_fonte,
            operacoes_autorizadas=operacoes_autorizadas)
        ids = gravacao["ids"]
        for indice, id_captura in enumerate(ids):
            recuperado = recuperar_pacote_sidra_offline(
                banco=banco, id_captura=id_captura)
            if (recuperado["sha256_valores"] != contagens[indice]["sha256_valores"]
                or recuperado["sha256_metadados"] != contagens[indice]["sha256_metadados"]):
                raise DadoInvalido("divergencia na verificacao pos-gravacao")
    qualidade = {
        "n_capturas": len(capturas_validadas),
        "n_especies": len(historicos),
        "registros_normalizados": sum(x["registros"] for x in contagens.values()),
        "linhas_inibidas_ou_indisponiveis": sum(
            x["ausentes_ou_inibidos"] for x in contagens.values()),
        "total_revisoes_por_corte": sum(len(h["revisoes"]) for h in historicos.values()),
        "ufs_nao_verificadas": sum(
            a["status"] == "COBERTURA_NAO_VERIFICADA"
            for a in relatorio_auditoria),
        "divergencias_territoriais": sum(
            a["status"] in ("DIVERGENCIA_A_INVESTIGAR",
                            "COBERTURA_DIVERGENTE_SEM_IMPUTACAO")
            for a in relatorio_auditoria),
        "bloqueios": [
            "SEM_EVIDENCIA_HTTP_AUTENTICADA",
            "SEM_MAPEAMENTO_DIMENSIONAL_HOMOLOGADO",
            "SEM_DIREITOS_ATTESTADOS_EXTERNAMENTE",
            "SEM_VINTAGES_HISTORICOS_COMPROVADOS",
            "SEM_DADOS_REAIS_HOMOLOGADOS",
        ],
    }
    return {
        "status": "LOTE_OFFLINE_NAO_HOMOLOGADO",
        "corte_asof": corte_asof,
        "persistido": persistir,
        "persistencia_transacional": bool(persistir),
        "ids_capturas": ids,
        "capturas": list(contagens.values()),
        "qualidade": qualidade,
        "auditoria_territorial": relatorio_auditoria,
        "historicos": historicos,
        "coleta_real_executada": False,
        "previsao_homologada": False,
        "publicacao_permitida": False,
    }


def resumir_lote_sidra(resultado):
    """Saida JSON serializavel SEM expor linha bruta ou valores individuais."""
    if not isinstance(resultado, Mapping) or resultado.get("status") != "LOTE_OFFLINE_NAO_HOMOLOGADO":
        raise DadoInvalido("resultado nao e lote validado")
    return {"status": resultado["status"], "corte_asof": resultado["corte_asof"],
            "persistido": resultado["persistido"],
            "ids_capturas": resultado["ids_capturas"],
            "qualidade": resultado["qualidade"],
            "capturas": resultado["capturas"],
            "auditoria_territorial": resultado["auditoria_territorial"],
            "especies": {nome: {"registros_vigentes": len(hist["observacoes"]),
                                "censuras_vigentes": len(hist["censuras_vigentes"]),
                                "revisoes": len(hist["revisoes"]),
                                "amostra_real_homologada": False}
                         for nome, hist in resultado["historicos"].items()},
            "publicacao_permitida": False}
