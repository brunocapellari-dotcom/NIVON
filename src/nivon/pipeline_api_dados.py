"""Ingestão OFFLINE de JSON PTAX/SIDRA em SQLite com proveniência por vintage.

Sem HTTP, deploy, agendamento, credenciais ou autorização implícita.
As-of é por DATA DE COLETA, não publication-time backtest.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .bcb_ptax import normalizar_ptax_odata
from .ptax_plano import planejar_consultas_ptax, ErroPlanoPTAX
from .sidra_pam import normalizar_pam_1612
from .registro_snapshots import registrar_snapshot, abrir_registro, ErroSnapshot

class ErroIngestaoAPI(ValueError):
    pass

_CAMPOS = {
    "BCB_PTAX":("moeda","referencia_data_hora_utc","competencia",
                "tipo_boletim","cotacao_compra_brl_por_moeda",
                "cotacao_venda_brl_por_moeda","paridade_compra","paridade_venda"),
    "IBGE_PAM":("municipio_ibge","ano_civil","variavel_sidra",
                "produto_categoria_c81","unidade_original","valor",
                "estado_valor","natureza"),
}
_VERSAO = {"BCB_PTAX":"PTAX_ODATA_1","IBGE_PAM":"SIDRA_1612_1"}
_FIELD_KEYS = {
    "BCB_PTAX":("moeda","referencia_data_hora_utc","tipo_boletim"),
    "IBGE_PAM":("municipio_ibge","ano_civil","variavel_sidra","produto_categoria_c81"),
}

def _no_duplicates(pairs):
    out={}
    for k,v in pairs:
        if k in out:
            raise ErroIngestaoAPI("JSON com chave repetida")
        out[k]=v
    return out

def _utc(valor):
    if not isinstance(valor,str):
        raise ErroIngestaoAPI("carimbo de coleta deve ser string ISO")
    try:
        d=datetime.fromisoformat(valor.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroIngestaoAPI("carimbo de coleta inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroIngestaoAPI("carimbo sem fuso")
    return d.astimezone(timezone.utc).isoformat()

def _normalizar_bytes(payload, dataset_id, plano, coleta):
    if not isinstance(payload,bytes) or not 1<=len(payload)<=2_000_000:
        raise ErroIngestaoAPI("payload JSON fora de limite de 2 MB")
    try:
        dados=json.loads(payload.decode("utf-8-sig"),object_pairs_hook=_no_duplicates)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ErroIngestaoAPI("JSON inválido") from exc
    if dataset_id=="BCB_PTAX":
        if not isinstance(plano,dict) or plano.get("dataset_id")!="BCB_PTAX":
            raise ErroIngestaoAPI("plano PTAX inválido")
        try:
            dia_inicio=datetime.fromisoformat(plano["inicio"]).date()
            dia_fim=datetime.fromisoformat(plano["fim"]).date()
            janela=(dia_fim-dia_inicio).days+1
            valido=planejar_consultas_ptax(moeda=plano["moeda"],
                       inicio=plano["inicio"],fim=plano["fim"],dias_janela=janela)
        except (KeyError,TypeError,ValueError,ErroPlanoPTAX) as exc:
            raise ErroIngestaoAPI("plano PTAX divergente") from exc
        if len(valido)!=1 or valido[0]!=plano:
            raise ErroIngestaoAPI("plano PTAX não foi produzido pelo planejador")
        norm=normalizar_ptax_odata(dados,moeda=plano["moeda"],
                                   coletado_em=coleta,consulta_url=plano["url"])
        obs=norm["observacoes"]
    elif dataset_id=="IBGE_PAM":
        norm=normalizar_pam_1612(payload,plano=plano,coletado_em=coleta)
        obs=norm["observacoes"]
    else:
        raise ErroIngestaoAPI("dataset não implementado no pipeline")
    campos=_CAMPOS[dataset_id]
    canonical=[]
    visto=set()
    for row in obs:
        item={k:row[k] for k in campos}
        chave=json.dumps([item[k] for k in _FIELD_KEYS[dataset_id]],
                         ensure_ascii=False,separators=(",",":"))
        if chave in visto:raise ErroIngestaoAPI("observação repetida")
        visto.add(chave)
        canonical.append((chave,json.dumps(item,ensure_ascii=False,sort_keys=True,
                                           separators=(",",":"),allow_nan=False)))
    if not canonical: raise ErroIngestaoAPI("sem dados; ausência nunca é zero")
    return canonical

def preparar_tabelas(db):
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
       CREATE TABLE IF NOT EXISTS nivon_observacoes_api (
         snapshot_id INTEGER NOT NULL REFERENCES nivon_snapshots(id),
         chave TEXT NOT NULL,
         observacao_json TEXT NOT NULL,
         PRIMARY KEY(snapshot_id,chave)
       );
       CREATE INDEX IF NOT EXISTS idx_nivon_api_chave ON nivon_observacoes_api(chave);
    """)

def ingerir_json_local(db:sqlite3.Connection, catalogo:dict, *, payload:bytes,
                       dataset_id:str, plano:dict, coletado_em:str,
                       tipo:str="SINTETICO", autorizacoes:frozenset[str]=frozenset(),
                       evidencia_direitos:str|None=None)->dict:
    """Registra observações canônicas e SHA. Direitos de coleta+storage em reais.

    Fonte e agendamento continuam inativos no catálogo; este módulo só consome
    bytes disponibilizados explicitamente por fonte aprovada ou fixture sintética.
    """
    if dataset_id not in _CAMPOS:
        raise ErroIngestaoAPI("dataset não suportado")
    if tipo == "REAL_AUTORIZADO":
        # Direitos informados pelo chamador não substituem a governança do catálogo.
        matches=[x for x in catalogo.get("datasets",[])
                 if x.get("id")==dataset_id]
        if (len(matches)!=1 or matches[0].get("enabled") is not True
                or matches[0].get("collection_authorized") is not True):
            raise PermissionError("registro real bloqueado: dataset desativado no catálogo")
    coleta=_utc(coletado_em)
    dados=_normalizar_bytes(payload,dataset_id,plano,coleta)
    sha=hashlib.sha256(payload).hexdigest()
    # Todo controle jurídico de dados reais é aplicado no ledger compartilhado.
    res=registrar_snapshot(
        db,catalogo,dataset_id=dataset_id,sha256=sha,tamanho=len(payload),
        mime="application/json",schema_versao=_VERSAO[dataset_id],
        coletado_em=coleta,publicacao=None,referencia=None,competencia=None,
        tipo=tipo,autorizacoes=autorizacoes,evidencia_direitos=evidencia_direitos,
    )
    preparar_tabelas(db)
    snap=db.execute(
        "SELECT id FROM nivon_snapshots WHERE dataset_id=? AND sha256=?",
        (dataset_id,sha)).fetchone()
    if snap is None:raise ErroIngestaoAPI("ledger sem snapshot")
    sid=snap["id"]
    with db:
        antes=dict(db.execute(
            "SELECT chave,observacao_json FROM nivon_observacoes_api WHERE snapshot_id=?",(sid,)))
        atual=dict(dados)
        if antes and antes!=atual:
            raise ErroIngestaoAPI("hash original reaparece com observações alteradas")
        if not antes:
            db.executemany(
                "INSERT INTO nivon_observacoes_api(snapshot_id,chave,observacao_json) VALUES(?,?,?)",
                [(sid,k,v) for k,v in dados])
    return {"dataset_id":dataset_id,"sha256":sha,"coleta":coleta,
            "linhas":len(dados),"nova_versao":res["nova_versao"],
            "nova_coleta":res["nova_coleta"],
            "estado":"NORMALIZADO_ARMAZENADO_LOCAL_SEM_AUTORIZACAO_DE_PUBLICAR",
            "publicacao":None}

def observar_asof_coleta(db:sqlite3.Connection, *, dataset_id:str,
                         corte_coleta:str, incluir_sinteticos:bool=False)->dict:
    """Reconstrói o que já fora COLETADO, sem inventar data de publicação."""
    if dataset_id not in _CAMPOS:raise ErroIngestaoAPI("dataset não suportado")
    corte=_utc(corte_coleta)
    if type(incluir_sinteticos) is not bool:
        raise ErroIngestaoAPI("incluir_sinteticos deve ser booleano")
    preparar_tabelas(db)
    registros=db.execute("""
       SELECT o.chave,o.observacao_json,s.sha256,s.tipo,c.coletado_utc
       FROM nivon_observacoes_api o
       JOIN nivon_snapshots s ON s.id=o.snapshot_id
       JOIN nivon_coletas c ON c.snapshot_id=s.id
       WHERE s.dataset_id=? AND c.coletado_utc<=?
       AND (?=1 OR s.tipo='REAL_AUTORIZADO')
       ORDER BY c.coletado_utc DESC,s.sha256 DESC LIMIT 10001
    """,(dataset_id,corte,int(incluir_sinteticos))).fetchall()
    if len(registros)>10000:
        raise ErroIngestaoAPI("janela as-of grande demais: exigir filtro por período")
    saida={}
    for row in registros:
        if row["chave"] in saida:
            anterior=saida[row["chave"]]
            if (anterior["primeira_visao_na_consulta"]==row["coletado_utc"] and
                    anterior["sha256"]!=row["sha256"] and
                    anterior["observacao"]!=json.loads(row["observacao_json"])):
                raise ErroIngestaoAPI("vintages conflitantes na mesma coleta, revisar origem")
        if row["chave"] not in saida:
            item=json.loads(row["observacao_json"])
            saida[row["chave"]]={"observacao":item,"sha256":row["sha256"],
                                  "primeira_visao_na_consulta":row["coletado_utc"],
                                  "tipo":row["tipo"]}
    return {"dataset_id":dataset_id,"corte_utc":corte,
            "linhas":len(saida),"registros":[saida[k] for k in sorted(saida)],
            "referencia_temporal":"COLETA_CONHECIDA_NAO_PUBLICACAO_OFICIAL",
            "apto_backtest_por_publicacao":False,"publicacao_comercial_permitida":False}
