"""Diagnóstico local redigido da outbox NIVON (sem envio ou alterações).

Exemplo:
  PYTHONPATH=src python scripts/nivon_outbox_diagnostico.py --banco /backup/outbox.sqlite
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

from nivon.diagnostico_outbox import diagnosticar_outbox


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico offline, sem envio, da outbox")
    ap.add_argument("--banco", required=True, help="SQLite local existente")
    ap.add_argument("--somente-resumo", action="store_true")
    args = ap.parse_args(argv)
    p = Path(args.banco).expanduser().resolve(strict=False)
    if not p.is_file():
        print("SQLite não encontrado; nenhuma base foi criada", file=sys.stderr)
        return 2
    # URI somente-leitura: não criar schema, não abrir acesso HTTP.
    uri = "file:" + quote(str(p), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as con:
            resultado = diagnosticar_outbox(con)
    except (sqlite3.DatabaseError, ValueError) as exc:
        print("Falha de diagnóstico SQLite: " + type(exc).__name__, file=sys.stderr)
        return 2
    if args.somente_resumo:
        resultado = {k:v for k,v in resultado.items() if k != "edicoes"}
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
