"""Leitura do histórico marítimo canônico NIVON no BigQuery, sem escrita.

O catálogo atual guarda revisões de PROGRAMAÇÃO e fluxos PortWatch. Não
contém, neste contrato, port calls/DUV confirmados ou trajetórias AIS com
geocercas suficientes para computar filas. Nunca converter revisões/fluxos
em navios operados, tonelagem realizada, ETA ou transbordos.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re

from .maritimo_bigquery import validar_destino

FONTES_LINEUP = frozenset({
    "suape", "imbituba", "santarem_cdp", "vila_conde_cdp"
})
PASSAGENS = frozenset({"hormuz", "bab_el_mandeb", "suez", "panama"})
HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_ROWS = 1000
MAX_DAYS = 35
MAX_BYTES_BILLED = 50_000_000


class ErroPainelMaritimo(ValueError):
    pass


def _instante(x):
    try:
        parsed = x if isinstance(x,datetime) else datetime.fromisoformat(
            x.replace("Z","+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ErroPainelMaritimo("as_of ou coleta invalida") from exc
    if parsed.utcoffset() is None:
        raise ErroPainelMaritimo("instantes exigem timezone")
    return parsed.astimezone(timezone.utc)


def _data(x):
    try:
        return date.fromisoformat(x)
    except (TypeError, ValueError) as exc:
        raise ErroPainelMaritimo("data ISO obrigatoria") from exc


def planejar_maritimo(*, projeto, dataset, inicio, fim, as_of,
                      fonte=None, passagem=None, limite=MAX_ROWS,
                      max_bytes_billed=MAX_BYTES_BILLED):
    validar_destino(projeto,dataset)
    if (fonte is None)==(passagem is None):
        raise ErroPainelMaritimo("escolher fonte lineup OU passagem PortWatch")
    if fonte is not None and fonte not in FONTES_LINEUP:
        raise ErroPainelMaritimo("fonte lineup nao suportada")
    if passagem is not None and passagem not in PASSAGENS:
        raise ErroPainelMaritimo("passagem PortWatch nao suportada")
    begin,end,cut=_data(inicio),_data(fim),_instante(as_of)
    if begin>end or (end-begin).days>MAX_DAYS or begin>cut.date():
        raise ErroPainelMaritimo("janela invalida ou superior a 35 dias")
    if type(limite) is not int or not 1<=limite<=MAX_ROWS:
        raise ErroPainelMaritimo("limite de linhas invalido")
    if (type(max_bytes_billed) is not int or not
            10_000_000<=max_bytes_billed<=MAX_BYTES_BILLED):
        raise ErroPainelMaritimo("teto maximo de consulta excedido")
    physical="maritimo_escalas_revisoes" if fonte is not None else "maritimo_fluxos_passagens"
    selected=(
        "fonte, escala_id, revisao_sha256, data_referencia, competencia, "
        "data_publicacao, data_coleta, natureza, situacao, publicavel, payload_json"
        if fonte is not None else
        "fonte, passagem, revisao_sha256, data_referencia, data_coleta, "
        "transitos_ais, volume_transito_estimado_t, payload_json"
    )
    where=("fonte = @origem" if fonte is not None else
           "fonte = 'FMI_PORTWATCH' AND passagem = @origem")
    sql=(
        f"SELECT {selected} FROM `{projeto}.{dataset}.{physical}` "
        f"WHERE data_referencia BETWEEN @inicio AND @fim AND {where} "
        "AND data_coleta <= @as_of "
        + ("AND (data_publicacao IS NULL OR data_publicacao <= @as_of) " if fonte else "")
        + "ORDER BY data_referencia, data_coleta, revisao_sha256 LIMIT @limite"
    )
    return {
        "estado":"PLANO_SEM_REDE","tabela":f"{projeto}.{dataset}.{physical}",
        "projeto":projeto,"dataset":dataset,
        "fonte":fonte,"passagem":passagem,
        "inicio":begin,"fim":end,"as_of":cut,
        "limite":limite,"max_bytes_billed":max_bytes_billed,"sql":sql,
        "executado":False,"publicavel":False,
    }


def _dec_nonnegative(v, nome):
    try:
        d=Decimal(str(v))
    except (TypeError,InvalidOperation,ValueError) as exc:
        raise ErroPainelMaritimo(nome+" invalido") from exc
    if not d.is_finite() or d<0:
        raise ErroPainelMaritimo(nome+" negativo ou nao-finito")
    return d


def _payload_str(row):
    raw=row.get("payload_json")
    if not isinstance(raw,str) or not 1<=len(raw)<=2_000_000:
        raise ErroPainelMaritimo("payload ausente/excessivo")
    try:
        doc=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ErroPainelMaritimo("JSON do lote invalido") from exc
    if not isinstance(doc,dict):
        raise ErroPainelMaritimo("payload deve ser objeto")
    return doc


def consultar_maritimo(*, projeto, dataset, inicio, fim, as_of,
                       fonte=None, passagem=None, limite=MAX_ROWS,
                       max_bytes_billed=MAX_BYTES_BILLED,
                       executar=False, client=None, sdk=None):
    plan=planejar_maritimo(projeto=projeto,dataset=dataset,inicio=inicio,
          fim=fim,as_of=as_of,fonte=fonte,passagem=passagem,limite=limite,
          max_bytes_billed=max_bytes_billed)
    base={k:v.isoformat() if isinstance(v,(date,datetime)) else v
          for k,v in plan.items() if k!="sql"}
    if executar is not True:
        return base
    if sdk is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError as exc:
            raise ErroPainelMaritimo("SDK google-cloud-bigquery nao instalado") from exc
    cli=client if client is not None else sdk.Client(project=projeto)
    cli.get_dataset(f"{projeto}.{dataset}")
    obj=cli.get_table(plan["tabela"])
    if getattr(obj,"table_type",None)!="TABLE":
        raise ErroPainelMaritimo("tabela historica maritima ausente ou tipo divergente")
    part=getattr(obj,"time_partitioning",None)
    if getattr(part,"field",None)!="data_referencia":
        raise ErroPainelMaritimo("tabela nao particionada pela data de referencia")
    params=[
        sdk.ScalarQueryParameter("inicio","DATE",plan["inicio"]),
        sdk.ScalarQueryParameter("fim","DATE",plan["fim"]),
        sdk.ScalarQueryParameter("as_of","TIMESTAMP",plan["as_of"]),
        sdk.ScalarQueryParameter("origem","STRING",fonte or passagem),
        sdk.ScalarQueryParameter("limite","INT64",limite+1),
    ]
    cfg=sdk.QueryJobConfig(maximum_bytes_billed=max_bytes_billed,
                           use_query_cache=True,query_parameters=params)
    rows=list(cli.query(plan["sql"],job_config=cfg).result(timeout=90))
    if len(rows)>limite:
        raise ErroPainelMaritimo("historico truncado; particionar recorte")
    if fonte is not None:
        ids=set()
        hashes=set()
        estados=Counter()
        naturezas=Counter()
        bloqueados=0
        for raw in rows:
            row=dict(raw.items()) if hasattr(raw,"items") else dict(raw)
            if row.get("fonte")!=fonte:
                raise ErroPainelMaritimo("fonte retornada difere do solicitado")
            if not isinstance(row.get("escala_id"),str) or not row["escala_id"].strip():
                raise ErroPainelMaritimo("identidade de programacao ausente")
            sha=row.get("revisao_sha256")
            if not isinstance(sha,str) or not HASH.fullmatch(sha):
                raise ErroPainelMaritimo("hash de revisao nao verificavel")
            ref=row.get("data_referencia")
            if isinstance(ref,datetime):ref=ref.date()
            if not isinstance(ref,date) or not plan["inicio"]<=ref<=plan["fim"]:
                raise ErroPainelMaritimo("referencia maritima fora da particao")
            coleta=row.get("data_coleta")
            if not isinstance(coleta,datetime) or _instante(coleta)>plan["as_of"]:
                raise ErroPainelMaritimo("coleta fora do as_of")
            publicacao=row.get("data_publicacao")
            if publicacao is not None and (
                not isinstance(publicacao,datetime) or _instante(publicacao)>plan["as_of"]
            ):
                raise ErroPainelMaritimo("publicacao posterior ao as_of")
            if type(row.get("publicavel")) is not bool:
                raise ErroPainelMaritimo("revisao sem gate de publicacao")
            _payload_str(row)
            natureza=row.get("natureza")
            estado=row.get("situacao")
            if not isinstance(natureza,str) or not natureza or not isinstance(estado,str) or not estado:
                raise ErroPainelMaritimo("revisao sem natureza/situacao")
            ids.add(row["escala_id"]);hashes.add(sha)
            estados[estado]+=1;naturezas[natureza]+=1
            bloqueados+=not row["publicavel"]
        return {**base,"executado":True,
            "estado":"PROGRAMACAO_HISTORICA_READONLY_SHADOW" if rows else "SEM_REVISOES_NAO_EQUIVALE_A_ZERO",
            "revisoes_visiveis":len(rows),"ids_programacao_distintos":len(ids),
            "status_revisoes":dict(sorted(estados.items())),
            "naturezas_revisoes":dict(sorted(naturezas.items())),
            "revisoes_bloqueadas_fonte":bloqueados,
            "hashes_revisoes_distintos":len(hashes),
            "hashes_originais_verificados_no_gcs":False,
            "vinculo_duv_confirmado":False,"navios_operados_confirmados":None,
            "toneladas_realizadas":None,"navios_em_fila_ais":None,
            "previsao_eta":None,"publicavel":False,
            "nota":"Contagem de IDs de programacao nao equivale a navios/DUV realizados."}
    por_dia = {}
    for raw in rows:
        row=dict(raw.items()) if hasattr(raw,"items") else dict(raw)
        if row.get("fonte")!="FMI_PORTWATCH" or row.get("passagem")!=passagem:
            raise ErroPainelMaritimo("PortWatch retornou fonte/passagem divergentes")
        ref=row.get("data_referencia")
        if isinstance(ref,datetime):ref=ref.date()
        if not isinstance(ref,date) or not plan["inicio"]<=ref<=plan["fim"]:
            raise ErroPainelMaritimo("data de PortWatch fora do recorte")
        coleta=row.get("data_coleta")
        if not isinstance(coleta,datetime) or _instante(coleta)>plan["as_of"]:
            raise ErroPainelMaritimo("PortWatch de data futura")
        sha=row.get("revisao_sha256")
        if not isinstance(sha,str) or not HASH.fullmatch(sha):
            raise ErroPainelMaritimo("hash de fluxo invalido")
        payload=_payload_str(row)
        if payload.get("volume_realizado_t") is not None or payload.get("natureza_volume_estimado")!="ESTIMADO_MODELO_FMI":
            raise ErroPainelMaritimo("PortWatch nao e comprovante de carga realizada")
        count=row.get("transitos_ais")
        if type(count) is not int or count<0:
            raise ErroPainelMaritimo("transitos PortWatch invalidos")
        vol=row.get("volume_transito_estimado_t")
        volume=None if vol is None else _dec_nonnegative(vol,"volume estimado PortWatch")
        at=_instante(coleta)
        # Uma data pode conter multiplas revisoes, jamais somar vintages.
        k=ref.isoformat()
        anterior=por_dia.get(k)
        registro={"at":at,"sha":sha,"transitos":count,"volume":volume}
        if anterior is None or (at,sha)>(anterior["at"],anterior["sha"]):
            por_dia[k]=registro
    total_volume=None
    if por_dia and all(v["volume"] is not None for v in por_dia.values()):
        total_volume=format(sum((v["volume"] for v in por_dia.values()),Decimal("0")),"f")
    total_transitos=sum(v["transitos"] for v in por_dia.values()) if por_dia else None
    return {**base,"executado":True,
        "estado":"PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW" if rows else "SEM_DADOS_NAO_EQUIVALE_A_ZERO",
        "revisoes_visiveis":len(rows),"dias_distintos":len(por_dia),
        "vintages_descartadas_para_soma":len(rows)-len(por_dia),
        "transitos_ais_reportados":total_transitos,
        "volume_estimado_modelo_t":total_volume,
        "volume_movimentado_real":None,"transitos_portuarios_confirmados":None,
        "publicavel":False,
        "nota":"PortWatch nao identifica port call, carga realizada nem trading."}
