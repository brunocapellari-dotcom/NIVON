"""Importação manual de uma captura OData/PTAX para a quarentena NIVON.

Execução explícita, apenas arquivos LOCAIS. Não chama o Banco Central, não
ativará coleta recorrente nem autoriza o briefing. Para arquivo de uma
coleta externa real, gerar manifesto separado pela infraestrutura com:
moeda, URL PTAX exata, instante UTC de coleta, HTTP status, SHA-256 do
arquivo recebido e cabeçalhos HTTP. Não inventar campos ausentes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from nivon.ptax_quarentena_coleta import (
    MAX_BYTES, MAX_MANIFEST, receber_amostra_ptax, ErroQuarentenaPTAX,
)


def _arquivo(path: str, limite: int) -> bytes:
    arq = Path(path)
    if arq.is_symlink() or not arq.is_file() or arq.stat().st_size > limite:
        raise ErroQuarentenaPTAX("arquivo irregular ou acima do limite")
    with arq.open("rb") as f:
        dados = f.read(limite + 1)
    if len(dados) > limite:
        raise ErroQuarentenaPTAX("arquivo acima do limite")
    return dados


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description="Importar RAW PTAX à quarentena, sem ativação de fonte"
    )
    parser.add_argument("--raw", required=True)
    parser.add_argument("--manifesto", required=True)
    parser.add_argument("--banco", required=True)
    args = parser.parse_args(argv)
    raw = _arquivo(args.raw, MAX_BYTES)
    metadata_bytes = _arquivo(args.manifesto, MAX_MANIFEST)
    try:
        meta = json.loads(metadata_bytes.decode("utf-8", "strict"))
    except (ValueError, UnicodeError) as exc:
        raise ErroQuarentenaPTAX("manifesto JSON inválido") from exc
    caminho = Path(args.banco)
    if caminho.is_symlink() or caminho.exists() and not caminho.is_file():
        raise ErroQuarentenaPTAX("destino SQLite inseguro")
    # A operação não altera o ledger de mercado. Usa transação local.
    with sqlite3.connect(caminho) as db:
        db.execute("PRAGMA foreign_keys=ON")
        resultado = receber_amostra_ptax(db, raw=raw, manifesto=meta)
    return resultado


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True, ensure_ascii=False))
