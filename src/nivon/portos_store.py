"""Histórico de programação portuária com provenance e versões de documentos.

Não converte line-up em embarque realizado. O conteúdo bruto dos documentos
deve ter guarda autorizada independente; este banco guarda apenas extrações.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from .portos import Programacao


class ErroHistoricoPortuario(ValueError):
    pass


def _timestamp(value: str) -> str:
    try:
        d = datetime.fromisoformat(value.replace("Z","+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ErroHistoricoPortuario("timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroHistoricoPortuario("timestamp sem fuso")
    return d.astimezone(timezone.utc).isoformat()


def abrir_historico_portos(path: str | Path = ":memory:") -> sqlite3.Connection:
    if str(path) != ":memory:":
        p=Path(path)
        if p.is_symlink() or not p.parent.is_dir():
            raise ErroHistoricoPortuario("caminho de arquivo não autorizado")
    db=sqlite3.connect(str(path),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS porto_docs (
        id INTEGER PRIMARY KEY,
        porto TEXT NOT NULL,
        fonte_url TEXT NOT NULL,
        sha256_original TEXT NOT NULL,
        sha256_extracao TEXT NOT NULL,
        numero_linhas INTEGER NOT NULL CHECK(numero_linhas>0),
        evidence_id TEXT NOT NULL,
        UNIQUE(porto,fonte_url,sha256_original)
      );
      CREATE TABLE IF NOT EXISTS porto_capturas (
        doc_id INTEGER NOT NULL REFERENCES porto_docs(id),
        capturado_utc TEXT NOT NULL,
        PRIMARY KEY(doc_id,capturado_utc)
      );
      CREATE TABLE IF NOT EXISTS porto_linhas (
        doc_id INTEGER NOT NULL REFERENCES porto_docs(id),
        ordem INTEGER NOT NULL,
        row_json TEXT NOT NULL,
        PRIMARY KEY(doc_id,ordem)
      );
      CREATE INDEX IF NOT EXISTS idx_porto_docs_fonte ON porto_docs(porto,fonte_url);
    """)
    return db


def gravar_documento_porto(db: sqlite3.Connection, processamento: dict, *,
                          evidence_id: str, direitos_confirmados: bool = False) -> dict:
    if direitos_confirmados is not True or not isinstance(evidence_id,str) or not evidence_id.strip():
        raise PermissionError("portos: direitos de coleta/armazenamento não confirmados")
    if processamento.get("status") != "EXTRAIDO_AGUARDA_HOMOLOGACAO":
        raise ErroHistoricoPortuario("extração não está no estado permitido")
    porto=processamento.get("porto")
    fonte=processamento.get("fonte")
    original=processamento.get("documento_sha256")
    from urllib.parse import urlsplit
    parsed=urlsplit(fonte or "")
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        raise ErroHistoricoPortuario("fonte HTTP inválida")
    if not isinstance(original,str) or len(original)!=64 or any(c not in "0123456789abcdef" for c in original):
        raise ErroHistoricoPortuario("hash do documento inválido")
    captura=_timestamp(processamento.get("capturado_em"))
    registros=processamento.get("registros")
    if not isinstance(registros,list) or not registros:
        raise ErroHistoricoPortuario("extração sem escalas")
    linhas=[]
    for r in registros:
        if not isinstance(r,Programacao) or r.porto!=porto or r.fonte!=fonte:
            raise ErroHistoricoPortuario("documento mistura portos ou fontes")
        if _timestamp(r.coletado_em)!=captura or r.status!="PROGRAMADO":
            raise ErroHistoricoPortuario("linha com tempo ou status incompatível")
        registro = asdict(r)
        registro.pop("coletado_em")  # não incluir hora da captura no hash da edição
        linhas.append(registro)
    payload=json.dumps(linhas,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    digest=hashlib.sha256(payload.encode()).hexdigest()
    with db:
        row=db.execute("""SELECT * FROM porto_docs
          WHERE porto=? AND fonte_url=? AND sha256_original=?""",
          (porto,fonte,original)).fetchone()
        novo=row is None
        if row is None:
            ident=db.execute("""INSERT INTO porto_docs
              (porto,fonte_url,sha256_original,sha256_extracao,numero_linhas,evidence_id)
              VALUES (?,?,?,?,?,?)""",(porto,fonte,original,digest,len(registros),evidence_id)).lastrowid
            db.executemany("INSERT INTO porto_linhas VALUES (?,?,?)",[
                (ident,i,json.dumps(l,ensure_ascii=False,sort_keys=True,allow_nan=False))
                for i,l in enumerate(linhas)
            ])
        else:
            ident=row["id"]
            if row["sha256_extracao"]!=digest or row["numero_linhas"]!=len(registros) or row["evidence_id"]!=evidence_id:
                raise ErroHistoricoPortuario("mesmo documento com interpretação/evidência diferente")
        vista=db.execute("SELECT 1 FROM porto_capturas WHERE doc_id=? AND capturado_utc=?",
                         (ident,captura)).fetchone()
        if vista is None:
            db.execute("INSERT INTO porto_capturas VALUES (?,?)",(ident,captura))
    return {"porto":porto,"linhas":len(registros),"nova_versao":novo,
            "nova_captura":vista is None,"sha256_original":original,
            "status":"PERSISTIDO_PROGRAMACAO_NAO_HOMOLOGADA"}


def historico_porto(db: sqlite3.Connection, *, porto: str,
                    corte_coleta: str) -> list[dict]:
    """Última captura disponível na data, sem inventar realização."""
    instante=_timestamp(corte_coleta)
    row=db.execute("""SELECT d.id,d.sha256_original,c.capturado_utc
      FROM porto_docs d JOIN porto_capturas c ON c.doc_id=d.id
      WHERE d.porto=? AND c.capturado_utc<=?
      ORDER BY c.capturado_utc DESC,d.id DESC LIMIT 1""",(porto,instante)).fetchone()
    if row is None:
        return []
    observacoes=db.execute("SELECT row_json FROM porto_linhas WHERE doc_id=? ORDER BY ordem",
                            (row["id"],)).fetchall()
    return [dict(json.loads(o["row_json"]),documento_sha256=row["sha256_original"],
                 captura_consultada=row["capturado_utc"]) for o in observacoes]
