"""Painel local e read-only da cooperação Claude Code + Codex.

Sem servidor HTTP, JavaScript, rede ou execução de modelos. A versão HTML
fica no host com permissão privada, não em arquivos versionados. Exibe
somente dados operacionais agregados, sem logs, prompts, notas ou segredos.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import tempfile
import time

from nivon.cooperacao import connect, default_db, report
from nivon.indicadores_engenharia import summarize_metrics
from nivon.janela_noturna import status as night_status
from nivon.token_guard import redact

MAX_TASKS = 16
ALLOWED_STATUS = {"pending", "running", "done", "blocked"}
HOME = Path(__file__).resolve().parents[2] / ".nivon-local"


def summary(data, night):
    """Dados para interface: nunca copiar corpo de tarefas ou notas do ledger."""
    counts = {key: int(data.get("counts", {}).get(key, 0))
              for key in ("pending", "running", "done", "blocked")}
    tasks = []
    recent = sorted(data.get("tasks", []),
                    key=lambda r: (str(r.get("finished_at") or r.get("claimed_at") or ""),
                                   str(r.get("id") or "")),
                    reverse=True)
    for row in recent[:MAX_TASKS]:
        state = row.get("status", "blocked")
        if state not in ALLOWED_STATUS:
            state = "blocked"
        tasks.append({
            "id": str(row.get("id") or "")[:80],
            "title": redact(str(row.get("title") or ""))[:150],
            "agent": row.get("owner") if row.get("owner") in {"claude", "codex"} else "unassigned",
            "status": state,
            "attempts": int(row.get("attempts") or 0),
        })
    efficiency = summarize_metrics(data)
    groups = {}
    for agent in ("claude", "codex"):
        m = efficiency["groups"][agent]
        groups[agent] = {
            "attempts": m["attempts"], "completed": m["completed"],
            "handoffs": sum(a.get("outcome") == "handoff" and a.get("agent") == agent
                            for a in data.get("attempts", [])),
            "tokens_input_observed": m["input_tokens_observed"],
            "tokens_output_observed": m["output_tokens_observed"],
            "missing_usage": m["missing_usage_attempts"],
            "tasks_per_100k_tokens": m["completed_per_100k_tokens"],
        }
    return {
        "title": "NIVON | Dueto de Desenvolvimento",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {
            "timezone": night["timezone"], "window": night["window"],
            "active": bool(night["active"]),
            "may_begin_task": bool(night["may_begin_task"]),
            "next_open": night["next_open"],
            "current_or_next_close": night["current_or_next_close"],
        },
        "counts": counts,
        "agents": groups,
        "last_tasks": tasks,
        "blocked_recovery": len(data.get("stale_needs_review", [])),
        "data_source": "SQLite local: observado, não um status remoto ou previsão",
    }


def render_html(data):
    """Escapa toda entrada do SQLite; saída HTML sem scripts/recursos externos."""
    def safe(value):
        return escape(str(value), quote=True)

    def figure(value):
        return "—" if value is None else safe(value)

    stats = "".join(
        '<div class="kpi"><div class="num">' + safe(data["counts"][name]) +
        '</div><div class="meta">' + safe(label) + "</div></div>"
        for name, label in [
            ("pending", "Na fila"), ("running", "Em execução"),
            ("done", "Concluídas"), ("blocked", "Bloqueadas")
        ]
    )
    agents = "".join(
        '<section class="agent"><div class="agenthead"><h2>' + safe(name.upper()) +
        '</h2><span>Implementador independente</span></div>'
        '<div class="big">' + safe(metric["completed"]) + ' <small>concluídas</small></div>'
        '<p>' + safe(metric["attempts"]) + ' tentativas · ' +
        safe(metric["handoffs"]) + ' transferências</p>'
        '<p>Tokens observados: ' +
        safe(metric["tokens_input_observed"] + metric["tokens_output_observed"]) + '</p>'
        '<p>Tarefas / 100 mil tokens: ' +
        figure(metric["tasks_per_100k_tokens"]) + '</p>'
        '<p>Medições ausentes: ' + safe(metric["missing_usage"]) + '</p></section>'
        for name, metric in data["agents"].items()
    )
    tasks = "".join(
        "<tr><td>" + safe(row["id"]) + "</td><td>" + safe(row["title"]) +
        "</td><td>" + safe(row["agent"]) + "</td><td>" +
        '<span class="state">' + safe(row["status"]) + "</span></td><td>" +
        safe(row["attempts"]) + "</td></tr>"
        for row in data["last_tasks"]
    ) or '<tr><td colspan="5">Nenhuma tarefa registrada neste host.</td></tr>'
    night = data["window"]
    label = ("Ativa" if night["active"] else "Inativa") + " · " + night["window"] + " " + night["timezone"]
    return ("""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>NIVON · Dueto de Desenvolvimento</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Segoe UI,Arial,sans-serif}
body{background:#101319;color:#f2f5fa;margin:0 auto;padding:24px;max-width:1100px}
h1{font-size:1.85rem;letter-spacing:-.04em;margin:0 0 8px}
h2{font-size:1.1rem;margin:0}
h3{margin-top:30px;font-size:1.05rem}
p{color:#acb7c7;line-height:1.5}
header{padding:16px 0 26px;border-bottom:1px solid #323b4b}
.window{display:inline-block;background:#232b38;border:1px solid #384254;padding:8px 12px;border-radius:30px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:25px}
.kpi,.agent{background:#1b202b;border:1px solid #30394a;border-radius:16px;padding:19px}
.kpi .num{font-weight:800;font-size:2rem}
.meta{color:#acb7c7;font-size:.86rem}
.duet{display:grid;grid-template-columns:repeat(auto-fit,minmax(275px,1fr));gap:12px;margin-top:15px}
.agenthead{display:flex;align-items:center;justify-content:space-between;gap:12px}
.agenthead span{font-size:.7rem;color:#95a3ba}
.big{font-size:2.1rem;font-weight:750;margin:24px 0 8px}
.big small{font-size:.82rem;color:#aeb9c8;font-weight:400}
table{width:100%;border-collapse:collapse;background:#1b202b;border-radius:12px;overflow:hidden}
th,td{padding:12px 14px;text-align:left;border-bottom:1px solid #30394a;font-size:.86rem;overflow-wrap:anywhere}
th{color:#bfc9d8;font-weight:600}
.tablewrap{overflow:auto}
footer{padding:25px 0;font-size:.8rem;color:#98a6b9}
</style></head><body>""" +
        "<header><h1>NIVON · Dueto de Desenvolvimento</h1>"
        "<p>Acompanhamento local de Claude Code e Codex. Não inicia agentes.</p>"
        '<span class="window">' + safe(label) + "</span></header>"
        '<div class="grid">' + stats + "</div>"
        "<h3>Produção cooperativa</h3><div class=\"duet\">" + agents + "</div>"
        "<h3>Últimas tarefas</h3><div class=\"tablewrap\"><table><thead><tr>"
        "<th>ID</th><th>Tarefa</th><th>Agente</th><th>Estado</th><th>Tentativas</th>"
        "</tr></thead><tbody>" + tasks + "</tbody></table></div>"
        "<footer>Atualizado " + safe(data["generated_at_utc"]) +
        " · " + safe(data["data_source"]) +
        " · Bloqueios de recuperação: " + safe(data["blocked_recovery"]) +
        " · Dados de tokens incompletos nunca são projetados.</footer></body></html>"
    )


def write_private(path, content):
    """Atomic, mode 0600 and no symlink destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Destino é symlink")
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".dueto-",
            dir=path.parent, delete=False
        ) as tmp:
            name = Path(tmp.name)
            os.chmod(name, 0o600)
            tmp.write(content)
        os.replace(name, path)
        os.chmod(path, 0o600)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)
    return path


def snapshot(database=None):
    with connect(database or default_db()) as db:
        return summary(report(db), night_status())


def watch(*, db=None, output=None, interval=15, minutes=120):
    """Refresh local HTML for a bounded period; does not spawn any providers."""
    if type(interval) is not int or not 2 <= interval <= 120:
        raise ValueError("Intervalo de atualização inválido")
    if type(minutes) is not int or not 1 <= minutes <= 240:
        raise ValueError("Duração do painel inválida")
    target = output or HOME / "painel-dueto.html"
    started = time.monotonic()
    updated = 0
    while True:
        write_private(target, render_html(snapshot(db)))
        updated += 1
        remaining = minutes * 60 - (time.monotonic() - started)
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    return {"updates": updated, "output": str(target), "duration_minutes": minutes}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Painel privado e offline Claude + Codex")
    parser.add_argument("command", choices=["json", "html", "watch"])
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--minutes", type=int, default=120)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "watch":
        print(json.dumps(watch(db=args.db, output=args.output,
                               interval=args.interval, minutes=args.minutes),
                         ensure_ascii=False))
        return 0
    data = snapshot(args.db)
    if args.command == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        output = write_private(args.output or HOME / "painel-dueto.html", render_html(data))
        print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
