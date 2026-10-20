"""Armazenamento versionado das observações CONAB em SQLite LOCAL.

A base derivada não deve ser commitada nem redistribuída sem verificar os direitos
dos dados. Captura, competência e publicação são eixos distintos.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from math import isfinite

from .transacoes_sqlite import savepoint_atomico

class ErroSerie(ValueError):pass


def abrir_series(path):
    db=sqlite3.connect(str(path),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS conab_edicoes(
      fonte_sha TEXT NOT NULL,arquivo TEXT NOT NULL,produto TEXT NOT NULL,
      subdivisao TEXT NOT NULL,publicado_em TEXT,
      PRIMARY KEY(fonte_sha,arquivo)
    );
    CREATE TABLE IF NOT EXISTS conab_coletas(
      fonte_sha TEXT NOT NULL,arquivo TEXT NOT NULL,coletado_utc TEXT NOT NULL,
      PRIMARY KEY(fonte_sha,arquivo,coletado_utc),
      FOREIGN KEY(fonte_sha,arquivo) REFERENCES conab_edicoes(fonte_sha,arquivo)
    );
    CREATE TABLE IF NOT EXISTS conab_observacoes(
      fonte_sha TEXT NOT NULL,arquivo TEXT NOT NULL,
      produto TEXT NOT NULL,subdivisao TEXT NOT NULL,
      uf TEXT NOT NULL,safra TEXT NOT NULL,
      indicador TEXT NOT NULL,unidade TEXT NOT NULL,
      valor REAL NOT NULL,classe TEXT NOT NULL,
      rotulo_original TEXT NOT NULL,cabecalho_inferido INTEGER NOT NULL,
      PRIMARY KEY(fonte_sha,arquivo,uf,safra,indicador),
      FOREIGN KEY(fonte_sha,arquivo) REFERENCES conab_edicoes(fonte_sha,arquivo)
    );
    """)
    return db


def salvar_edicao(db, observacoes, *, publicado_em=None):
    if not observacoes: raise ErroSerie("edição CONAB vazia")
    primeiro=observacoes[0]
    sha=primeiro["origem_sha256"];arq=primeiro["arquivo"]
    produto=primeiro["produto"];subdiv=primeiro["subdivisao_safra"]
    instante=primeiro["coletado_em"]
    try:
        d=datetime.fromisoformat(instante.replace("Z","+00:00"))
    except ValueError as exc: raise ErroSerie("data de coleta inválida") from exc
    if d.tzinfo is None:raise ErroSerie("coleta precisa ter timezone")
    iso=d.astimezone(timezone.utc).isoformat()
    if publicado_em is not None:
        from datetime import date
        try: date.fromisoformat(publicado_em)
        except (ValueError,TypeError) as exc: raise ErroSerie("publicacao incorreta") from exc
        if publicado_em>iso[:10]:
            raise ErroSerie("publicação futura relativamente à captura") from exc
    seen=set()
    for r in observacoes:
        if any(r[k]!=v for k,v in (
            ("origem_sha256",sha),("arquivo",arq),("produto",produto),
            ("subdivisao_safra",subdiv),("coletado_em",instante))):
            raise ErroSerie("observações misturam edições ou coletas")
        if type(r["valor"]) not in (float,int) or not isfinite(r["valor"]) or r["valor"]<0:
            raise ErroSerie("valor ausente ou inválido")
        k=(r["regiao_uf"],r["safra"],r["indicador"])
        if k in seen: raise ErroSerie("duplicata na edição")
        seen.add(k)
    with savepoint_atomico(db):
        existe=db.execute("SELECT publicado_em FROM conab_edicoes WHERE fonte_sha=? AND arquivo=?",
                          (sha,arq)).fetchone()
        nova=existe is None
        if nova:
            db.execute("INSERT INTO conab_edicoes VALUES (?,?,?,?,?)",
                       (sha,arq,produto,subdiv,publicado_em))
            db.executemany(
                "INSERT INTO conab_observacoes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(sha,arq,produto,subdiv,r["regiao_uf"],r["safra"],r["indicador"],
                  r["unidade"],r["valor"],r["classificacao"],
                  r["rotulo_coluna_original"],int(r["rotulo_coluna_inferido"]))
                 for r in observacoes]
            )
        else:
            if publicado_em is not None and existe["publicado_em"] not in (None,publicado_em):
                raise ErroSerie("data de publicação conflita com edição já existente")
            # Mesmo hash deve representar mesmas observações, não apenas mesma contagem.
            anterior=db.execute("SELECT count(*) FROM conab_observacoes WHERE fonte_sha=? AND arquivo=?",
                                (sha,arq)).fetchone()[0]
            if anterior!=len(observacoes): raise ErroSerie("mesma edição, linhas divergentes")
            # Igualdade efetiva das observações; mesma quantidade NÃO basta.
            guardado=db.execute("""SELECT produto,subdivisao,uf,safra,indicador,unidade,
                    valor,classe,rotulo_original,cabecalho_inferido
                    FROM conab_observacoes
                    WHERE fonte_sha=? AND arquivo=? ORDER BY uf,safra,indicador""",
                    (sha,arq)).fetchall()
            recebido=sorted([
                (produto,subdiv,r["regiao_uf"],r["safra"],r["indicador"],
                 r["unidade"],float(r["valor"]),r["classificacao"],
                 r["rotulo_coluna_original"],int(r["rotulo_coluna_inferido"]))
                for r in observacoes
            ],key=lambda x:(x[2],x[3],x[4]))
            if [tuple(row) for row in guardado]!=recebido:
                raise ErroSerie("mesmo hash com conteúdo/valores divergentes")
            if existe["publicado_em"] is None and publicado_em:
                db.execute("UPDATE conab_edicoes SET publicado_em=? WHERE fonte_sha=? AND arquivo=?",
                           (publicado_em,sha,arq))
        row=db.execute("SELECT 1 FROM conab_coletas WHERE fonte_sha=? AND arquivo=? AND coletado_utc=?",
                       (sha,arq,iso)).fetchone()
        if row is None:
            db.execute("INSERT INTO conab_coletas VALUES (?,?,?)",(sha,arq,iso))
    return {"nova_edicao":nova,"nova_coleta":row is None,"arquivo":arq,
            "observacoes":len(observacoes),"sha256":sha,"natureza":"DADOS_CONAB_LOCAIS"}


def consulta_na_data(db, *, corte_coleta_utc, arquivo, uf, indicador, safra):
    try: instante=datetime.fromisoformat(corte_coleta_utc.replace("Z","+00:00"))
    except ValueError as exc: raise ErroSerie("corte inválido") from exc
    if instante.tzinfo is None:raise ErroSerie("corte sem timezone")
    corte=instante.astimezone(timezone.utc).isoformat()
    d=db.execute("""
      SELECT o.valor,o.unidade,o.classe,o.fonte_sha,o.arquivo,
             e.publicado_em,c.coletado_utc
      FROM conab_coletas c
      JOIN conab_edicoes e USING(fonte_sha,arquivo)
      JOIN conab_observacoes o USING(fonte_sha,arquivo)
      WHERE o.arquivo=? AND o.uf=? AND o.indicador=? AND o.safra=?
        AND c.coletado_utc<=?
        AND (e.publicado_em IS NULL OR e.publicado_em<=substr(?,1,10))
      ORDER BY c.coletado_utc DESC,c.fonte_sha DESC LIMIT 1
    """,(arquivo,uf,indicador,safra,corte,corte)).fetchone()
    return dict(d) if d else None
