"""Histórico de medições ANA/INMET, preservando edições e datas as-of.

Somente recebe dados JÁ normalizados de fontes autorizadas. Não faz rede,
decodificação de payload remoto, publicação ou execução em background.
"""
from __future__ import annotations
import re
import sqlite3
from dataclasses import dataclass
from datetime import date,datetime,timezone
from math import isfinite
from typing import Iterable

class ErroAmbiental(ValueError):
    pass

METRICAS={
    "ANA_HIDRO":{"COTA_CM":"CM","VAZAO_M3_S":"M3_S","CHUVA_DIA_MM":"MM"},
    "INMET_ESTACOES":{"CHUVA_DIA_MM":"MM","TMIN_C":"CELSIUS",
        "TMAX_C":"CELSIUS","UMIDADE_REL_PCT":"PERCENTUAL","VENTO_MS":"M_S"},
}
_SHA=re.compile(r"[0-9a-f]{64}\Z")
_ESTACAO=re.compile(r"[A-Z0-9_-]{3,32}\Z")

def _instante(v,nome):
    if not isinstance(v,str) or "T" not in v:
        raise ErroAmbiental(nome+": data/hora com fuso obrigatórias")
    try:
        d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroAmbiental(nome+": data/hora inválidas") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroAmbiental(nome+": fuso obrigatório")
    return d.astimezone(timezone.utc).isoformat()

def _dia(v):
    try:return date.fromisoformat(v).isoformat()
    except (ValueError,TypeError) as exc:raise ErroAmbiental("dia YYYY-MM-DD obrigatório") from exc

@dataclass(frozen=True)
class Ambiental:
    dataset_id:str
    estacao_id:str
    data_local:str
    metrica:str
    valor:float
    unidade:str
    natureza:str
    origem_sha256:str
    referencia:str
    publicado_em:str|None
    coletado_em:str
    evidencia:str

    def __post_init__(self):
        if self.dataset_id not in METRICAS or METRICAS[self.dataset_id].get(self.metrica)!=self.unidade:
            raise ErroAmbiental("dataset/métrica/unidade incompatíveis")
        if not isinstance(self.estacao_id,str) or not _ESTACAO.fullmatch(self.estacao_id):
            raise ErroAmbiental("estação não canônica")
        if _dia(self.referencia)<_dia(self.data_local):
            raise ErroAmbiental("referência anterior ao dia observado")
        if self.natureza not in {"OBSERVADO","INFORMADO","ESTIMADO","PROJETADO"}:
            raise ErroAmbiental("natureza inválida")
        if type(self.valor) not in (int,float) or not isfinite(self.valor):
            raise ErroAmbiental("nulo, booleano ou número não finito")
        if self.metrica in {"CHUVA_DIA_MM","VAZAO_M3_S","VENTO_MS"} and self.valor<0:
            raise ErroAmbiental("valor físico negativo")
        if self.metrica=="UMIDADE_REL_PCT" and not 0<=self.valor<=100:
            raise ErroAmbiental("umidade fora de 0 a 100")
        if self.metrica in {"TMIN_C","TMAX_C"} and not -90<=self.valor<=70:
            raise ErroAmbiental("temperatura fisicamente inválida")
        if not isinstance(self.origem_sha256,str) or not _SHA.fullmatch(self.origem_sha256):
            raise ErroAmbiental("SHA-256 obrigatório")
        if not isinstance(self.evidencia,str) or not self.evidencia.strip() or len(self.evidencia)>500:
            raise ErroAmbiental("evidência obrigatória")
        c=_instante(self.coletado_em,"coleta")
        if self.publicado_em is not None and _instante(self.publicado_em,"publicação")>c:
            raise ErroAmbiental("publicação posterior à coleta")

def abrir_ambiental(caminho=":memory:"):
    db=sqlite3.connect(str(caminho),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS ambiental_edicoes(
        dataset_id TEXT NOT NULL,sha256 TEXT NOT NULL,
        publicado_utc TEXT,referencia TEXT NOT NULL,evidencia TEXT NOT NULL,
        classe_registro TEXT NOT NULL CHECK(classe_registro IN ('SINTETICO','REAL_AUTORIZADO')),
        direitos_ref TEXT,PRIMARY KEY(dataset_id,sha256));
      CREATE TABLE IF NOT EXISTS ambiental_coletas(
        dataset_id TEXT NOT NULL,sha256 TEXT NOT NULL,coletado_utc TEXT NOT NULL,
        PRIMARY KEY(dataset_id,sha256,coletado_utc),
        FOREIGN KEY(dataset_id,sha256) REFERENCES ambiental_edicoes(dataset_id,sha256));
      CREATE TABLE IF NOT EXISTS ambiental_medidas(
        dataset_id TEXT NOT NULL,sha256 TEXT NOT NULL,estacao_id TEXT NOT NULL,
        data_local TEXT NOT NULL,metrica TEXT NOT NULL,valor REAL NOT NULL,
        unidade TEXT NOT NULL,natureza TEXT NOT NULL,
        PRIMARY KEY(dataset_id,sha256,estacao_id,data_local,metrica),
        FOREIGN KEY(dataset_id,sha256) REFERENCES ambiental_edicoes(dataset_id,sha256));
      CREATE INDEX IF NOT EXISTS idx_ambiental_medidas
        ON ambiental_medidas(dataset_id,estacao_id,metrica,data_local);
    """)
    return db

def salvar_lote(db,observacoes:Iterable[Ambiental],*,classe_registro="SINTETICO",
               autorizacoes:frozenset[str]=frozenset(),direitos_ref=None):
    rows=list(observacoes)
    if not 1<=len(rows)<=50000 or any(not isinstance(r,Ambiental) for r in rows):
        raise ErroAmbiental("lote ausente, excessivo ou inválido")
    if classe_registro not in {"SINTETICO","REAL_AUTORIZADO"}:
        raise ErroAmbiental("classe de registro inválida")
    if classe_registro=="REAL_AUTORIZADO":
        if not {"COLETA","ARMAZENAMENTO"}.issubset(autorizacoes) or not isinstance(direitos_ref,str) or len(direitos_ref.strip())<6:
            raise PermissionError("direitos por operação e evidência necessários")
    elif autorizacoes or direitos_ref is not None:
        raise ErroAmbiental("fixture não pode declarar direitos reais")
    first=rows[0]
    head=(first.dataset_id,first.origem_sha256,
          _instante(first.publicado_em,"publicação") if first.publicado_em else None,
          first.referencia,first.evidencia,classe_registro,direitos_ref)
    coleta=_instante(first.coletado_em,"coleta")
    seen=set()
    for r in rows:
        edition=(r.dataset_id,r.origem_sha256,
                 _instante(r.publicado_em,"publicação") if r.publicado_em else None,
                 r.referencia,r.evidencia,classe_registro,direitos_ref)
        if edition!=head or _instante(r.coletado_em,"coleta")!=coleta:
            raise ErroAmbiental("edições e datas misturadas")
        key=(r.estacao_id,r.data_local,r.metrica)
        if key in seen:raise ErroAmbiental("duplicata na mesma edição")
        seen.add(key)
    did,sha,_,_,_,_,_=head
    with db:
        old=db.execute("SELECT * FROM ambiental_edicoes WHERE dataset_id=? AND sha256=?",(did,sha)).fetchone()
        if old is None:
            db.execute("INSERT INTO ambiental_edicoes VALUES (?,?,?,?,?,?,?)",head)
            db.executemany("INSERT INTO ambiental_medidas VALUES (?,?,?,?,?,?,?,?)",[
                (r.dataset_id,r.origem_sha256,r.estacao_id,r.data_local,r.metrica,
                 float(r.valor),r.unidade,r.natureza) for r in rows])
        else:
            keys=("dataset_id","sha256","publicado_utc","referencia","evidencia","classe_registro","direitos_ref")
            if tuple(old[k] for k in keys)!=head:
                raise ErroAmbiental("mesmo SHA com metadados conflitantes")
            prev=db.execute("SELECT estacao_id,data_local,metrica,valor,unidade,natureza FROM ambiental_medidas WHERE dataset_id=? AND sha256=?",(did,sha)).fetchall()
            oldmap={(r[0],r[1],r[2]):(r[3],r[4],r[5]) for r in prev}
            newmap={(r.estacao_id,r.data_local,r.metrica):(float(r.valor),r.unidade,r.natureza) for r in rows}
            if oldmap!=newmap:raise ErroAmbiental("mesmo SHA com medidas diferentes")
        exists=db.execute("SELECT 1 FROM ambiental_coletas WHERE dataset_id=? AND sha256=? AND coletado_utc=?",(did,sha,coleta)).fetchone()
        if exists is None:
            db.execute("INSERT INTO ambiental_coletas VALUES (?,?,?)",(did,sha,coleta))
    return {"dataset_id":did,"sha256":sha,"observacoes":len(rows),
            "nova_edicao":old is None,"nova_coleta":exists is None,
            "natureza":"MEDIDAS_AMBIENTAIS_OFFLINE"}

def consultar_asof(db,*,dataset_id,estacao_id,metrica,inicio,fim,corte_publicacao,corte_coleta):
    if dataset_id not in METRICAS or metrica not in METRICAS[dataset_id]:
        raise ErroAmbiental("dataset/métrica inválidos")
    if not isinstance(estacao_id,str) or not _ESTACAO.fullmatch(estacao_id):
        raise ErroAmbiental("estação inválida")
    i,f=_dia(inicio),_dia(fim)
    if i>f or (date.fromisoformat(f)-date.fromisoformat(i)).days>3660:
        raise ErroAmbiental("intervalo inválido")
    pub,cole=_instante(corte_publicacao,"corte publicação"),_instante(corte_coleta,"corte coleta")
    rows=db.execute("""
      SELECT m.dataset_id,m.estacao_id,m.metrica,m.data_local,m.valor,m.unidade,m.natureza,
             e.sha256,e.publicado_utc,e.referencia,MIN(c.coletado_utc) AS visto_utc
      FROM ambiental_medidas m
      JOIN ambiental_edicoes e ON e.dataset_id=m.dataset_id AND e.sha256=m.sha256
      JOIN ambiental_coletas c ON c.dataset_id=e.dataset_id AND c.sha256=e.sha256
      WHERE m.dataset_id=? AND m.estacao_id=? AND m.metrica=?
        AND m.data_local BETWEEN ? AND ?
        AND e.publicado_utc IS NOT NULL AND e.publicado_utc<=?
        AND c.coletado_utc<=?
      GROUP BY m.data_local,e.sha256
      ORDER BY m.data_local,e.publicado_utc DESC,visto_utc DESC
    """,(dataset_id,estacao_id,metrica,i,f,pub,cole)).fetchall()
    latest={}
    for row in rows:
        obj=dict(row);d=obj["data_local"]
        if d not in latest:latest[d]=obj
        elif obj["publicado_utc"]==latest[d]["publicado_utc"] and obj["valor"]!=latest[d]["valor"]:
            raise ErroAmbiental("duas versões conflitantes com mesma publicação")
    return [latest[k] for k in sorted(latest)]

def preparar_graus_dia(rows_min:list[dict],rows_max:list[dict])->list[dict]:
    if not rows_min or not rows_max:raise ErroAmbiental("séries incompletas")
    info_min={(r.get("dataset_id"),r.get("estacao_id"),r.get("metrica")) for r in rows_min}
    info_max={(r.get("dataset_id"),r.get("estacao_id"),r.get("metrica")) for r in rows_max}
    if len(info_min)!=1 or len(info_max)!=1:raise ErroAmbiental("estações mistas")
    d0,s0,m0=next(iter(info_min));d1,s1,m1=next(iter(info_max))
    if d0!=d1 or s0!=s1 or d0!="INMET_ESTACOES" or m0!="TMIN_C" or m1!="TMAX_C":
        raise ErroAmbiental("estações, métricas ou fontes incompatíveis")
    a={r["data_local"]:r["valor"] for r in rows_min}
    b={r["data_local"]:r["valor"] for r in rows_max}
    if len(a)!=len(rows_min) or len(b)!=len(rows_max) or set(a)!=set(b):
        raise ErroAmbiental("dias ausentes ou duplicados")
    out=[]
    for day in sorted(a):
        if a[day]>b[day]:raise ErroAmbiental("Tmin > Tmax")
        if out and (date.fromisoformat(day)-date.fromisoformat(out[-1]["data"])).days!=1:
            raise ErroAmbiental("lacuna diária não pode ser preenchida automaticamente")
        out.append({"data":day,"tmin_c":a[day],"tmax_c":b[day]})
    return out
