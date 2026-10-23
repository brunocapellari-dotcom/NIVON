"""Memória incremental SQLite de agregados municipais MAPA: sem registros individuais."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .cadastro_derivado import carregar_municipios_racao


def abrir(caminho: str | Path):
    con = sqlite3.connect(str(caminho))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS edicoes (
          id INTEGER PRIMARY KEY, hash_fonte TEXT UNIQUE NOT NULL,
          primeira_coleta TEXT NOT NULL, municipios INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cidades (
          edicao_id INTEGER NOT NULL REFERENCES edicoes(id),
          uf TEXT NOT NULL, municipio TEXT NOT NULL,
          PRIMARY KEY(edicao_id, uf, municipio)
        );
        CREATE TABLE IF NOT EXISTS coletas (
          edicao_id INTEGER NOT NULL REFERENCES edicoes(id),
          coletado_utc TEXT NOT NULL,
          hash_agregado TEXT NOT NULL,
          PRIMARY KEY(edicao_id, coletado_utc)
        );
    """)
    return con


def _tempo(valor):
    d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("data de coleta sem fuso")
    return d.astimezone(timezone.utc).isoformat()


def registrar(con, caminho):
    item = carregar_municipios_racao(caminho)
    fonte_hash = item["hash_arquivo_mapa_origem_sha256"]
    agregado_hash = item["hash_arquivo_agregado_sha256"]
    coleta = _tempo(item["coletado_em"])
    cidades = {(f.uf, f.municipio) for f in item["fabrica_candidata_por_municipio"]}
    with con:
        edicao = con.execute("SELECT id FROM edicoes WHERE hash_fonte=?", (fonte_hash,)).fetchone()
        nova_edicao = edicao is None
        if nova_edicao:
            cur = con.execute(
                "INSERT INTO edicoes(hash_fonte, primeira_coleta, municipios) VALUES (?,?,?)",
                (fonte_hash, coleta, len(cidades))
            )
            eid = cur.lastrowid
            con.executemany(
                "INSERT INTO cidades(edicao_id,uf,municipio) VALUES (?,?,?)",
                [(eid, uf, cidade) for uf, cidade in sorted(cidades)]
            )
        else:
            eid = edicao["id"]
            antigo = {(r["uf"], r["municipio"]) for r in con.execute(
                "SELECT uf,municipio FROM cidades WHERE edicao_id=?", (eid,))}
            if antigo != cidades:
                raise ValueError("hash da fonte repetido com municipios diferentes")
        anterior = con.execute(
            "SELECT hash_agregado FROM coletas WHERE edicao_id=? AND coletado_utc=?",
            (eid, coleta)
        ).fetchone()
        if anterior and anterior["hash_agregado"] != agregado_hash:
            raise ValueError("mesma coleta com conteúdo divergente")
        if anterior is None:
            con.execute("INSERT INTO coletas VALUES (?,?,?)", (eid, coleta, agregado_hash))
    return {"nova_edicao": nova_edicao, "nova_coleta": anterior is None,
            "municipios": len(cidades), "fonte_sha256": fonte_hash,
            "coletado_utc": coleta, "natureza": "CADASTRO_NAO_CONSUMO"}


def consultar_em(con, corte_utc: str):
    corte = _tempo(corte_utc)
    row = con.execute(
        "SELECT edicao_id, coletado_utc FROM coletas WHERE coletado_utc<=? "
        "ORDER BY coletado_utc DESC, edicao_id DESC LIMIT 1", (corte,)
    ).fetchone()
    if row is None:
        return {"estado": "SEM_COLETA", "municipios": []}
    cidades = [dict(r) for r in con.execute(
        "SELECT uf, municipio FROM cidades WHERE edicao_id=? ORDER BY uf,municipio",
        (row["edicao_id"],)
    )]
    return {"estado": "DISPONIVEL", "coletado_utc": row["coletado_utc"],
            "municipios": cidades, "natureza": "CADASTRO_NAO_CONSUMO"}
