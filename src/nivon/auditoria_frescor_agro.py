"""Auditoria local de origem, frescor e RAW de CEPEA/IMEA/CONAB.

NÃO consulta URL, não gera dado novo, não habilita publicação e não equipara
data de publicação a data de referência agrícola. Sinaliza quando uma coleta
não chegou ao banco ou seu RAW mudou depois da gravação.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATASETS=(
    "CEPEA_PRECOS_FISICOS",
    "IMEA_PUBLICACOES_STAGING",
    "CONAB_SAFRAS_STAGING",
)
HORAS_LIMITE=72
DIAS_REFERENCIA_CEPEA=7
SHA=re.compile(r"[a-f0-9]{64}\Z")


class ErroFrescorAgro(ValueError):
    pass


def _dt(value):
    try:
        obj=datetime.fromisoformat(value.replace("Z","+00:00"))
        if obj.utcoffset() is None:
            raise ValueError("timezone required")
        return obj.astimezone(timezone.utc)
    except (ValueError,AttributeError,TypeError) as exc:
        raise ErroFrescorAgro("instante sem timezone ou malformado") from exc


def _tabelas(db):
    required=("snapshots","observacoes")
    found={x[0] for x in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    return all(x in found for x in required)


def _raw_confere(arquivo,sha,tamanho,raiz):
    if not isinstance(arquivo,str) or not isinstance(sha,str) or not SHA.fullmatch(sha):
        return False
    if type(tamanho) is not int or tamanho<0 or tamanho>64_000_000:
        return False
    file=Path(arquivo)
    if not file.is_absolute() or file.is_symlink() or not file.is_file():
        return False
    if raiz is None:
        return False
    root=Path(raiz)
    if not root.is_dir() or root.is_symlink():
        return False
    try:
        file.resolve().relative_to(root.resolve())
        if file.stat().st_size!=tamanho:
            return False
        h=hashlib.sha256()
        with file.open("rb") as stream:
            for piece in iter(lambda:stream.read(1_048_576),b""):
                h.update(piece)
        return h.hexdigest()==sha
    except (ValueError,OSError):
        return False


def auditar_fontes_agro(
    *, banco: str | Path, agora: datetime, diretorio_raw: str | Path | None=None,
) -> dict:
    """Leitura read-only de snapshots; retorna apenas contagens e datas."""
    now=_dt(agora.isoformat()) if isinstance(agora,datetime) else _dt(agora)
    path=Path(banco)
    if not path.is_absolute() or path.is_symlink():
        raise ErroFrescorAgro("banco SQLite requer arquivo absoluto não symlink")
    if not path.is_file():
        return {"estado":"SEM_BANCO_LOCAL","datasets":{
            k:{"estado":"SOURCE_LAG","snapshots":0,"observacoes":0,
               "referencia_verificada":False,"publicavel":False} for k in DATASETS},
            "agendamento_executado":False,"persistencia_cloud_verificada":False}
    conn=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10)
    conn.execute("PRAGMA query_only=ON")
    try:
        if not _tabelas(conn):
            raise ErroFrescorAgro("schema de ingestão ausente")
        datasets={}
        capturas={x[0] for x in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for dataset in DATASETS:
            if "capturas_fonte" in capturas:
                ss=conn.execute("""SELECT s.snapshot_id,c.coletado_em,
                    s.sha256,s.tamanho,s.arquivo,s.estado
                    FROM capturas_fonte c
                    JOIN snapshots s ON s.snapshot_id=c.snapshot_id
                    WHERE c.dataset_id=? AND s.dataset_id=?
                    ORDER BY c.coletado_em DESC,c.snapshot_id DESC LIMIT 1""",
                    (dataset,dataset)).fetchone()
                total_capturas=conn.execute("""SELECT COUNT(*)
                    FROM capturas_fonte WHERE dataset_id=?""",(dataset,)).fetchone()[0]
            else:
                ss=conn.execute("""SELECT snapshot_id,coletado_em,sha256,
                    tamanho,arquivo,estado FROM snapshots WHERE dataset_id=?
                    ORDER BY coletado_em DESC,snapshot_id DESC LIMIT 1""",
                    (dataset,)).fetchone()
                total_capturas=None
            counts=conn.execute("""SELECT
                (SELECT COUNT(*) FROM snapshots WHERE dataset_id=?),
                (SELECT COUNT(*) FROM observacoes WHERE dataset_id=?)""",
                (dataset,dataset)).fetchone()
            out={"snapshots":counts[0],"observacoes":counts[1],
                 "capturas_verificadas":total_capturas,
                 "referencia_verificada":False,"publicavel":False,
                 "persistencia_cloud_verificada":False}
            if ss is None:
                out["estado"]="SOURCE_LAG"
                datasets[dataset]=out
                continue
            _,collected,sha,size,arq,estado=ss
            instante=_dt(collected)
            hours=(now-instante).total_seconds()/3600
            out["ultima_coleta_utc"]=instante.isoformat()
            out["coleta_recente"]=0<=hours<=HORAS_LIMITE
            out["estado_snapshot"]=estado
            out["raw_sha256_confere"]=_raw_confere(arq,sha,size,diretorio_raw)
            if hours<0:
                state="COLETA_FUTURA_INCONSISTENTE"
            elif not out["raw_sha256_confere"]:
                state="RAW_NAO_VERIFICADO"
            elif not out["coleta_recente"]:
                state="SOURCE_LAG"
            elif estado!="NORMALIZED":
                state="QUARENTENA_NAO_PUBLICAVEL"
            elif dataset!="CEPEA_PRECOS_FISICOS":
                # Referência da safra e publicação são temporalidades diversas.
                state="METADADO_NAO_PROMOVIDO"
            else:
                last=conn.execute("""SELECT MAX(referencia) FROM observacoes
                    WHERE dataset_id=? AND snapshot_id=?""",
                    (dataset,ss[0])).fetchone()[0]
                if last is None:
                    state="SEM_OBSERVACAO_NO_SNAPSHOT"
                else:
                    try:
                        ref=datetime.strptime(last,"%Y-%m-%d").date()
                    except ValueError:
                        state="REFERENCIA_NAO_DIARIA"
                    else:
                        diff=(now.date()-ref).days
                        out["ultima_referencia_cepea"]=ref.isoformat()
                        out["referencia_verificada"]=0<=diff<=DIAS_REFERENCIA_CEPEA
                        state=("CANDIDATO_RECENTE_SEM_LICENCA_HOMOLOGADA"
                               if out["referencia_verificada"]
                               else "REFERENCIA_DEFASADA_OU_FUTURA")
            out["estado"]=state
            datasets[dataset]=out
        return {"estado":"AUDITORIA_LOCAL_CONCLUIDA",
                "datasets":datasets,
                "agendamento_executado":False,
                "persistencia_cloud_verificada":False,
                "permissao_de_publicacao_verificada":False}
    finally:
        conn.close()
