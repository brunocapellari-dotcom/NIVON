"""Consulta limitada à view ANTT/SIADE existente no BigQuery, sem escrita.

A view contém a revisão ATUAL do arquivo SIADE. Filtrar as_of não recria
automaticamente a revisão histórica que vigorava naquele instante; o resultado
nunca afirma point-in-time retroativo. Sem linha observada, não reporta zero.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re

from .antt_bigquery import DestinoBQ
from .corredores_bigquery import nome_view
from .transporte_multimodal import ErroTransporte

COMP = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")
POLO = re.compile(r"^[A-Z]{2}_[A-Z0-9_]{3,90}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_LINHAS = 1000
BYTES_LIMITE = 50_000_000


def _instante(value):
    if not isinstance(value, (str, datetime)):
        raise ErroTransporte("as_of exige instante timezone-aware")
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroTransporte("as_of invalido") from exc
    if dt.utcoffset() is None:
        raise ErroTransporte("as_of deve incluir timezone")
    return dt.astimezone(timezone.utc)


def plano_ferrovia(*, projeto, dataset, competencia, uf_origem="MT",
                   as_of, limite=MAX_LINHAS, max_bytes_billed=BYTES_LIMITE):
    destino = DestinoBQ(projeto, dataset)
    if not isinstance(competencia, str) or not COMP.fullmatch(competencia):
        raise ErroTransporte("competencia ANTT invalida")
    if not isinstance(uf_origem, str) or not re.fullmatch("[A-Z]{2}", uf_origem):
        raise ErroTransporte("UF de origem invalida")
    instante = _instante(as_of)
    inicio = date.fromisoformat(competencia + "-01")
    if inicio > instante.date():
        raise ErroTransporte("competencia futura frente ao as_of")
    if type(limite) is not int or not 1 <= limite <= MAX_LINHAS:
        raise ErroTransporte("limite de linhas invalido")
    if (type(max_bytes_billed) is not int or not
            10_000_000 <= max_bytes_billed <= BYTES_LIMITE):
        raise ErroTransporte("teto faturavel excedido")
    view = nome_view(destino)
    sql = (
        "SELECT competencia, data_referencia, polo_id, ferrovia, "
        "estacao_origem, uf_origem, mercadoria_antt, produto_normalizado, "
        "estacao_destino, uf_destino, toneladas_uteis, linhas_fonte, "
        "arquivos_sha256, data_coleta, fonte, abrangencia, "
        "match_geografico, transbordo_confirmado "
        f"FROM `{view}` "
        "WHERE data_referencia = @inicio AND competencia = @competencia "
        "AND uf_origem = @uf_origem AND data_coleta <= @as_of "
        "ORDER BY polo_id, mercadoria_antt, estacao_destino, uf_destino "
        "LIMIT @limite"
    )
    return {
        "estado":"PLANO_SEM_REDE", "projeto":projeto, "dataset":dataset,
        "view":view, "competencia":competencia, "uf_origem":uf_origem,
        "inicio":inicio, "as_of":instante, "limite":limite,
        "max_bytes_billed":max_bytes_billed, "sql":sql, "executado":False,
        "somar_com_rodovia_permitido":False, "historico_pit_reconstruido":False,
    }


def _positivo(raw, nome):
    try:
        d = Decimal(str(raw))
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ErroTransporte(nome + " invalido") from exc
    if not d.is_finite() or d < 0:
        raise ErroTransporte(nome + " negativo ou nao-finito")
    return d


def consultar_ferrovia(*, projeto, dataset, competencia, uf_origem="MT",
                       as_of, limite=MAX_LINHAS, max_bytes_billed=BYTES_LIMITE,
                       executar=False, cliente=None, sdk=None):
    plano=plano_ferrovia(
        projeto=projeto,dataset=dataset,competencia=competencia,
        uf_origem=uf_origem,as_of=as_of,limite=limite,
        max_bytes_billed=max_bytes_billed,
    )
    base={k:(v.isoformat() if isinstance(v,(date,datetime)) else v)
          for k,v in plano.items() if k!="sql"}
    if executar is not True:
        return base
    if sdk is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError as exc:
            raise ErroTransporte("SDK BigQuery nao instalado") from exc
    client=cliente if cliente is not None else sdk.Client(project=projeto)
    client.get_dataset(f"{projeto}.{dataset}")
    tabela=client.get_table(plano["view"])
    if getattr(tabela, "table_type", None)!="VIEW":
        raise ErroTransporte("view mensal SIADE inexistente ou tipo incorreto")
    cfg=sdk.QueryJobConfig(
        maximum_bytes_billed=max_bytes_billed,
        use_query_cache=True,
        query_parameters=[
            sdk.ScalarQueryParameter("inicio", "DATE", plano["inicio"]),
            sdk.ScalarQueryParameter("competencia", "STRING", competencia),
            sdk.ScalarQueryParameter("uf_origem", "STRING", uf_origem),
            sdk.ScalarQueryParameter("as_of", "TIMESTAMP", plano["as_of"]),
            sdk.ScalarQueryParameter("limite", "INT64", limite+1),
        ])
    registros=client.query(plano["sql"],job_config=cfg).result(timeout=90)
    agrupados={}
    fontes_sha=set()
    total_linhas=0
    n=0
    for entrada in registros:
        n+=1
        if n>limite:
            raise ErroTransporte("view SIADE truncada; refinar a competencia/UF")
        row=dict(entrada.items()) if hasattr(entrada,"items") else dict(entrada)
        if row.get("competencia")!=competencia or row.get("uf_origem")!=uf_origem:
            raise ErroTransporte("retorno fora de competencia ou UF")
        ref=row.get("data_referencia")
        if isinstance(ref, datetime):
            ref=ref.date()
        if ref!=plano["inicio"]:
            raise ErroTransporte("data de referencia divergente")
        coleta=row.get("data_coleta")
        if not isinstance(coleta,datetime) or coleta.utcoffset() is None or coleta.astimezone(timezone.utc)>plano["as_of"]:
            raise ErroTransporte("data coleta ausente/futura")
        if (row.get("fonte")!="ANTT_SIADE_ORIGEM_DESTINO"
            or row.get("abrangencia")!="FERROVIAS_FEDERAIS_CONCEDIDAS"
            or row.get("match_geografico")!="ESTACAO_NOME_EXATO_NAO_TERMINAL"
            or row.get("transbordo_confirmado") is not False):
            raise ErroTransporte("proveniencia/terminal nao comprovados")
        id_polo=row.get("polo_id")
        if not isinstance(id_polo,str) or not POLO.fullmatch(id_polo):
            raise ErroTransporte("polo desconhecido")
        mercadoria=row.get("mercadoria_antt")
        if not isinstance(mercadoria,str) or not mercadoria.strip() or len(mercadoria)>180:
            raise ErroTransporte("mercadoria ANTT sem nome original")
        produto=row.get("produto_normalizado")
        if produto is not None and (not isinstance(produto,str) or len(produto)>100):
            raise ErroTransporte("taxonomia mercadoria invalida")
        tu=_positivo(row.get("toneladas_uteis"),"toneladas uteis")
        linhas=row.get("linhas_fonte")
        if type(linhas) is not int or linhas <= 0:
            raise ErroTransporte("linhas_fonte invalidas")
        hashes=row.get("arquivos_sha256")
        if not isinstance(hashes,(list,tuple)) or not hashes or any(
            not isinstance(h,str) or not SHA.fullmatch(h) for h in hashes
        ):
            raise ErroTransporte("hashes SIADE ausentes")
        fontes_sha.update(hashes)
        total_linhas+=linhas
        polo=agrupados.setdefault(id_polo,{"polo":{"id":id_polo},
                "toneladas_ferroviarias":Decimal(0),"mercadorias":{},
                "linhas_fonte":0,"estacoes_origem":set()})
        polo["toneladas_ferroviarias"]+=tu
        polo["linhas_fonte"]+=linhas
        est=row.get("estacao_origem")
        if not isinstance(est,str) or not est:
            raise ErroTransporte("estacao de origem ausente")
        polo["estacoes_origem"].add(est)
        chave=(mercadoria,produto)
        polo["mercadorias"][chave]=polo["mercadorias"].get(chave,Decimal(0))+tu
    polos=[]
    for p in agrupados.values():
        polos.append({
            "polo":p["polo"],
            "toneladas_ferroviarias":format(p["toneladas_ferroviarias"],"f"),
            "mercadorias":[{"mercadoria_fonte":k[0],"produto_normalizado":k[1],
                "toneladas_ferroviarias":format(v,"f")}
                for k,v in sorted(p["mercadorias"].items(),key=lambda x:(-x[1],x[0][0]))],
            "linhas_fonte":p["linhas_fonte"],
            "estacoes_origem":sorted(p["estacoes_origem"]),
            "terminal_comprovado":False,
            "status":"POLO_CANDIDATO_NOME_EXATO_NAO_TERMINAL",
        })
    polos.sort(key=lambda x:(-Decimal(x["toneladas_ferroviarias"]),x["polo"]["id"]))
    return {
        **base, "estado":"REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA" if polos else "SEM_REGISTROS_NAO_SIGNIFICA_ZERO",
        "executado":True, "competencia":competencia,
        "qualidade":"TU_DECLARADA_FONTE_PRIMARIA_REQUER_CONCILIACAO",
        "fonte":"ANTT_SIADE_ORIGEM_DESTINO","linhas_view":n,
        "linhas_fonte":total_linhas, "arquivos_sha256":sorted(fontes_sha),
        "polos_ferroviarios":polos,"publicavel":False,
        "historico_pit_reconstruido":False, "transbordo_confirmado":False,
        "sem_registro_nao_equivale_a_zero":True,
        "observacao":"View atual por ano: nao permite reconstruir vintage historico por as_of.",
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: ANTT ferrovia view existente, RO e limitado")
    p.add_argument("--projeto",required=True); p.add_argument("--dataset",required=True)
    p.add_argument("--competencia",required=True); p.add_argument("--uf-origem",default="MT")
    p.add_argument("--as-of",required=True); p.add_argument("--executar",action="store_true")
    opts=p.parse_args(argv)
    out=consultar_ferrovia(projeto=opts.projeto,dataset=opts.dataset,
          competencia=opts.competencia,uf_origem=opts.uf_origem,
          as_of=opts.as_of,executar=opts.executar)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True,default=str))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
