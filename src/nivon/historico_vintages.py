"""Armazenamento offline de edições históricas (vintages) para backtest point-in-time.

SQLite é apenas a camada local de índice normalizado. RAW imutável autorizado,
licença por operação, backups e execução remota permanecem gates separados.
Nunca inventar publication/availability; sem ambas não entra no backtest.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3
from .qualidade_cientifica import ErroCientifico, _instante


CLASSES = frozenset({"OBSERVADO","INFORMADO","ESTIMADO","PROJETADO","INFERIDO"})
_CAMPOS = frozenset({
    "source_id","dataset_id","serie_id","competencia","referencia","edicao_id",
    "unidade","valor","classe_evidencia","publicado_em","disponivel_em",
    "coletado_em","fonte_url","raw_sha256",
})
_ID = re.compile(r"^[A-Z][A-Z0-9_]{1,90}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS edicoes (
 source_id TEXT NOT NULL, dataset_id TEXT NOT NULL, serie_id TEXT NOT NULL,
 competencia TEXT NOT NULL, referencia TEXT NOT NULL, edicao_id TEXT NOT NULL,
 unidade TEXT NOT NULL, valor TEXT NOT NULL, classe_evidencia TEXT NOT NULL,
 publicado_em TEXT, disponivel_em TEXT, coletado_em TEXT NOT NULL,
 fonte_url TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
 PRIMARY KEY (dataset_id,serie_id,competencia,edicao_id)
);
CREATE INDEX IF NOT EXISTS idx_asof ON edicoes
(dataset_id,serie_id,competencia,disponivel_em);
"""


def _utc(texto, campo):
    if texto is None:return None
    v=_instante(texto,campo)
    # ISO UTC text ordered lexicographically; never compare offset-ISO strings in SQLite.
    from datetime import timezone
    return v.astimezone(timezone.utc).isoformat(timespec="seconds")


def _valor(texto):
    if isinstance(texto,bool) or not isinstance(texto,(str,int,float,Decimal)):
        raise ErroCientifico("valor da observação inválido")
    try:v=Decimal(str(texto))
    except InvalidOperation as exc:raise ErroCientifico("decimal inválido") from exc
    if not v.is_finite() or len(v.as_tuple().digits)>40:
        raise ErroCientifico("decimal não finito/excessivamente preciso")
    return str(v)


def normalizar_edicao(item:dict) -> dict:
    if not isinstance(item,dict) or not _CAMPOS<=item.keys():
        raise ErroCientifico("observação sem campos obrigatórios")
    d={k:item[k] for k in _CAMPOS}
    for key in ("source_id","dataset_id"):
        if not isinstance(d[key],str) or not _ID.fullmatch(d[key]):
            raise ErroCientifico(f"{key} inválido")
    for key in ("serie_id","competencia","referencia","edicao_id","unidade"):
        if not isinstance(d[key],str) or not d[key].strip() or len(d[key])>160:
            raise ErroCientifico(f"{key} inválido")
    if d["classe_evidencia"] not in CLASSES:
        raise ErroCientifico("classe da evidência não catalogada")
    if not isinstance(d["raw_sha256"],str) or not _HASH.fullmatch(d["raw_sha256"]):
        raise ErroCientifico("hash SHA-256 do bruto obrigatório")
    from urllib.parse import urlsplit
    link=urlsplit(str(d["fonte_url"]))
    if link.scheme!="https" or not link.hostname or link.username or link.password or link.port not in (None,443):
        raise ErroCientifico("link de evidência deve ser HTTPS sem credenciais")
    d["valor"]=_valor(d["valor"])
    d["publicado_em"]=_utc(d["publicado_em"],"publicado_em")
    d["disponivel_em"]=_utc(d["disponivel_em"],"disponivel_em")
    d["coletado_em"]=_utc(d["coletado_em"],"coletado_em")
    if (d["publicado_em"] is None)!=(d["disponivel_em"] is None):
        raise ErroCientifico("publicação e disponibilidade devem ser ambas comprovadas ou ambas nulas")
    if d["publicado_em"] is not None:
        if not d["publicado_em"]<=d["disponivel_em"]<=d["coletado_em"]:
            raise ErroCientifico("sequência temporal publicação-disponibilidade-coleta impossível")
    return d


class ArmazemVintages:
    def __init__(self,caminho: str|Path=":memory:"):
        self.conn=sqlite3.connect(str(caminho))
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def fechar(self):self.conn.close()

    def gravar(self,registro:dict) -> str:
        d=normalizar_edicao(registro)
        pk=(d["dataset_id"],d["serie_id"],d["competencia"],d["edicao_id"])
        linhas=self.conn.execute(
            "SELECT * FROM edicoes WHERE dataset_id=? AND serie_id=? AND competencia=? AND edicao_id=?",pk
        ).fetchone()
        # Coletas subsequentes da mesma edição podem ter outro horário, mas
        # nenhum atributo de conteúdo/versão pode ser substituído.
        if linhas:
            fields=set(_CAMPOS)-{"coletado_em"}
            if any(linhas[k]!=d[k] for k in fields):
                raise ErroCientifico("mesmo ID de edição com conteúdo ou provenance conflitante")
            return "DUPLICATA_IDEMPOTENTE"
        cols=sorted(_CAMPOS)
        placeholders=",".join("?" for _ in cols)
        with self.conn:
            self.conn.execute(f"INSERT INTO edicoes ({','.join(cols)}) VALUES ({placeholders})",
                              [d[k] for k in cols])
        return "EDICAO_PERSISTIDA_LOCALMENTE"

    def consultar_asof(self,*,dataset_id:str,serie_id:str,
                       competencia:str,instante_decisao:str) -> dict|None:
        corte=_utc(instante_decisao,"instante_decisao")
        if not all(isinstance(x,str) and x for x in (dataset_id,serie_id,competencia)):
            raise ErroCientifico("identidade da série incompleta")
        row=self.conn.execute(
            """SELECT * FROM edicoes WHERE dataset_id=? AND serie_id=? AND competencia=?
               AND disponivel_em IS NOT NULL AND disponivel_em<=?
               ORDER BY disponivel_em DESC, publicado_em DESC, edicao_id DESC LIMIT 1""",
            (dataset_id,serie_id,competencia,corte)
        ).fetchone()
        if row is None:return None
        return {**dict(row),"valor_decimal":Decimal(row["valor"]),
                "status":"EDICAO_CONHECIDA_ASOF_NAO_HOMOLOGADA"}

    def contar(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM edicoes").fetchone()[0]
