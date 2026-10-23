"""Ingestão incremental OFFLINE SAGyP Argentina com lote SQLite atômico.

RAWs privados e manifestos assináveis externamente; NÃO faz GET, nem reconhece
metadata CKAN como data de publicação. Integra dados somente em quarentena.
A edição sempre é identificada pelo SHA do CSV e recurso catalogado.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata

from .argentina_agricultura import (
    CAMPOS, ErroArgentina, RECURSOS, _SQL, _url_legal, _utc, ler_linhas_csv,
)

SCHEMA = "NIVON_ARG_INCREMENTAL_RAW_LOCAL_V1"
LIMITE_EDICOES = 24
LIMITE_TOTAL_BYTES = 120_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COLUNAS = (
    "cultivo", "anio", "campania", "provincia", "provincia_id",
    "departamento", "departamento_id", "superficie_sembrada_ha",
    "superficie_cosechada_ha", "produccion_tm", "rendimiento_kgxha",
)


class ErroIncrementalArgentina(ErroArgentina):
    pass


def _privado(p: Path, *, pasta: bool):
    if not p.is_absolute() or p.is_symlink() or (
        not p.is_dir() if pasta else not p.is_file()
    ):
        raise ErroIncrementalArgentina("caminho privado absoluto e regular obrigatório")
    if os.name == "posix":
        st = p.stat()
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise ErroIncrementalArgentina("RAW e SQLite não podem ter acesso de grupo/outros")
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise ErroIncrementalArgentina("arquivos devem pertencer ao operador")
    return p


def _manifesto(catalogo: dict):
    if not isinstance(catalogo, dict) or set(catalogo) != {"schema", "edicoes"}:
        raise ErroIncrementalArgentina("manifesto fora do contrato")
    if catalogo["schema"] != SCHEMA or not isinstance(catalogo["edicoes"], list):
        raise ErroIncrementalArgentina("schema incremental não reconhecido")
    if not 1 <= len(catalogo["edicoes"]) <= LIMITE_EDICOES:
        raise ErroIncrementalArgentina("quantidade de edições excedida")
    parsed = []
    ids = set()
    for e in catalogo["edicoes"]:
        keys = {"recurso", "sha256", "arquivo", "origem_url", "coletado_em"}
        if not isinstance(e, dict) or set(e) != keys:
            raise ErroIncrementalArgentina("edição com metadados incompletos")
        recurso, digest = e["recurso"], e["sha256"]
        if recurso not in RECURSOS or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ErroIncrementalArgentina("recurso/SHA não catalogado")
        if e["arquivo"] != digest + ".csv":
            raise ErroIncrementalArgentina("RAW deve ser endereçado exclusivamente pelo SHA")
        if not isinstance(e["origem_url"], str):
            raise ErroIncrementalArgentina("URL de origem ausente")
        _url_legal(e["origem_url"])
        try:
            instante = datetime.fromisoformat(e["coletado_em"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ErroIncrementalArgentina("data de coleta inválida") from exc
        corte = _utc(instante)
        if instante.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise ErroIncrementalArgentina("coleta datada no futuro")
        edicao_id = "ARG_" + recurso.upper() + "_" + digest
        if edicao_id in ids:
            raise ErroIncrementalArgentina("edição repetida no manifesto")
        ids.add(edicao_id)
        parsed.append((edicao_id, recurso, digest, e["origem_url"], corte))
    return sorted(parsed)


def _cultivo_do_recurso(recurso: str, cultivo: str):
    """Não misturar observações de soja, milho e trigo por rótulo do recurso."""
    if recurso == "todos":
        return
    canonico = "".join(
        char for char in unicodedata.normalize("NFKD", cultivo)
        if not unicodedata.combining(char)
    ).strip().upper()
    esperado = {"soja": "SOJA", "milho": "MAIZ", "trigo": "TRIGO"}[recurso]
    if canonico != esperado:
        raise ErroIncrementalArgentina(
            "cultivo do CSV diverge do recurso oficial selecionado"
        )


def _digest_pares(rows):
    return sha256(json.dumps(sorted(rows), ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _linhas_db(db, eid):
    return list(db.execute(
        """SELECT cultivo,anio,campania,provincia,provincia_id,
           departamento,departamento_id,superficie_sembrada_ha,
           superficie_cosechada_ha,produccion_tm,rendimiento_kgxha
           FROM ar_estimaciones WHERE edicion_id=? ORDER BY
           cultivo,campania,provincia_id,departamento_id""", (eid,),
    ))


def _auditar(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ErroIncrementalArgentina("integridade SQLite falhou")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ErroIncrementalArgentina("chaves estrangeiras violadas")
    for eid, n in db.execute("SELECT edicion_id,filas FROM ar_ediciones").fetchall():
        anchor = db.execute(
            "SELECT sha256_semantico FROM ar_integridade_incremental WHERE edicion_id=?",
            (eid,),
        ).fetchone()
        rows = _linhas_db(db, eid)
        if not anchor or not rows or n != len(rows) or _digest_pares(rows) != anchor[0]:
            raise ErroIncrementalArgentina(
                "histórico sem prova ou adulterado; revisão humana obrigatória"
            )


def sincronizar_raw_argentina_local(
    catalogo: dict, *, banco: str | Path, pasta_raw: str | Path,
    direitos_armazenamento_verificados: bool = False,
):
    """Primeira/segunda/terceira rodada: escreve apenas SHA novo, transação única.

    Não confirma licenças por si só; a flag exige decisão externa independente.
    Não considera os dados correntes nem publicáveis sem data oficial provada.
    """
    if direitos_armazenamento_verificados is not True:
        raise PermissionError("direito de armazenamento explicitamente verificado obrigatório")
    entries = _manifesto(catalogo)
    rawdir = _privado(Path(pasta_raw), pasta=True)
    target = Path(banco)
    if not target.is_absolute() or not target.parent.is_dir() or target.is_symlink():
        raise ErroIncrementalArgentina("banco SQLite exige caminho absoluto seguro")
    _privado(target.parent, pasta=True)
    if target.exists():
        _privado(target, pasta=False)
    else:
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        os.close(fd)
    db = sqlite3.connect(str(target), timeout=20)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(_SQL)
        db.execute("""CREATE TABLE IF NOT EXISTS ar_integridade_incremental(
            edicion_id TEXT PRIMARY KEY REFERENCES ar_ediciones(edicion_id),
            sha256_semantico TEXT NOT NULL
        )""")
        db.commit()
        _auditar(db)
        previous = {eid: (recurso, digest, url) for eid, recurso, digest, url
                    in db.execute("SELECT edicion_id,recurso,sha256,origen_url FROM ar_ediciones")}
        pending = []
        total = 0
        for eid, recurso, digest, url, utc in entries:
            if eid in previous:
                if previous[eid] != (recurso, digest, url):
                    raise ErroIncrementalArgentina("edição anterior conflita com manifesto")
                continue
            file = rawdir / (digest + ".csv")
            _privado(file, pasta=False)
            size = file.stat().st_size
            if not 0 < size <= LIMITE_TOTAL_BYTES or total + size > LIMITE_TOTAL_BYTES:
                raise ErroIncrementalArgentina("limite total de RAWs excedido")
            total += size
            raw = file.read_bytes()
            if sha256(raw).hexdigest() != digest:
                raise ErroIncrementalArgentina("SHA-256 do RAW diverge do manifesto")
            linhas = []
            seen = set()
            for row in ler_linhas_csv(raw):
                _cultivo_do_recurso(recurso, row["cultivo"])
                vals = tuple(row[col] for col in _COLUNAS)
                key = (row["cultivo"], row["campania"],
                       row["provincia_id"], row["departamento_id"])
                if key in seen:
                    raise ErroIncrementalArgentina("chave econômica duplicada na edição")
                seen.add(key)
                linhas.append(vals)
            if not linhas:
                raise ErroIncrementalArgentina("RAW sem observações")
            pending.append((eid, recurso, digest, url, utc, linhas))
        if not pending:
            return {"estado": "SEM_DELTA_SEM_DOWNLOAD_OU_ESCRITA_DE_EDICAO",
                    "edicoes_novas": 0, "edicoes_inalteradas": len(entries),
                    "observacoes_novas": 0, "publicacao_verificada": False,
                    "cloud_integrado": False, "publicacao_permitida": False}
        try:
            db.execute("BEGIN IMMEDIATE")
            # Revalidar contra outra conexão que tenha escrito após o preflight.
            _auditar(db)
            existentes = {row[0] for row in db.execute("SELECT edicion_id FROM ar_ediciones")}
            for eid, recurso, digest, url, utc, linhas in pending:
                if eid in existentes:
                    raise ErroIncrementalArgentina("edição escrita concorrentemente; replanejar delta")
                db.execute("""INSERT INTO ar_ediciones VALUES (?,?,?,?,?,?,0,?,?)""",
                           (eid, recurso, digest, url, utc, None, "INTERNO_NAO_COMERCIAL", len(linhas)))
                db.executemany(
                    """INSERT INTO ar_estimaciones VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?, 'ESTIMADO')""",
                    [(eid, *row) for row in linhas],
                )
                saved = _linhas_db(db, eid)
                db.execute(
                    "INSERT INTO ar_integridade_incremental VALUES (?,?)",
                    (eid, _digest_pares(saved)),
                )
            _auditar(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return {"estado": "DELTA_LOCAL_ATOMICO_QUARENTENA",
                "edicoes_novas": len(pending),
                "edicoes_inalteradas": len(entries) - len(pending),
                "observacoes_novas": sum(len(p[-1]) for p in pending),
                "observacoes_apos": db.execute(
                    "SELECT COUNT(*) FROM ar_estimaciones"
                ).fetchone()[0],
                "publicacao_verificada": False,
                "cloud_integrado": False, "publicacao_permitida": False}
    except sqlite3.Error as exc:
        raise ErroIncrementalArgentina("transação SQL falhou; sem promoção") from exc
    finally:
        db.close()
