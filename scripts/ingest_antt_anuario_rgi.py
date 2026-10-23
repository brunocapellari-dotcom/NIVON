"""E2E de importação do Anuário da ANTT em banco SQLite temporário ou autorizado."""
import argparse
import json
import sys
from pathlib import Path
from nivon.antt_anuario_rgi import executar

def main(argv=None):
    ap=argparse.ArgumentParser(description="Extrair top-16 fluxos RGI anuais ANTT")
    ap.add_argument("--db",required=True)
    ap.add_argument("--pdf-local")
    args=ap.parse_args(argv)
    try:
        bruto=Path(args.pdf_local).read_bytes() if args.pdf_local else None
        status=executar(args.db,pdf=bruto)
        print(json.dumps({k:status[k] for k in ("estado","sha256","linhas","ano","escopo")},ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"estado":"FALHA_EXTRAIR_E_PERSISTIR","classe_erro":type(exc).__name__}),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
