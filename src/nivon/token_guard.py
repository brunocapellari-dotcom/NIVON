"""Deterministic log reduction; full evidence is kept in the input file."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

IMPORTANT = re.compile(r"(ERROR|FAIL(?:ED|URE)?|Traceback|Exception|E\s+assert|warning:)", re.I)
CREDENTIAL = re.compile(r"(?i)(api[_-]?key|token|secret|password|senha)\s*[:=]\s*[^\s,;]+")
BEARER = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]{8,}")


def redact(line):
    line = CREDENTIAL.sub(lambda match: match.group(1) + "=[REDACTED]", line)
    return BEARER.sub("Bearer [REDACTED]", line)


def summarize(text, max_chars=3800, context=1):
    if not 200 <= max_chars <= 40000:
        raise ValueError("max_chars inválido")
    lines = text.splitlines()
    selected = set(range(min(3, len(lines))))
    for i, line in enumerate(lines):
        if IMPORTANT.search(line):
            selected.update(range(max(0, i-context), min(len(lines), i+context+1)))
    if not any(IMPORTANT.search(line) for line in lines):
        selected.update(range(max(0, len(lines)-4), len(lines)))
    out = [f"Resumo determinístico: {len(lines)} linhas; log original preservado localmente."]
    previous = -1
    for i in sorted(selected):
        if i > previous + 1:
            out.append("... linhas omitidas ...")
        item = f"{i+1}: {redact(lines[i])}"
        if sum(len(x)+1 for x in out) + len(item) > max_chars-70:
            out.append("... limite de contexto atingido; consulte log completo ...")
            break
        out.append(item)
        previous = i
    return "\n".join(out)[:max_chars]


def main():
    parser = argparse.ArgumentParser(description="Reduz saída de teste sem apagar log")
    parser.add_argument("log", type=Path)
    parser.add_argument("--max-chars", type=int, default=3800)
    args = parser.parse_args()
    if not args.log.is_file():
        parser.error("log inexistente")
    print(summarize(args.log.read_text(encoding="utf-8", errors="replace"), args.max_chars))


if __name__ == "__main__":
    main()
