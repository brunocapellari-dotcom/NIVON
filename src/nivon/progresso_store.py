"""Memória bitemporal do progresso semanal CONAB, independente de serviços pagos.

Persiste observações normalizadas e capturas, NÃO o XLSX bruto. Publicação
desconhecida fica NULL, de modo que estudos as-of não antecipem evidências.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .conab_agrobr import normalizar_progresso, ErroProgresso


class ErroHistoricoProgresso(ValueError):
    pass


def _utc(valor: str) -> str:
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ErroHistoricoProgresso("timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroHistoricoProgresso("timestamp sem fuso")
    return dt.astimezone(timezone.utc).isoformat()


def abrir_progresso(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Inicializa memória local; caminho remoto/mount persistente é operacional."""
    if str(path) != ":memory:":
        p = Path(path)
        if p.is_symlink():
            raise ErroHistoricoProgresso("não abrir banco através de symlink")
        if not p.parent.is_dir():
            raise ErroHistoricoProgresso("diretório do banco inexistente")
    db = sqlite3.connect(str(path), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS progresso_edicoes (
          id INTEGER PRIMARY KEY,
          fonte_url TEXT NOT NULL,
          sha256_json TEXT NOT NULL,
          publicado_utc TEXT,
          observado_semana TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          numero_linhas INTEGER NOT NULL CHECK(numero_linhas>0),
          UNIQUE(fonte_url, sha256_json)
        );
        CREATE TABLE IF NOT EXISTS progresso_coletas (
          edicao_id INTEGER NOT NULL REFERENCES progresso_edicoes(id),
          coletado_utc TEXT NOT NULL,
          PRIMARY KEY(edicao_id, coletado_utc)
        );
        CREATE TABLE IF NOT EXISTS progresso_observacoes (
          edicao_id INTEGER NOT NULL REFERENCES progresso_edicoes(id),
          cultura TEXT NOT NULL,
          safra TEXT NOT NULL,
          operacao TEXT NOT NULL,
          uf TEXT NOT NULL,
          semana TEXT NOT NULL,
          registro_json TEXT NOT NULL,
          PRIMARY KEY(edicao_id,cultura,safra,operacao,uf,semana)
        );
        CREATE INDEX IF NOT EXISTS idx_progresso_chave
          ON progresso_observacoes(cultura,safra,operacao,uf,semana);
        CREATE INDEX IF NOT EXISTS idx_progresso_captura
          ON progresso_coletas(coletado_utc);
    """)
    return db


def gravar_progresso(
    db: sqlite3.Connection,
    registros: list[dict],
    *,
    evidence_id: str,
    direitos_confirmados: bool = False,
) -> dict:
    """Grava apenas dados com evidência de coleta+armazenamento.

    Recebe o resultado de normalizar_progresso. A extração deve manter todos os
    registros de uma única semana/fonte. Mesmo URL+conteúdo alterado cria vintage.
    """
    if direitos_confirmados is not True or not isinstance(evidence_id, str) or not evidence_id.strip():
        raise PermissionError("faltam direitos/evidência para armazenamento CONAB")
    if not isinstance(registros, list) or not registros:
        raise ErroHistoricoProgresso("nenhuma observação")
    base = registros[0]
    fonte, coleta, publicacao, semana = (
        base.get("source_url"), base.get("coleta"),
        base.get("publicacao"), base.get("competencia"),
    )
    # Todos precisam provir de uma única edição, com timestamps coerentes.
    from urllib.parse import urlsplit
    p = urlsplit(fonte or "")
    if p.scheme != "https" or p.hostname not in {"www.gov.br","www.conab.gov.br","conab.gov.br"}:
        raise ErroHistoricoProgresso("URL não oficial")
    coletado_utc = _utc(coleta)
    pub_utc = _utc(publicacao) if publicacao is not None else None
    if pub_utc and pub_utc > coletado_utc:
        raise ErroHistoricoProgresso("publicação futura")
    chaves = set()
    limpos = []
    for r in registros:
        if r.get("source_url") != fonte or _utc(r.get("coleta")) != coletado_utc or r.get("publicacao") != publicacao or r.get("competencia") != semana:
            raise ErroHistoricoProgresso("edições ou semanas misturadas")
        chave = tuple(r.get(k) for k in ("cultura","safra","operacao","uf","competencia"))
        if any(not x for x in chave) or chave in chaves:
            raise ErroHistoricoProgresso("chave vazia/repetida")
        chaves.add(chave)
        # Validar todos os campos sem retornar ao provedor.
        norm = normalizar_progresso([{
            "cultura":r.get("cultura"),"safra":r.get("safra"),
            "operacao":r.get("operacao"),"uf":r.get("uf"),
            "semana_atual":r.get("competencia"),
            "revisado":r.get("revisado"),
            "n_estados":r.get("n_estados"),
            "cobertura_area_pct":r.get("cobertura_area_pct"),
            **{k:r.get(k) for k in (
                "pct_ano_anterior","pct_semana_anterior","pct_semana_atual","pct_media_5_anos")},
        }], fonte_url=fonte, coletado_em=datetime.fromisoformat(coletado_utc),
           publicado_em=publicacao)[0]
        # O hash representa somente observações e datas da fonte, NÃO o horário da coleta.
        norm.pop("coleta")
        limpos.append(norm)
    limpos.sort(key=lambda r:(r["cultura"],r["safra"],r["operacao"],r["uf"],r["competencia"]))
    canonical = json.dumps(limpos, ensure_ascii=False, sort_keys=True, separators=(",",":"),allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with db:
        existe = db.execute("""SELECT * FROM progresso_edicoes
          WHERE fonte_url=? AND sha256_json=?""",(fonte,digest)).fetchone()
        nova = existe is None
        if nova:
            sid=db.execute("""INSERT INTO progresso_edicoes
              (fonte_url,sha256_json,publicado_utc,observado_semana,evidence_id,numero_linhas)
              VALUES (?,?,?,?,?,?)""",(fonte,digest,pub_utc,semana,evidence_id,len(limpos))).lastrowid
            db.executemany("""INSERT INTO progresso_observacoes
              (edicao_id,cultura,safra,operacao,uf,semana,registro_json)
              VALUES (?,?,?,?,?,?,?)""",[
                (sid,r["cultura"],r["safra"],r["operacao"],r["uf"],
                 r["competencia"],json.dumps(r,ensure_ascii=False,sort_keys=True,allow_nan=False))
                for r in limpos
            ])
        else:
            sid=existe["id"]
            if existe["evidence_id"]!=evidence_id or existe["numero_linhas"]!=len(limpos):
                raise ErroHistoricoProgresso("mesma edição com evidência/contagem divergente")
        ja=db.execute("SELECT 1 FROM progresso_coletas WHERE edicao_id=? AND coletado_utc=?",
                      (sid,coletado_utc)).fetchone()
        if ja is None:
            db.execute("INSERT INTO progresso_coletas VALUES (?,?)",(sid,coletado_utc))
    return {"status":"PERSISTIDO_NAO_HOMOLOGADO", "nova_edicao":nova,
            "nova_coleta":ja is None,"sha256":digest,"linhas":len(limpos),
            "semana":semana}


def consultar_progresso_asof(db: sqlite3.Connection, *, cultura: str, safra: str,
                            operacao: str, uf: str, semana: str,
                            corte_coleta: str, corte_publicacao: str) -> dict | None:
    """Não expõe publicação desconhecida num estudo retrospectivo."""
    coleta = _utc(corte_coleta)
    pub = _utc(corte_publicacao)
    r = db.execute("""
       SELECT o.registro_json,e.sha256_json,e.publicado_utc,c.coletado_utc
       FROM progresso_observacoes o
       JOIN progresso_edicoes e ON e.id=o.edicao_id
       JOIN progresso_coletas c ON c.edicao_id=e.id
       WHERE o.cultura=? AND o.safra=? AND o.operacao=? AND o.uf=? AND o.semana=?
         AND e.publicado_utc IS NOT NULL
         AND e.publicado_utc<=? AND c.coletado_utc<=?
       ORDER BY e.publicado_utc DESC,c.coletado_utc DESC,e.id DESC
       LIMIT 1
    """,(cultura,safra,operacao,uf,semana,pub,coleta)).fetchone()
    if r is None:
        return None
    return {"observacao":json.loads(r["registro_json"]),
            "sha256":r["sha256_json"],"publicacao":r["publicado_utc"],
            "coleta":r["coletado_utc"]}


async def atualizar_progresso(*, db: sqlite3.Connection, evidence_id: str,
                              max_pages: int = 4, max_semanas: int = 12,
                              direitos_confirmados: bool = False,
                              api=None) -> dict:
    """Retrospectiva paginada + incremental; somente execução explicitamente autorizada."""
    if direitos_confirmados is not True:
        raise PermissionError("coleta e armazenamento CONAB não aprovados")
    if not 1 <= max_semanas <= 500:
        raise ErroHistoricoProgresso("limite de histórico inválido")
    from .conab_agrobr import descobrir_semanas, coletar_progresso
    semanas=await descobrir_semanas(
        direitos_confirmados=True,max_pages=max_pages,agrobr_api=api)
    # Listagens podem repetir a mesma semana na paginação.
    urls=set()
    resultados=[]
    for item in semanas:
        url=item["url"]
        if url in urls:
            continue
        urls.add(url)
        linhas=await coletar_progresso(
            semana_url=url,direitos_confirmados=True,agrobr_api=api)
        resultados.append(gravar_progresso(
            db,linhas,evidence_id=evidence_id,direitos_confirmados=True))
        if len(resultados)>=max_semanas:
            break
    return {"semanas_processadas":len(resultados),
            "edicoes_novas":sum(r["nova_edicao"] for r in resultados),
            "coletas_novas":sum(r["nova_coleta"] for r in resultados),
            "estado":"HISTORICO_LOCAL_SEM_HOMOLOGACAO"}
