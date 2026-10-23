"""Mapa estrutural compacto de Python para evitar releitura de arquivos inteiros.

Sem rede, modelos ou dependências extras. Os símbolos são metadados locais.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".nivon-local" / "symbols.json"


def files(root=ROOT):
    src = root / "src" / "nivon"
    return sorted(x for x in src.glob("*.py") if x.is_file() and not x.is_symlink())


def symbols(path):
    data = path.read_bytes()
    if len(data) > 500_000:
        return [], hashlib.sha256(data).hexdigest()
    try:
        parsed = ast.parse(data.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return [], hashlib.sha256(data).hexdigest()
    found = []
    for node in parsed.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("_"):
            continue
        found.append({"name": node.name, "line": node.lineno,
                      "kind": "class" if isinstance(node, ast.ClassDef) else "function"})
    return found[:150], hashlib.sha256(data).hexdigest()


def index(root=ROOT, *, cache=CACHE, write=True):
    previous = {}
    if cache.exists():
        try:
            previous = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    entries, unchanged = {}, 0
    for path in files(root):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        old = previous.get(relative)
        if isinstance(old, dict) and old.get("hash") == digest and isinstance(old.get("symbols"), list):
            entries[relative] = old
            unchanged += 1
        else:
            symbols_found, _ = symbols(path)
            entries[relative] = {"hash": digest, "symbols": symbols_found}
    if write:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return entries, unchanged


def lookup(query, *, root=ROOT, cache=CACHE, maximum=12, max_chars=1400):
    if not isinstance(query, str) or not 2 <= len(query) <= 120:
        return []
    idx, _ = index(root, cache=cache, write=True)
    needle = query.casefold()
    found = []
    for path, meta in idx.items():
        for symbol in meta["symbols"]:
            if needle in symbol["name"].casefold():
                found.append({"path": path, **symbol})
                if len(found) >= maximum:
                    return found
    return found


def capsule(task, *, root=ROOT, limit=500):
    """Provide symbol hints only when task title matches names; no file bodies."""
    if limit < 100:
        return ""
    scope = json.loads(task["scope"]) if isinstance(task["scope"], str) else task["scope"]
    words = set(re.findall(r"[\wÀ-ÿ]{5,}", task["title"].casefold()))
    result = []
    for entry in scope[:6]:
        path = root / entry
        if not path.is_file() or path.suffix != ".py" or path.is_symlink():
            continue
        values, _ = symbols(path)
        relevant = [x for x in values if any(w in x["name"].casefold() for w in words)]
        if relevant:
            listing = ",".join(f"{x['name']}@{x['line']}" for x in relevant[:4])
            result.append(entry + ": " + listing)
    output = "\n".join(result)
    return output[:limit]


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: busca AST incremental e econômica")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    p = sub.add_parser("find")
    p.add_argument("symbol")
    p.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)
    if args.cmd == "index":
        items, unchanged = index()
        result = {"files": len(items), "unchanged": unchanged,
                  "symbols": sum(len(x["symbols"]) for x in items.values())}
    else:
        result = lookup(args.symbol, maximum=max(1, min(30, args.limit)))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
