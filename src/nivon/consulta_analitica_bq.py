"""Consulta interna NIVON: observações historizadas no BigQuery (somente leitura).

Contrato de consumo para motores de preços, tendências, clima e logística.
O filtro "as of" impede usar revisões publicadas depois da data de análise.
Nenhuma query sem limite de datas, nenhuma tabela fornecida pelo usuário.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .carga_bigquery_fontes import PROJECT, DATASET

FONTE = re.compile(r"^[A-Z][A-Z0-9_]{2,90}$")
SERIE = re.compile(r"^[A-Za-z0-9_:-]{3,150}$")
CLASSES_SERIE = frozenset({"FRETE_ANUNCIADO", "CBOT", "PRECO_FISICO"})
NATUREZAS = frozenset({"OBSERVADO","INFORMADO","ESTIMADO","PROJETADO","INFERIDO"})
LIMITE_MAXIMO = 1000
BYTES_MAXIMOS = 100_000_000


class ErroConsultaAnalitica(ValueError):
    pass


def _as_of(value):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt=value
    elif isinstance(value,str):
        try:
            dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        except ValueError as exc:
            raise ErroConsultaAnalitica("as_of invalido") from exc
    else:
        raise ErroConsultaAnalitica("as_of precisa timestamp ISO")
    if dt.utcoffset() is None or dt>datetime.now(timezone.utc)+timedelta(minutes=1):
        raise ErroConsultaAnalitica("as_of requer timezone e nao pode ser futuro")
    return dt.astimezone(timezone.utc)


def planejar_consulta(*,project_id,dataset_id,fonte,inicio,fim,
                     as_of=None,limite=500,max_bytes_billed=BYTES_MAXIMOS,
                     classe=None,serie_id=None):
    if not isinstance(project_id,str) or not PROJECT.fullmatch(project_id):
        raise ErroConsultaAnalitica("projeto nao autorizado")
    if not isinstance(dataset_id,str) or not DATASET.fullmatch(dataset_id):
        raise ErroConsultaAnalitica("dataset nao autorizado")
    if not isinstance(fonte,str) or not FONTE.fullmatch(fonte):
        raise ErroConsultaAnalitica("id de fonte/dataset invalido")
    try:
        de=date.fromisoformat(inicio)
        ate=date.fromisoformat(fim)
    except (TypeError,ValueError) as exc:
        raise ErroConsultaAnalitica("data inicial/final invalidas") from exc
    if de>ate or (ate-de).days>366 or ate>date.today()+timedelta(days=1):
        raise ErroConsultaAnalitica("janela fora do limite de 367 dias")
    if type(limite)!=int or not 1<=limite<=LIMITE_MAXIMO:
        raise ErroConsultaAnalitica("limite de linhas invalido")
    if type(max_bytes_billed)!=int or not 10_000_000<=max_bytes_billed<=BYTES_MAXIMOS:
        raise ErroConsultaAnalitica("limite maximo de leitura invalido")
    if (classe is None) != (serie_id is None):
        raise ErroConsultaAnalitica("classe e serie_id devem ser fornecidos juntos")
    if classe is not None and (
        classe not in CLASSES_SERIE or not isinstance(serie_id,str)
        or not SERIE.fullmatch(serie_id)
    ):
        raise ErroConsultaAnalitica("serie de mercado invalida")
    momento=_as_of(as_of)
    tabela=f"{project_id}.{dataset_id}.nivon_observacoes"
    sql=(
        f"WITH versoes AS ("
        f" SELECT dataset_id, identidade, fingerprint, data_referencia, competencia,"
        f" data_publicacao, data_coleta, natureza, valor, unidade, campos, snapshot_id,"
        f" ROW_NUMBER() OVER (PARTITION BY dataset_id, identidade"
        f" ORDER BY data_coleta DESC, fingerprint DESC) AS posicao"
        f" FROM `{tabela}`"
        f" WHERE dataset_id = @dataset_origem"
        f" AND data_referencia BETWEEN @inicio AND @fim"
        f" AND data_coleta <= @as_of"
        f" AND (data_publicacao IS NULL OR data_publicacao <= @as_of)"
        f") SELECT dataset_id, identidade, fingerprint, data_referencia, competencia,"
        f" data_publicacao, data_coleta, natureza, valor, unidade, campos, snapshot_id"
        f" FROM versoes WHERE posicao = 1"
        + (f" AND JSON_VALUE(campos, '$.classe') = @classe"
           f" AND JSON_VALUE(campos, '$.serie_id') = @serie_id"
           if classe is not None else "")
        + f" ORDER BY data_referencia ASC, identidade ASC LIMIT @limite"
    )
    return {"tabela":tabela,"fonte":fonte,"inicio":de,"fim":ate,
        "as_of":momento,"limite":limite,"max_bytes_billed":max_bytes_billed,
        "classe":classe,"serie_id":serie_id,
        "sql":sql,"executado":False}


def consultar(*,project_id,dataset_id,fonte,inicio,fim,as_of=None,limite=500,
             max_bytes_billed=BYTES_MAXIMOS,executar=False,client=None,
             classe=None,serie_id=None):
    plano=planejar_consulta(project_id=project_id,dataset_id=dataset_id,
        fonte=fonte,inicio=inicio,fim=fim,as_of=as_of,limite=limite,
        max_bytes_billed=max_bytes_billed,classe=classe,serie_id=serie_id)
    if executar is not True:
        return {k:v.isoformat() if isinstance(v,(date,datetime)) else v
             for k,v in plano.items() if k!="sql"} | {
             "status":"PLANO_SEM_REDE","sql_parametrizado":True}
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("instale nivon[gcp] e configure ADC/Workload Identity") from exc
    bq=client if client is not None else bigquery.Client(project=project_id)
    job_cfg=bigquery.QueryJobConfig(
        maximum_bytes_billed=max_bytes_billed,
        use_query_cache=True,
        query_parameters=[
            bigquery.ScalarQueryParameter("dataset_origem","STRING",fonte),
            bigquery.ScalarQueryParameter("inicio","DATE",plano["inicio"]),
            bigquery.ScalarQueryParameter("fim","DATE",plano["fim"]),
            bigquery.ScalarQueryParameter("as_of","TIMESTAMP",plano["as_of"]),
            bigquery.ScalarQueryParameter("limite","INT64",limite),
        ] + ([
            bigquery.ScalarQueryParameter("classe","STRING",classe),
            bigquery.ScalarQueryParameter("serie_id","STRING",serie_id),
        ] if classe is not None else []))
    rows=bq.query(plano["sql"],job_config=job_cfg).result(timeout=120)
    observacoes=[]
    for row in rows:
        if len(observacoes)>=limite:
            raise ErroConsultaAnalitica("consulta retornou mais linhas que o limite")
        obj=dict(row.items()) if hasattr(row,"items") else dict(row)
        campos=obj.get("campos")
        if isinstance(campos,str):
            try:
                campos=json.loads(campos)
            except (ValueError,UnicodeError) as exc:
                raise ErroConsultaAnalitica("JSON de campos quebrado no BigQuery") from exc
        if not isinstance(campos,dict):
            raise ErroConsultaAnalitica("campos de observacao nao sao objeto")
        if classe is not None and (
            campos.get("classe") != classe or campos.get("serie_id") != serie_id
        ):
            raise ErroConsultaAnalitica("resposta BigQuery fora da serie economica requerida")
        if obj.get("natureza") not in NATUREZAS or obj.get("dataset_id")!=fonte:
            raise ErroConsultaAnalitica("fonte ou natureza divergente no retorno")
        data_ref=obj.get("data_referencia")
        coletado=obj.get("data_coleta")
        if not isinstance(data_ref,(date,datetime)) or not isinstance(coletado,datetime):
            raise ErroConsultaAnalitica("datas canonicas ausentes no BigQuery")
        observado_em=coletado.astimezone(timezone.utc)
        if observado_em>plano["as_of"]:
            raise ErroConsultaAnalitica("observacao futura no retorno de historico")
        publicado=obj.get("data_publicacao")
        if publicado is not None and (not isinstance(publicado,datetime) or publicado>plano["as_of"]):
            raise ErroConsultaAnalitica("data de publicacao posterior ao as_of")
        observacoes.append({
            "dataset_id":fonte,"identidade":str(obj["identidade"]),
            "fingerprint":str(obj["fingerprint"]),
            "data_referencia":data_ref.isoformat(),
            "competencia":obj.get("competencia"),
            "data_publicacao":publicado.isoformat() if publicado else None,
            "data_coleta":observado_em.isoformat(),
            "valor":str(obj["valor"]) if obj.get("valor") is not None else None,
            "unidade":obj.get("unidade"),"natureza":obj["natureza"],
            "campos":campos,"snapshot_id":str(obj["snapshot_id"]),
        })
    return {"fonte":fonte,"inicio":inicio,"fim":fim,
        "as_of":plano["as_of"].isoformat(),"quantidade":len(observacoes),
        "observacoes":observacoes,"status":"DADOS_INTERNOS_NAO_HOMOLOGADOS_EDITORIALMENTE",
        "limite":limite,"executado":True,
        "sem_resultados":len(observacoes)==0,
        "classe":classe,"serie_id":serie_id}


def main(argv=None):
    p=argparse.ArgumentParser(description="Consultar series NIVON armazenadas no BigQuery")
    for k in ("projeto","dataset","fonte","inicio","fim"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--as-of")
    p.add_argument("--limite",type=int,default=500)
    p.add_argument("--executar",action="store_true")
    a=p.parse_args(argv)
    out=consultar(project_id=a.projeto,dataset_id=a.dataset,fonte=a.fonte,
        inicio=a.inicio,fim=a.fim,as_of=a.as_of,limite=a.limite,executar=a.executar)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
