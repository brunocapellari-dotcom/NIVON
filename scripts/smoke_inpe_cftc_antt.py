"""Uma consulta explícita e segura em fonte pública, sem cron nem banco.

Exemplos:
  PYTHONPATH=src python scripts/smoke_inpe_cftc_antt.py --fonte inpe --data 2026-10-20 --executar
  PYTHONPATH=src python scripts/smoke_inpe_cftc_antt.py --fonte cftc --data 2026-10-20 --mercado SOYBEANS --executar
  PYTHONPATH=src python scripts/smoke_inpe_cftc_antt.py --fonte antt --executar
O catálogo central continua OFF mesmo após esta consulta de diagnóstico.
"""
from __future__ import annotations
import argparse
import json
from nivon.consultas_fontes_publicas import (
    consultar_cftc, consultar_inpe_focos, consultar_antt_trafego,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description="NIVON: uma chamada pública, sem persistência")
    ap.add_argument("--fonte", choices=("inpe", "cftc", "antt"), required=True)
    ap.add_argument("--data", help="data de referência AAAA-MM-DD")
    ap.add_argument("--mercado", choices=("SOYBEANS", "CORN", "WHEAT",
                                         "SOYBEAN OIL", "SOYBEAN MEAL", "COTTON"))
    ap.add_argument("--executar", action="store_true")
    args = ap.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado": "BLOQUEADO_SEM_FLAG_EXECUTAR"}, ensure_ascii=False))
        return 2
    if args.fonte in ("inpe", "cftc") and not args.data:
        ap.error("--data obrigatória para CFTC e INPE")
    if args.fonte == "cftc" and not args.mercado:
        ap.error("--mercado obrigatório para CFTC")
    try:
        if args.fonte == "inpe":
            out = consultar_inpe_focos(data=args.data, executar=True)
        elif args.fonte == "cftc":
            out = consultar_cftc(data=args.data, mercado=args.mercado, executar=True)
        else:
            out = consultar_antt_trafego(executar=True)
        d, a = out["dados"], out["aquisição"]
        print(json.dumps({
            "estado": "RESPOSTA_PONTUAL_NORMALIZADA_SEM_PERSISTENCIA",
            "fonte": args.fonte, "dataset_id": d["dataset_id"],
            "quantidade": d.get("total_retorno", d.get("quantidade",
                          len(d.get("pacotes_retorno", [])))),
            "coleta": a["coletado_em"], "sha256": a["sha256"],
            "byte_count": a["bytes"], "publicacao_aprovada": False,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Não emitir valores nem URL potencialmente sensível nos logs.
        print(json.dumps({"estado": "FALHA_NAO_HOMOLOGADA",
                          "fonte": args.fonte, "classe_erro": type(exc).__name__},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
