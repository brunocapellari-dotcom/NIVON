"""Adaptacao segura dos dados existentes do NIVON ao painel operacional.

Orquestra SQLite MDF-e e leitura temporal parametrizada do BigQuery; nao cria
coletor, tabela, bucket nem contorna controle de acesso. Rede apenas opt-in.
"""
from __future__ import annotations

from typing import Any

from .consulta_analitica_bq import consultar, planejar_consulta
from .inteligencia_corredores import consultar_corredores
from .conciliacao_corredores_ferrovia import analisar_staging, quadro_intermodal
from .painel_operacional import ErroMotor, montar_painel
from .adaptadores_operacionais import adaptar_fretes_consolidados, ler_replay_ais_sqlite
from .ferrovia_painel_bq import consultar_ferrovia
from .maritimo_painel_bigquery import consultar_maritimo


def analisar_fontes(
    config: dict, *, as_of: str, executar_bigquery: bool = False,
    cliente_bigquery=None, leitor_bq=consultar, leitor_corredores=consultar_corredores,
    leitor_ferrovia=analisar_staging, conciliador_intermodal=quadro_intermodal,
    leitor_ferrovia_bq=consultar_ferrovia, cliente_ferrovia_bq=None, sdk_ferrovia_bq=None,
    leitor_maritimo_bq=consultar_maritimo, cliente_maritimo_bq=None, sdk_maritimo_bq=None,
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
    # SIADE e MDF-e sao reportados lado a lado. Nenhuma soma entre modais,
    # estimativa de transbordo ou volume unico e calculada aqui.
    staging = config.get("ferrovia_staging")
    ferrovia = config.get("ferrovia")
    config_bq_ferrovia = config.get("ferrovia_bigquery")
    if sum(x is not None for x in (staging, ferrovia, config_bq_ferrovia)) > 1:
        raise ErroMotor("escolha so uma fonte ferroviaria")
    ferrovia_bq_meta = None
    if config_bq_ferrovia is not None:
        if not isinstance(config_bq_ferrovia, dict):
            raise ErroMotor("configuracao ferroviaria BigQuery invalida")
        chaves_rail = ("projeto","dataset","competencia")
        if not all(isinstance(config_bq_ferrovia.get(k),str)
                   and config_bq_ferrovia[k] for k in chaves_rail):
            raise ErroMotor("projeto/dataset/competencia ferroviarios obrigatorios")
        resposta_ferrovia_bq = leitor_ferrovia_bq(
            projeto=config_bq_ferrovia["projeto"],
            dataset=config_bq_ferrovia["dataset"],
            competencia=config_bq_ferrovia["competencia"],
            uf_origem=config_bq_ferrovia.get("uf_origem","MT"),
            as_of=as_of,
            executar=executar_bigquery is True,
            cliente=cliente_ferrovia_bq, sdk=sdk_ferrovia_bq,
        )
        if not isinstance(resposta_ferrovia_bq,dict):
            raise ErroMotor("resposta ferroviaria BigQuery invalida")
        if executar_bigquery is True:
            if (resposta_ferrovia_bq.get("executado") is not True
                or resposta_ferrovia_bq.get("competencia")!=config_bq_ferrovia["competencia"]
                or not isinstance(resposta_ferrovia_bq.get("polos_ferroviarios"),list)):
                raise ErroMotor("consulta SIADE nao comprovada")
            ferrovia = resposta_ferrovia_bq
        ferrovia_bq_meta = {
            k:v for k,v in resposta_ferrovia_bq.items()
            if k not in ("polos_ferroviarios","mercadorias")
        }
    if staging is not None:
        if not isinstance(staging, dict) or not isinstance(staging.get("pasta"), str):
            raise ErroMotor("staging ferroviario invalido")
        ano = staging.get("ano")
        competencia = staging.get("competencia")
        uf = staging.get("uf_origem", "MT")
        if type(ano) is not int or not isinstance(competencia, str) or not isinstance(uf, str):
            raise ErroMotor("ano, competencia e UF ferroviarios invalidos")
        ferrovia = leitor_ferrovia(
            staging["pasta"], ano=ano, competencia=competencia,
            uf_origem=uf, limite=1000,
        )
    if ferrovia is not None and not isinstance(ferrovia, dict):
        raise ErroMotor("saida ferroviaria invalida")
    intermodal = None
    if ferrovia is not None:
        intermodal = (conciliador_intermodal(ferrovia, corredores) if corredores is not None
                      else {"estado": "DADOS_INSUFICIENTES",
                            "motivos": ["rodovia_ou_recorte_ausente"],
                            "dados": [], "sem_dados_nao_equivale_a_zero": True})
    series = list(manual_series)
    fontes = []
    if not all(isinstance(s, dict) for s in series):
        raise ErroMotor("serie manual malformada")
    chaves = {(s.get("classe"), s.get("serie_id")) for s in series}
    if len(chaves) != len(series):
        raise ErroMotor("series manuais duplicadas")
    fretes_meta = None
    fretes_input = config.get("fretes_consolidados")
    if fretes_input is not None:
        fretes_meta = adaptar_fretes_consolidados(fretes_input, as_of=as_of)
        for s in fretes_meta["series"]:
            chave = (s["classe"], s["serie_id"])
            if chave in chaves:
                raise ErroMotor("identidade de frete duplicada entre fontes")
            chaves.add(chave)
            series.append(s)
        if len(series) + len(config_queries) > 50:
            raise ErroMotor("excesso de series; particionar as ofertas")
    ais_config = config.get("replays_ais_sqlite", [])
    if not isinstance(ais_config, list) or len(ais_config) > 25:
        raise ErroMotor("maximo 25 replays AIS por lote")
    replays = []
    portos_ais = set()
    for entrada in ais_config:
        if not isinstance(entrada, dict) or any(
            not isinstance(entrada.get(k), str) or not entrada[k]
            for k in ("banco","porto_id","inicio","fim")
        ):
            raise ErroMotor("parametros de replay AIS incompletos")
        if entrada["porto_id"] in portos_ais:
            raise ErroMotor("porto repetido na lista de replay AIS")
        portos_ais.add(entrada["porto_id"])
        replays.append(ler_replay_ais_sqlite(
            banco=entrada["banco"], porto_id=entrada["porto_id"],
            inicio=entrada["inicio"], fim=entrada["fim"],
            as_of=as_of, limite=entrada.get("limite", 2000)
        ))
    # Mesmas tabelas maritimas canônicas do coletor GCS/BigQuery.
    # Nao alimente automaticamente o score AIS com programacao ou PortWatch.
    consultas_maritimas = config.get("consultas_maritimas_bigquery", [])
    if not isinstance(consultas_maritimas,list) or len(consultas_maritimas)>8:
        raise ErroMotor("maximo 8 consultas maritimas no mesmo lote")
    maritimo_bq=[]
    consultas_unicas=set()
    for consulta in consultas_maritimas:
        if not isinstance(consulta,dict) or any(
            not isinstance(consulta.get(k),str) or not consulta[k]
            for k in ("projeto","dataset","inicio","fim")
        ):
            raise ErroMotor("consulta maritima sem janela ou destino")
        id_ref=consulta.get("fonte") or consulta.get("passagem")
        chave=(consulta["projeto"],consulta["dataset"],consulta.get("fonte"),
               consulta.get("passagem"),consulta["inicio"],consulta["fim"])
        if not isinstance(id_ref,str) or chave in consultas_unicas:
            raise ErroMotor("fonte maritima ausente ou consulta duplicada")
        consultas_unicas.add(chave)
        resultado=leitor_maritimo_bq(
            projeto=consulta["projeto"],dataset=consulta["dataset"],
            inicio=consulta["inicio"],fim=consulta["fim"],as_of=as_of,
            fonte=consulta.get("fonte"),passagem=consulta.get("passagem"),
            executar=executar_bigquery is True,
            client=cliente_maritimo_bq,sdk=sdk_maritimo_bq,
            limite=consulta.get("limite",500),
        )
        if not isinstance(resultado,dict) or resultado.get("executado") is not (executar_bigquery is True):
            raise ErroMotor("leitura maritima nao respeitou contrato de execucao")
        if (resultado.get("fonte")!=consulta.get("fonte") or
            resultado.get("passagem")!=consulta.get("passagem")):
            raise ErroMotor("retorno do BigQuery maritimo com fonte divergente")
        maritimo_bq.append(resultado)
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
            classe=cfg["classe"],serie_id=cfg["serie_id"],
        )
        meta = {"fonte": cfg["fonte"], "classe": cfg["classe"],
                "serie_id": cfg["serie_id"], "executado": False}
        observacoes = []
        if executar_bigquery is True:
            resposta = leitor_bq(
                project_id=cfg["project_id"], dataset_id=cfg["dataset_id"],
                fonte=cfg["fonte"], inicio=cfg["inicio"], fim=cfg["fim"],
                as_of=as_of, limite=limite, executar=True, client=cliente_bigquery,
                classe=cfg["classe"],serie_id=cfg["serie_id"],
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
                if (resposta.get("classe") not in (None, cfg["classe"])
                    or resposta.get("serie_id") not in (None, cfg["serie_id"])):
                    raise ErroMotor("escopo de serie divergente no BigQuery")
                if not all(
                    isinstance(o, dict) and isinstance(o.get("campos"), dict)
                    and o["campos"].get("classe")==cfg["classe"]
                    and o["campos"].get("serie_id")==cfg["serie_id"]
                    for o in dados
                ):
                    raise ErroMotor("consulta retornou linhas de outra serie economica")
                observacoes = dados
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
    painel["ferrovia"] = ferrovia
    painel["fonte_ferrovia_bigquery"] = ferrovia_bq_meta
    painel["conciliacao_intermodal"] = intermodal
    painel["fretes_consolidados"] = (
        {k:v for k,v in fretes_meta.items() if k!="series"} if fretes_meta else None
    )
    painel["replays_ais"] = replays
    painel["fontes_maritimas_bigquery"] = maritimo_bq
    painel["fontes_bigquery"] = fontes
    painel["executou_bigquery"] = executar_bigquery is True and bool(
        config_queries or config_bq_ferrovia is not None or consultas_maritimas
    )
    return painel
