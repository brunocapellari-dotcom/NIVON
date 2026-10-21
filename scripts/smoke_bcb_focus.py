"""Diagnóstico pontual BCB Focus anual sem salvar projeções."""
import argparse
import json
from nivon.apis_gratuitas_execucao import consultar_focus


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON Focus BCB: apenas diagnóstico manual")
    p.add_argument("--indicador", choices=("Câmbio", "Selic", "IPCA", "PIB Total"), required=True)
    p.add_argument("--inicio", required=True, help="AAAA-MM-DD")
    p.add_argument("--fim", required=True, help="AAAA-MM-DD")
    p.add_argument("--executar", action="store_true")
    args = p.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado": "CONSULTA_BLOQUEADA_SEM_EXECUTAR"}))
        return 2
    try:
        r = consultar_focus(indicador=args.indicador, inicio=args.inicio,
                            fim=args.fim, executar=True)
    except Exception as exc:
        print(json.dumps({"estado": "FALHA", "erro": type(exc).__name__}))
        return 1
    a, d = r["aquisição"], r["dados"]
    print(json.dumps({"estado": "CONSULTA_REAL_PONTUAL_SEM_PERSISTENCIA",
                      "dataset_id": d["dataset_id"],
                      "quantidade": d["quantidade"],
                      "sha256": a["sha256"], "coleta": a["coleta"],
                      "publicacao_comprovada": False,
                      "liberado_para_backtest": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
