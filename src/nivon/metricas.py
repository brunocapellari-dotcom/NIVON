"""Métricas verificáveis de tokens por tentativa, sem executar CLIs nem rede.

O formato de Claude (JSON único) e Codex (JSONL) difere. Tokens de cache
já estão INCLUÍDOS no input do Codex, mas são campos separados em Claude.
Nunca inferir economia, custo em dinheiro ou taxa de cache de dados ausentes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 20_000


def _integer(value):
    return value if type(value) is int and value >= 0 else None


def _normalize(usage, agent):
    if not isinstance(usage, dict):
        return None
    used_in = _integer(usage.get("input_tokens"))
    used_out = _integer(usage.get("output_tokens"))
    if used_in is None or used_out is None:
        return None
    if agent == "claude":
        read = _integer(usage.get("cache_read_input_tokens"))
        creation = _integer(usage.get("cache_creation_input_tokens"))
        total = used_in + (read or 0) + (creation or 0)
        return {"input": total, "output": used_out,
                "cached_input": read, "cache_creation": creation}
    if agent == "codex":
        cached = _integer(usage.get("cached_input_tokens"))
        if cached is not None and cached > used_in:
            return None
        return {"input": used_in, "output": used_out,
                "cached_input": cached, "cache_creation": None}
    return None


def parse_text(content, agent):
    """Return observed usage or None; no heuristic estimates from token count."""
    if agent not in {"claude", "codex"}:
        raise ValueError("Agente inválido")
    if len(content.encode("utf-8")) > MAX_LOG_BYTES:
        return None
    if agent == "claude":
        try:
            value = json.loads(content)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, dict) or value.get("type") not in (None, "result"):
            return None
        result = _normalize(value.get("usage"), agent)
        return dict(result, source="claude_json") if result else None

    total = {"input": 0, "output": 0, "cached_input": 0}
    count = 0
    cached_unknown = False
    for index, line in enumerate(content.splitlines()):
        if index >= MAX_EVENTS:
            return None
        if not line.lstrip().startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        values = _normalize(event.get("usage"), agent)
        if values is None:
            continue
        count += 1
        total["input"] += values["input"]
        total["output"] += values["output"]
        if values["cached_input"] is None:
            cached_unknown = True
        else:
            total["cached_input"] += values["cached_input"]
    if not count:
        return None
    return {"input": total["input"], "output": total["output"],
            "cached_input": None if cached_unknown else total["cached_input"],
            "cache_creation": None, "source": "codex_completed_jsonl",
            "completed_turns": count}


def parse_file(path, agent):
    """Do not read arbitrarily big logs into memory; original remains local."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_LOG_BYTES:
            return None
        return parse_text(path.read_text(encoding="utf-8", errors="replace"), agent)
    except OSError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: consumo de tokens reportado pela CLI")
    parser.add_argument("file", type=Path)
    parser.add_argument("--agent", choices=["claude", "codex"], required=True)
    args = parser.parse_args(argv)
    result = parse_file(args.file, args.agent)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
