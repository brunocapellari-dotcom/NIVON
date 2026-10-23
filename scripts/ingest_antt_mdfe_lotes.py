"""Backfill e atualização incremental dos CSVs oficiais já exportados.
Entrada: pasta e manifesto.json. Sem rede, sem API interna do Power BI.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from nivon.antt_mdfe_volumes import importar, parse_csv, DadosANTTInvalidos

def executar(pasta: str, bd: str) -> list[dict]:
    diretorio = Path(pasta).resolve(strict=True)
    manifest = json.loads((diretorio / "manifesto.json").read_text(encoding="utf-8"))
    lotes = manifest.get("lotes")
    if not isinstance(lotes, list) or not 1 <= len(lotes) <= 1000:
        raise DadosANTTInvalidos("manifesto sem lotes válidos")
    preparados, vistos = [], set()
    for lote in lotes:
        if not isinstance(lote, dict) or set(lote) != {"arquivo", "recorte", "nivel"}:
            raise DadosANTTInvalidos("cada lote exige arquivo, recorte e nivel")
        nome = lote["arquivo"]
        if not isinstance(nome, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.csv", nome):
            raise DadosANTTInvalidos("nome de arquivo inseguro")
        destino = (diretorio / nome).resolve(strict=True)
        if destino.parent != diretorio or not destino.is_file():
            raise DadosANTTInvalidos("arquivo fora da pasta")
        recorte = lote["recorte"]
        if not isinstance(recorte, str) or recorte in vistos:
            raise DadosANTTInvalidos("recorte duplicado no manifesto")
        vistos.add(recorte)
        bruto = destino.read_bytes()
        parse_csv(bruto, nivel=lote["nivel"])
        preparados.append((nome, recorte, lote["nivel"], bruto))
    return [importar(bd, bruto, arquivo=nome, recorte=recorte, nivel=nivel)
            for nome, recorte, nivel, bruto in preparados]

def main(argv=None):
    ap = argparse.ArgumentParser(description="Backfill/ingestão incremental de lotes ANTT")
    ap.add_argument("--pasta", required=True)
    ap.add_argument("--db", required=True)
    args = ap.parse_args(argv)
    try:
        out = executar(args.pasta, args.db)
        print(json.dumps({"estado": "LOTES_PROCESSADOS", "total": len(out), "resultados": out}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"estado": "FALHA_SEM_NOVAS_IMPORTACOES", "tipo": type(exc).__name__}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
