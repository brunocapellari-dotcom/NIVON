"""Ingestão offline e versionada de grades NASA POWER.

Retém coordenadas SOLICITADAS e coordenadas da grade devolvida; não disfarça
reanálise/grade como estação. Mesmo conteúdo (SHA) é idempotente, revisão
tem vintage independente. "Publicação" ausente não vira "coleta".
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from math import isfinite
from .nasa_power_diario import normalizar_power_diario, ErroPower
from .transacoes_sqlite import savepoint_atomico

class ErroGrade(ValueError):
    pass

def _utc(value):
    if not isinstance(value,str) or "T" not in value:raise ErroGrade("timestamp com fuso necessário")
    try:dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:raise ErroGrade("timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:raise ErroGrade("timestamp sem fuso")
    return dt.astimezone(timezone.utc).isoformat()

def abrir_grade(caminho=":memory:"):
    con=sqlite3.connect(str(caminho))
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS grade_edicao(
      dataset_id TEXT NOT NULL,consulta_sha256 TEXT NOT NULL,
      conteudo_sha256 TEXT NOT NULL,coordenada_lat REAL NOT NULL,
      coordenada_lon REAL NOT NULL,latitude_grade REAL NOT NULL,
      longitude_grade REAL NOT NULL,primeiro_dia TEXT NOT NULL,ultimo_dia TEXT NOT NULL,
      publicado_utc TEXT,classe TEXT NOT NULL,licenca_evidencia TEXT,
      PRIMARY KEY(dataset_id,consulta_sha256,conteudo_sha256));
    CREATE TABLE IF NOT EXISTS grade_captura(
      dataset_id TEXT NOT NULL,consulta_sha256 TEXT NOT NULL,
      conteudo_sha256 TEXT NOT NULL,coletado_utc TEXT NOT NULL,
      PRIMARY KEY(dataset_id,consulta_sha256,conteudo_sha256,coletado_utc),
      FOREIGN KEY(dataset_id,consulta_sha256,conteudo_sha256)
        REFERENCES grade_edicao(dataset_id,consulta_sha256,conteudo_sha256));
    CREATE TABLE IF NOT EXISTS grade_valor(
      dataset_id TEXT NOT NULL,consulta_sha256 TEXT NOT NULL,
      conteudo_sha256 TEXT NOT NULL,data_utc TEXT NOT NULL,
      parametro TEXT NOT NULL,valor REAL,unidade TEXT NOT NULL,
      PRIMARY KEY(dataset_id,consulta_sha256,conteudo_sha256,data_utc,parametro),
      FOREIGN KEY(dataset_id,consulta_sha256,conteudo_sha256)
        REFERENCES grade_edicao(dataset_id,consulta_sha256,conteudo_sha256));
    """)
    return con

def ingerir_power_local(db,*,bytes_json,plano,coletado_em,
                        publicado_em=None,classe="SINTETICO",
                        permissoes=frozenset(),licenca_evidencia=None):
    """O executor deve obter bytes legitimamente fora desta função.

    Revisão de direitos depende de evidência externa; o check de permissões
    apenas impede habilitação acidental de lotes reais.
    """
    if classe not in {"SINTETICO","REAL_AUTORIZADO"}:
        raise ErroGrade("classe inválida")
    if classe=="REAL_AUTORIZADO":
        if not {"COLETA","ARMAZENAMENTO"}.issubset(permissoes) or not isinstance(licenca_evidencia,str) or len(licenca_evidencia)<8:
            raise PermissionError("coleta e armazenamento requerem prova de permissão")
    elif permissoes or licenca_evidencia is not None:
        raise ErroGrade("fixture não pode reivindicar direitos reais")
    if not isinstance(bytes_json,bytes):
        raise ErroGrade("bytes JSON obrigatórios")
    sha=hashlib.sha256(bytes_json).hexdigest()
    result=normalizar_power_diario(bytes_json=bytes_json,plano=plano,sha256=sha,coletado_em=coletado_em)
    if result["numero_dias"]>366 or not result["registros"]:raise ErroGrade("janela fora de limite")
    utc=_utc(coletado_em)
    published=_utc(publicado_em) if publicado_em is not None else None
    if published is not None and published>utc:raise ErroGrade("publicação futura frente à coleta")
    from urllib.parse import parse_qs,urlsplit
    query=parse_qs(urlsplit(plano["url"]).query)
    try:lat=float(query["latitude"][0]);lon=float(query["longitude"][0])
    except (KeyError,ValueError,IndexError) as exc:raise ErroGrade("coordenada de plano ausente") from exc
    if not all(isfinite(x) for x in (lat,lon)) or abs(lat)>90 or abs(lon)>180:
        raise ErroGrade("coordenadas fora do globo")
    req_sha=hashlib.sha256(plano["url"].encode("utf-8")).hexdigest()
    ds="NASA_POWER_AG"
    values=[]
    from .nasa_power_diario import PARAMETROS
    for row in result["registros"]:
        for key,val in row["valores"].items():
            values.append((ds,req_sha,sha,row["data_utc"],key,val,PARAMETROS[key][0]))
    metadata=(ds,req_sha,sha,lat,lon,result["latitude_grade"],result["longitude_grade"],
              plano["inicio"],plano["fim"],
              published,classe,licenca_evidencia)
    with savepoint_atomico(db):
        old=db.execute("""SELECT * FROM grade_edicao WHERE dataset_id=?
             AND consulta_sha256=? AND conteudo_sha256=?""",(ds,req_sha,sha)).fetchone()
        if old is None:
            db.execute("INSERT INTO grade_edicao VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",metadata)
            db.executemany("INSERT INTO grade_valor VALUES (?,?,?,?,?,?,?)",values)
        else:
            keys=("dataset_id","consulta_sha256","conteudo_sha256",
                  "coordenada_lat","coordenada_lon","latitude_grade","longitude_grade",
                  "primeiro_dia","ultimo_dia",
                  "publicado_utc","classe","licenca_evidencia")
            if tuple(old[k] for k in keys)!=metadata:raise ErroGrade("mesmo hash com metadados conflitantes")
            prev=db.execute("""SELECT dataset_id,consulta_sha256,conteudo_sha256,data_utc,
                   parametro,valor,unidade FROM grade_valor
                   WHERE dataset_id=? AND consulta_sha256=? AND conteudo_sha256=?""",
                   (ds,req_sha,sha)).fetchall()
            def key(row):return (row[3],row[4])
            if {key(x):(x[5],x[6]) for x in prev}!={key(x):(x[5],x[6]) for x in values}:
                raise ErroGrade("hash duplicado com conteúdo diferente")
        exists=db.execute("""SELECT 1 FROM grade_captura WHERE dataset_id=?
              AND consulta_sha256=? AND conteudo_sha256=? AND coletado_utc=?""",
              (ds,req_sha,sha,utc)).fetchone()
        if exists is None:
            db.execute("INSERT INTO grade_captura VALUES (?,?,?,?)",(ds,req_sha,sha,utc))
    return {"dataset_id":ds,"consulta_sha256":req_sha,"conteudo_sha256":sha,
            "registros_diarios":result["numero_dias"],"valores":len(values),
            "nova_edicao":old is None,"nova_captura":exists is None,
            "publicacao_conhecida":published is not None,
            "apto_para_treino_temporal":False,
            "classe":classe,"coleta_ativa":False}

def grade_asof(db,*,consulta_sha256,parametro,inicio,fim,
               corte_publicacao,corte_coleta):
    """Somente edições publicadas e coletadas antes do corte especificado."""
    from .nasa_power_diario import PARAMETROS
    if parametro not in PARAMETROS or not isinstance(consulta_sha256,str) or not re.fullmatch(r"[0-9a-f]{64}",consulta_sha256):
        raise ErroGrade("consulta ou variável inválida")
    from datetime import date
    try:a=date.fromisoformat(inicio);b=date.fromisoformat(fim)
    except (ValueError,TypeError) as exc:raise ErroGrade("datas YYYY-MM-DD inválidas") from exc
    if a>b or (b-a).days>3660:raise ErroGrade("intervalo excessivo")
    pub=_utc(corte_publicacao);col=_utc(corte_coleta)
    rows=db.execute("""
       SELECT v.data_utc,v.valor,v.unidade,e.conteudo_sha256,e.publicado_utc,
           e.latitude_grade,e.longitude_grade,
           MIN(c.coletado_utc) AS primeira_coleta_utc
       FROM grade_valor v
       JOIN grade_edicao e ON e.dataset_id=v.dataset_id
          AND e.consulta_sha256=v.consulta_sha256 AND e.conteudo_sha256=v.conteudo_sha256
       JOIN grade_captura c ON c.dataset_id=e.dataset_id
          AND c.consulta_sha256=e.consulta_sha256 AND c.conteudo_sha256=e.conteudo_sha256
       WHERE v.dataset_id='NASA_POWER_AG' AND v.consulta_sha256=?
           AND v.parametro=? AND v.data_utc BETWEEN ? AND ?
           AND e.publicado_utc IS NOT NULL AND e.publicado_utc<=?
           AND c.coletado_utc<=?
       GROUP BY v.data_utc,e.conteudo_sha256
       ORDER BY v.data_utc,e.publicado_utc DESC,primeira_coleta_utc DESC
    """,(consulta_sha256,parametro,a.isoformat(),b.isoformat(),pub,col)).fetchall()
    selected={}
    for row in rows:
        item=dict(row);k=item["data_utc"]
        if k not in selected:selected[k]=item
        elif selected[k]["publicado_utc"]==item["publicado_utc"] and selected[k]["valor"]!=item["valor"]:
            raise ErroGrade("revisões conflitantes na mesma publicação")
    return [selected[k] for k in sorted(selected)]
