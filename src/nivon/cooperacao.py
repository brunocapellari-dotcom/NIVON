"""Shared offline task ledger for two independent coding agents.

SQLite is kept in git-common-dir so worktrees share leases. This does not
launch providers, access network, schedule work or merge code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

AGENTS = {"claude", "codex"}
STATES = {"pending", "running", "done", "blocked"}


def utcnow():
    return datetime.now(timezone.utc)


def default_db():
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, timeout=5
        )
        root = Path(proc.stdout.strip())
        if root.is_dir():
            return root / "nivon-cooperation.sqlite"
    except (OSError, subprocess.SubprocessError):
        pass
    raise ValueError("Sem git-common-dir: passe --db CAMINHO explicitamente")


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, scope TEXT NOT NULL,
        priority INTEGER NOT NULL, preferred_agent TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', owner TEXT,
        claimed_at TEXT, lease_until TEXT, finished_at TEXT,
        tokens_in INTEGER, tokens_out INTEGER,
        note TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0)""")
    db.commit()
    return db


def clean_scope(value):
    if not isinstance(value, list) or not value:
        raise ValueError("scope precisa conter caminhos")
    result = []
    for raw in value:
        if not isinstance(raw, str) or not raw or raw.startswith(("/", "~")) or "\\" in raw:
            raise ValueError("Caminho inseguro")
        path = Path(raw)
        if any(part in (".", "..") for part in path.parts):
            raise ValueError("Travessia de caminhos")
        result.append(path.as_posix().rstrip("/"))
    return sorted(set(result))


def overlap(a, b):
    return any(x == y or x.startswith(y + "/") or y.startswith(x + "/")
               for x in a for y in b)


def seed(db, manifest):
    prepared, seen = [], set()
    for row in manifest:
        task_id = row["id"]
        if not isinstance(task_id, str) or not task_id or task_id in seen:
            raise ValueError("IDs invalidos ou duplicados")
        seen.add(task_id)
        preference = row.get("preferred_agent", "any")
        priority = row.get("priority", 100)
        if preference not in (AGENTS | {"any"}) or type(priority) is not int or not 1 <= priority <= 1000:
            raise ValueError("Preferência/prioridade inválida")
        if not isinstance(row["title"], str) or not row["title"].strip():
            raise ValueError("Título ausente")
        prepared.append((task_id, row["title"], json.dumps(clean_scope(row["scope"])),
                         priority, preference))
    with db:
        previous = db.total_changes
        db.executemany("""INSERT OR IGNORE INTO tasks
            (id,title,scope,priority,preferred_agent) VALUES (?,?,?,?,?)""", prepared)
        return db.total_changes - previous


def claim(db, agent, minutes=60):
    if agent not in AGENTS or not 1 <= minutes <= 240:
        raise ValueError("Agente/duração inválidos")
    db.execute("BEGIN IMMEDIATE")
    try:
        active = [json.loads(r["scope"]) for r in
                  db.execute("SELECT scope FROM tasks WHERE status='running'")]
        candidates = db.execute("""SELECT * FROM tasks WHERE status='pending'
            ORDER BY CASE WHEN preferred_agent=? THEN 0 WHEN preferred_agent='any' THEN 1 ELSE 2 END,
            priority,id""", (agent,)).fetchall()
        for row in candidates:
            if row["preferred_agent"] not in (agent, "any"):
                continue
            scope = json.loads(row["scope"])
            if any(overlap(scope, other) for other in active):
                continue
            at = utcnow()
            db.execute("""UPDATE tasks SET status='running', owner=?, claimed_at=?,
                lease_until=?, attempts=attempts+1 WHERE id=?""",
                (agent, at.isoformat(), (at + timedelta(minutes=minutes)).isoformat(), row["id"]))
            db.commit()
            return dict(db.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone())
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise


def change(db, task_id, agent, action, note="", tokens_in=None, tokens_out=None):
    if agent not in AGENTS or action not in {"done", "blocked", "handoff", "heartbeat"}:
        raise ValueError("Ação/agente inválidos")
    if (tokens_in is not None and tokens_in < 0) or (tokens_out is not None and tokens_out < 0):
        raise ValueError("Tokens inválidos")
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or row["status"] != "running" or row["owner"] != agent:
            raise ValueError("Somente o responsável pode alterar uma tarefa ativa")
        if action == "heartbeat":
            db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                       ((utcnow() + timedelta(minutes=60)).isoformat(), task_id))
        elif action == "handoff":
            if not note.strip():
                raise ValueError("Handoff requer checkpoint")
            db.execute("""UPDATE tasks SET status='pending', owner=NULL, claimed_at=NULL,
                lease_until=NULL, note=?,tokens_in=COALESCE(?,tokens_in),
                tokens_out=COALESCE(?,tokens_out) WHERE id=?""",
                (note[:3000], tokens_in, tokens_out, task_id))
        else:
            db.execute("""UPDATE tasks SET status=?,finished_at=?,lease_until=NULL,
                note=?, tokens_in=COALESCE(?,tokens_in),
                tokens_out=COALESCE(?,tokens_out) WHERE id=?""",
                (action, utcnow().isoformat(), note[:3000], tokens_in, tokens_out, task_id))
        db.commit()
        return dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    except Exception:
        db.rollback()
        raise


def report(db):
    rows = [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY priority,id")]
    stamp = utcnow()
    return {
        "counts": {state: sum(r["status"] == state for r in rows) for state in sorted(STATES)},
        "stale_needs_review": [r["id"] for r in rows if r["status"] == "running"
            and r["lease_until"] and datetime.fromisoformat(r["lease_until"]) < stamp],
        "tokens_reported": {
            "input": sum(r["tokens_in"] or 0 for r in rows),
            "output": sum(r["tokens_out"] or 0 for r in rows)},
        "tasks": rows
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON coop: fila offline multiagente")
    parser.add_argument("--db", type=Path, help="Padrão: git-common-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("seed")
    p.add_argument("manifest", type=Path)
    p = sub.add_parser("claim")
    p.add_argument("--agent", choices=sorted(AGENTS), required=True)
    p.add_argument("--minutes", type=int, default=60)
    for command in ("done", "blocked", "handoff", "heartbeat"):
        p = sub.add_parser(command)
        p.add_argument("--id", required=True)
        p.add_argument("--agent", choices=sorted(AGENTS), required=True)
        p.add_argument("--note", default="")
        p.add_argument("--input-tokens", type=int)
        p.add_argument("--output-tokens", type=int)
    sub.add_parser("report")
    args = parser.parse_args(argv)
    try:
        with connect(args.db or default_db()) as db:
            if args.command == "seed":
                result = {"added": seed(db, json.loads(args.manifest.read_text(encoding="utf-8")))}
            elif args.command == "claim":
                result = {"task": claim(db, args.agent, args.minutes)}
            elif args.command == "report":
                result = report(db)
            else:
                result = change(db, args.id, args.agent, args.command, args.note,
                                args.input_tokens, args.output_tokens)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"NIVON coop: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
