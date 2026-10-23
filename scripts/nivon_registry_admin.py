"""Operação administrativa local do registry NIVON (NUNCA executa envio).

Comandos de provisionamento/revogação EXIGEM manifesto assinado
externamente, chave raiz via variável de ambiente e --aplicar.
A raiz nunca é impressa ou gravada no SQLite.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

from nivon.registry_emissores import (
    ErroRegistry, provisionar_registro, revogar_emissor, resumo_registry,
)


def _ler_comando(caminho: str) -> dict:
    p = Path(caminho).expanduser()
    if not p.is_file() or p.stat().st_size > 8192:
        raise ValueError("arquivo de comando ausente ou excessivo")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or set(doc) != {"manifesto", "assinatura"}:
        raise ValueError("JSON administrativo exige manifesto e assinatura")
    if not isinstance(doc["manifesto"], dict):
        raise ValueError("manifesto administrativo não é objeto")
    return doc


def _chave() -> bytes:
    valor = os.environ.get("NIVON_REGISTRY_ROOT_HEX", "")
    if not valor or len(valor) > 1024:
        raise ValueError("NIVON_REGISTRY_ROOT_HEX ausente")
    try:
        chave = bytes.fromhex(valor)
    except ValueError as exc:
        raise ValueError("chave raiz hexadecimal inválida") from exc
    if len(chave) < 32:
        raise ValueError("chave raiz insuficiente")
    return chave


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Provisionamento e revogação offline de emissores da outbox")
    parser.add_argument("--banco", required=True)
    parser.add_argument("--acao", choices=("resumo", "provisionar", "revogar"),
                        required=True)
    parser.add_argument("--arquivo", help="JSON assinado por operação administrativa")
    parser.add_argument("--aplicar", action="store_true",
                        help="Executa mutação reversível somente após auditoria externa")
    args = parser.parse_args(argv)
    p = Path(args.banco).expanduser().resolve(strict=False)
    if args.acao == "resumo":
        if not p.is_file():
            print(json.dumps({"estado": "SEM_BANCO"}))
            return 0
        try:
            uri = "file:" + quote(str(p), safe="/") + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as con:
                nomes = {x[0] for x in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "nivon_registry_root" not in nomes:
                    print(json.dumps({"estado": "REGISTRY_NAO_PROVISIONADO"}))
                    return 0
                # SELECT puro; sem tentar alterar schema de arquivo read-only.
                total, ativos = con.execute("""SELECT COUNT(*),
                   SUM(CASE WHEN revogado_em IS NULL THEN 1 ELSE 0 END)
                   FROM nivon_registry_emissores""").fetchone()
                resultado = {"estado": "DIAGNOSTICO_OFFLINE",
                             "emissores": total or 0, "ativos": ativos or 0,
                             "revogados": (total or 0) - (ativos or 0)}
            print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
            return 0
        except sqlite3.DatabaseError:
            print("Falha ao consultar SQLite", file=sys.stderr)
            return 2
    if not args.arquivo:
        print("--arquivo obrigatório para operação administrativa", file=sys.stderr)
        return 2
    try:
        comando = _ler_comando(args.arquivo)
        if not args.aplicar:
            print(json.dumps({"estado": "SIMULACAO_SEM_MUTACAO",
                              "operacao": args.acao,
                              "aviso": "nenhuma assinatura foi validada nem banco alterado"}))
            return 0
        # Nenhuma conexão real de Cloud API ou credenciais de transporte.
        root = _chave()
        with sqlite3.connect(p, timeout=5) as con:
            if args.acao == "provisionar":
                out = provisionar_registro(
                    con, manifesto=comando["manifesto"],
                    assinatura=comando["assinatura"], chave_raiz=root)
            else:
                out = revogar_emissor(
                    con, evento=comando["manifesto"],
                    assinatura=comando["assinatura"], chave_raiz=root)
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, PermissionError, ErroRegistry, sqlite3.DatabaseError):
        print("Operação não aplicada: arquivo, permissão ou estado inválido",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
