"""Adaptacao segura dos dados existentes do NIVON ao painel operacional.

Orquestra SQLite MDF-e e leitura temporal parametrizada do BigQuery; nao cria
coletor, tabela, bucket nem contorna controle de acesso. Rede apenas opt-in.
"""
from __future__ import annotations

from typing import Any

from .consulta_analitica_bq import consultar, planejar_consulta
from .inteligencia_corredores import consultar_corredores
from .painel_operacional import ErroMotor, montar_painel


def analisar_fontes(
    config: dict, *, as_of: str, executar_bigquery: bool = False,
    cliente_bigquery=None, leitor_bq=consultar, leitor_corredores=consultar_corredores,
) -> dict:
    """Produz uma resposta independente por fonte, sem silenciar truncamentos."""
    if not isinstance(config, dict):
        raise ErroMotor("configuracao precisa ser objeto")
    config_queries = config.get("consultas_bigquery", [])
    if not isinstance(config_queries, list) or len(config_queries) > 10:
        raise ErroMotor("maximo 10 consultas BigQuery")
    manual_series = config.get("series", [])
    if not isinstance(manual_series, list):
        raise ErroMotor("series precisa ser lista")
    if len(manual_series) + len(config_queries) > 50:
        raise ErroMotor("excesso de series")
    corredor_cfg = config.get("corredores_sqlite")
    if config.get("corredores") is not None and corredor_cfg is not None:
        raise ErroMotor("escolha corredores ou corredores_sqlite, nao ambos")
    corredores = config.get("corredores")
    if corredor_cfg is not None:
        if not isinstance(corredor_cfg, dict):
            raise ErroMotor("configuracao de corredores invalida")
        if not all(isinstance(corredor_cfg.get(k), str) and corredor_cfg[k]
                   for k in ("banco", "recorte", "competencia")):
            raise ErroMotor("banco, recorte, competencia obrigatorios")
        corredores = leitor_corredores(
            corredor_cfg["banco"], recorte=corredor_cfg["recorte"],
            competencia=corredor_cfg["competencia"], limite=1000,
        )
    series = list(manual_series)
    fontes = []
    chaves = {(s.get("classe"), s.get("serie_id")) for s in series if isinstance(s, dict)}
    for cfg in config_queries:
        if not isinstance(cfg, dict):
            raise ErroMotor("consulta BigQuery invalida")
        requisitados = ("project_id", "dataset_id", "fonte", "inicio", "fim", "classe", "serie_id")
        if not all(isinstance(cfg.get(k), str) and cfg[k].strip() for k in requisitados):
            raise ErroMotor("parametros BigQuery incompletos")
        chave = (cfg["classe"], cfg["serie_id"])
        if chave in chaves:
            raise ErroMotor("serie duplicada no pacote")
        chaves.add(chave)
        limite = cfg.get("limite", 1000)
        # O preflight faz validacao de identificadores, datas, as-of, janela,
        # limite de linhas e bytes, inclusive quando nao ha acesso cloud.
        planejar_consulta(
            project_id=cfg["project_id"], dataset_id=cfg["dataset_id"],
            fonte=cfg["fonte"], inicio=cfg["inicio"], fim=cfg["fim"],
            as_of=as_of, limite=limite,
        )
        meta = {"fonte": cfg["fonte"], "classe": cfg["classe"],
                "serie_id": cfg["serie_id"], "executado": False}
        observacoes = []
        if executar_bigquery is True:
            resposta = leitor_bq(
                project_id=cfg["project_id"], dataset_id=cfg["dataset_id"],
                fonte=cfg["fonte"], inicio=cfg["inicio"], fim=cfg["fim"],
                as_of=as_of, limite=limite, executar=True, client=cliente_bigquery,
            )
            if not isinstance(resposta, dict) or resposta.get("executado") is not True:
                raise ErroMotor("consulta BigQuery nao comprovada")
            if resposta.get("fonte") != cfg["fonte"] or resposta.get("as_of") is None:
                raise ErroMotor("resposta BigQuery divergente")
            total = resposta.get("quantidade")
            dados = resposta.get("observacoes")
            if type(total) is not int or total < 0 or not isinstance(dados, list) or len(dados) != total:
                raise ErroMotor("contagem BigQuery inconsistente")
            if total >= limite:
                meta["status"] = "LIMITE_ATINGIDO_SERIE_NAO_AVALIADA"
            else:
                observacoes = [
                    o for o in dados
                    if isinstance(o, dict) and isinstance(o.get("campos"), dict)
                    and o["campos"].get("classe") == cfg["classe"]
                    and o["campos"].get("serie_id") == cfg["serie_id"]
                ]
                meta["status"] = "LIDA_NAO_HOMOLOGADA" if observacoes else "SEM_DADOS_COMPATIVEIS"
                meta["linhas_filtradas"] = len(observacoes)
            meta["executado"] = True
        else:
            meta["status"] = "PLANO_SEM_REDE"
        series.append({"classe": cfg["classe"], "serie_id": cfg["serie_id"],
                       "observacoes": observacoes})
        fontes.append(meta)
    painel = montar_painel({
        "corredores": corredores, "portos": config.get("portos", []), "series": series,
    }, as_of=as_of)
    painel["fontes_bigquery"] = fontes
    painel["executou_bigquery"] = executar_bigquery is True and bool(config_queries)
    return painel
