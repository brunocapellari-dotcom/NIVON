"""Persistência local de séries agregadas ferroviárias ANTT/SIADE.

Armazena apenas somas por mês, mercadoria, UF origem/destino e estação
de origem/destino; jamais interpreta estações como municípios consumidores.
Cada edição tem hash de origem, cada coleta tem seu instante de conhecimento.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path


class ErroHistoricoFerroviario(ValueError):
    pass


def _utc(valor: str) -> str:
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ErroHistoricoFerroviario("instante de coleta inválido") from exc
    if instante.tzinfo is None:
        raise ErroHistoricoFerroviario("instante de coleta precisa de fuso")
    return instante.astimezone(timezone.utc).isoformat()


def abrir_banco(caminho: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(caminho), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS edicoes_ferrovia (
            hash_fonte TEXT PRIMARY KEY,
            primeiro_registro TEXT NOT NULL,
            fonte TEXT NOT NULL CHECK (fonte='ANTT_SIADE_FERROVIA')
        );
        CREATE TABLE IF NOT EXISTS coletas_ferrovia (
            hash_fonte TEXT NOT NULL REFERENCES edicoes_ferrovia(hash_fonte),
            coletado_em TEXT NOT NULL,
            PRIMARY KEY(hash_fonte, coletado_em)
        );
        CREATE TABLE IF NOT EXISTS series_ferrovia (
            hash_fonte TEXT NOT NULL REFERENCES edicoes_ferrovia(hash_fonte),
            mes TEXT NOT NULL, mercadoria_fonte TEXT NOT NULL,
            origem_uf TEXT NOT NULL, destino_uf TEXT NOT NULL,
            origem_estacao TEXT NOT NULL, destino_estacao TEXT NOT NULL,
            linhas INTEGER NOT NULL CHECK(linhas>0),
            tu_t REAL NOT NULL CHECK(tu_t>=0),
            tku REAL NOT NULL CHECK(tku>=0),
            PRIMARY KEY(hash_fonte,mes,mercadoria_fonte,origem_uf,destino_uf,
                        origem_estacao,destino_estacao)
        );
        CREATE INDEX IF NOT EXISTS idx_coletas_antt_em ON coletas_ferrovia(coletado_em);
        CREATE INDEX IF NOT EXISTS idx_series_antt_mes ON series_ferrovia(mes,origem_uf);
    """)
    return conn


def _agrupar(registros, limite=400_000):
    agrupados = defaultdict(lambda: [0, 0.0, 0.0])
    origem_hash = None
    count = 0
    for r in registros:
        count += 1
        if count > limite:
            raise ErroHistoricoFerroviario("origem acima do limite de registros")
        sha = r["arquivo_sha256"]
        if origem_hash is None:
            origem_hash = sha
        if sha != origem_hash:
            raise ErroHistoricoFerroviario("hashes de arquivos diferentes")
        if r.get("modal") != "FERROVIARIO" or r.get("local_tipo") != "ESTACAO_NAO_MUNICIPIO":
            raise ErroHistoricoFerroviario("modalidade geográfica incompatível")
        tu = r["tu_t"]
        tku = r["tku"]
        if any(type(v) not in (int,float) or not isfinite(v) or v < 0 for v in (tu,tku)):
            raise ErroHistoricoFerroviario("TU/TKU inválido")
        chave = (r["periodo"],r["mercadoria_antt"],r["origem_uf"],r["destino_uf"],
                 r["origem_estacao"],r["destino_estacao"])
        agrupados[chave][0] += 1
        agrupados[chave][1] += tu
        agrupados[chave][2] += tku
    if count == 0 or not origem_hash or len(origem_hash) != 64:
        raise ErroHistoricoFerroviario("arquivo ou hash ausente")
    return origem_hash, agrupados, count


def guardar_serie(conn: sqlite3.Connection, registros, *, coletado_em: str) -> dict:
    corte = _utc(coletado_em)
    sha, agrupados, quantidade = _agrupar(registros)
    with conn:
        existe = conn.execute(
            "SELECT 1 FROM edicoes_ferrovia WHERE hash_fonte=?", (sha,)
        ).fetchone()
        edicao_nova = existe is None
        if edicao_nova:
            conn.execute("INSERT INTO edicoes_ferrovia VALUES (?,?,?)",
                         (sha,corte,"ANTT_SIADE_FERROVIA"))
            conn.executemany(
                "INSERT INTO series_ferrovia VALUES (?,?,?,?,?,?,?,?,?,?)",
                ((sha, *chave, valores[0], valores[1], valores[2])
                 for chave, valores in sorted(agrupados.items()))
            )
        else:
            anterior = {
                (r["mes"],r["mercadoria_fonte"],r["origem_uf"],r["destino_uf"],
                 r["origem_estacao"],r["destino_estacao"]):
                (r["linhas"],r["tu_t"],r["tku"])
                for r in conn.execute("SELECT * FROM series_ferrovia WHERE hash_fonte=?", (sha,))
            }
            if set(anterior) != set(agrupados):
                raise ErroHistoricoFerroviario("mesmo hash com chaves divergentes")
            for chave, val in agrupados.items():
                antigo = anterior[chave]
                if antigo[0] != val[0] or abs(antigo[1] - val[1]) > 0.001 or abs(antigo[2] - val[2]) > 0.001:
                    raise ErroHistoricoFerroviario("mesmo hash com volumes divergentes")
        coleta = conn.execute(
            "SELECT 1 FROM coletas_ferrovia WHERE hash_fonte=? AND coletado_em=?",
            (sha,corte)
        ).fetchone()
        nova_coleta = coleta is None
        if nova_coleta:
            conn.execute("INSERT INTO coletas_ferrovia VALUES (?,?)", (sha,corte))
    return {"hash_fonte":sha,"nova_edicao":edicao_nova,"nova_coleta":nova_coleta,
            "registros_origem":quantidade,"series_agregadas":len(agrupados),
            "natureza":"FERROVIA_NAO_RODOVIA_NAO_CONSUMO"}


def consultar_ferrovia_em(conn:sqlite3.Connection, *, corte_utc:str,
                          mes:str, origem_uf:str="MT") -> dict:
    corte = _utc(corte_utc)
    edicao = conn.execute(
        """SELECT hash_fonte, coletado_em FROM coletas_ferrovia
           WHERE coletado_em<=? ORDER BY coletado_em DESC,hash_fonte DESC LIMIT 1""",
        (corte,)
    ).fetchone()
    if edicao is None:
        return {"estado":"SEM_COLETA","rotas":[]}
    rotas = [dict(r) for r in conn.execute(
        """SELECT mercadoria_fonte,destino_uf,origem_estacao,destino_estacao,
                  SUM(tu_t) AS tu_t,SUM(tku) AS tku
           FROM series_ferrovia
           WHERE hash_fonte=? AND mes=? AND origem_uf=?
           GROUP BY mercadoria_fonte,destino_uf,origem_estacao,destino_estacao
           ORDER BY mercadoria_fonte,destino_uf,origem_estacao,destino_estacao""",
        (edicao["hash_fonte"], mes, origem_uf)
    )]
    return {"estado":"DISPONIVEL","mes":mes,"origem_uf":origem_uf,
            "hash_fonte":edicao["hash_fonte"],"coletado_em":edicao["coletado_em"],
            "rotas":rotas,"natureza":"FERROVIARIO_ESTACOES_NAO_MUNICIPIOS"}
