"""Métricas de produtividade da engenharia, sem inferir tokens ausentes.

Todos os números são observados pelo contador de eventos da CLI. A métrica
comparativa só é mostrada quando TODOS os registros do recorte têm uso válido.
Cache é contexto reutilizado, não tokens gratuitos nem economia de assinatura.
"""
from __future__ import annotations

import argparse
import json

from nivon.cooperacao import connect, default_db, report


def _ratio(completed, input_tokens, output_tokens, missing):
    if missing or (input_tokens + output_tokens) <= 0:
        return None
    return round(completed * 100_000 / (input_tokens + output_tokens), 4)


def summarize_metrics(data):
    if not isinstance(data, dict):
        raise ValueError("Relatório inválido")
    attempts = data.get("attempts", [])
    tasks = data.get("tasks", [])
    if not isinstance(attempts, list) or not isinstance(tasks, list):
        raise ValueError("Formato de relatório inválido")
    groups = {"total": attempts}
    groups.update({
        agent: [r for r in attempts if r["agent"] == agent]
        for agent in ("claude", "codex")
    })
    result = {}
    for key, records in groups.items():
        missing = sum(type(r.get("tokens_in")) is not int or
                      type(r.get("tokens_out")) is not int for r in records)
        inputs = sum(r.get("tokens_in") or 0 for r in records)
        outputs = sum(r.get("tokens_out") or 0 for r in records)
        cached_known = all(r.get("tokens_cached") is not None for r in records)
        cached = sum(r.get("tokens_cached") or 0 for r in records)
        completed = sum(r["status"] == "done" for r in tasks) if key == "total" else sum(
            r.get("outcome") == "done" for r in records)
        result[key] = {
            "completed": completed,
            "attempts": len(records),
            "missing_usage_attempts": missing,
            "input_tokens_observed": inputs,
            "output_tokens_observed": outputs,
            "cached_input_tokens_observed": cached if cached_known and records else None,
            "completed_per_100k_tokens": _ratio(completed, inputs, outputs, missing),
            "comparability": (
                "complete" if records and missing == 0
                else "incomplete" if records else "no_attempts"),
        }
    return {
        "units": "tarefas concluídas por 100 mil tokens de entrada+saída",
        "groups": result,
        "meaning": "Não atribui economia sem antes/depois controlado; cache faz parte dos tokens processados.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Indicadores locais, não financeiros, do NIVON")
    parser.add_argument("command", choices=["report"])
    parser.parse_args(argv)
    with connect(default_db()) as db:
        data = report(db)
    print(json.dumps(summarize_metrics(data), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
