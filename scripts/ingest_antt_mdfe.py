"""CLI para importar recortes agregados ANTT MDF-e/RNTRC em SQLite."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from nivon.antt_mdfe_volumes import baixar_csv_oficial, importar, resumo

def main(argv=None):
    parser = argparse.ArgumentParser(description="Importar exportação CSV agregada ANTT MDF-e")
    fonte = parser.add_mutually_exclusive_group(required=True)
    fonte.add_argument("--csv", help="arquivo CSV exportado do painel oficial")
    fonte.add_argument("--url-oficial", help="URL CSV oficial confirmada em dados.antt.gov.br")
    parser.add_argument("--db", required=True)
    parser.add_argument("--recorte", required=True, help="ID estável do universo de filtros")
    parser.add_argument("--nivel", required=True, choices=("MUNICIPIO", "RGI"))
    parser.add_argument("--competencia-resumo", help="consulta da competência AAAA-MM")
    args = parser.parse_args(argv)
    try:
        bruto = Path(args.csv).read_bytes() if args.csv else baixar_csv_oficial(args.url_oficial)
        resultado = importar(args.db, bruto, arquivo=args.csv or args.url_oficial,
                             recorte=args.recorte, nivel=args.nivel)
        if args.competencia_resumo:
            resultado["resumo"] = resumo(args.db, args.recorte, args.competencia_resumo)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"estado": "FALHA_SEM_PERSISTENCIA", "tipo": type(exc).__name__}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
