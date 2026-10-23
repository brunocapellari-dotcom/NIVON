"""Smoke seguro e explicitamente manual de uma fonte gratuita do lote."""
import argparse
import json

from nivon.fontes_abertas_lote import FONTES, consultar

def main(argv=None):
    ap = argparse.ArgumentParser(description="Uma consulta pontual, rede OFF por padrão")
    ap.add_argument("--fonte", required=True, choices=sorted(FONTES))
    ap.add_argument("--ano", type=int, default=None)
    ap.add_argument("--executar", action="store_true")
    args = ap.parse_args(argv)
    try:
        resultado = consultar(args.fonte, ano=args.ano, executar=args.executar)
        print(json.dumps({"fonte_id": args.fonte, "status": "RESPOSTA_RECEBIDA_NAO_HOMOLOGADA",
                          "sha256_original": resultado["sha256_original"],
                          "coleta": resultado["coleta"],
                          "total_recursos": resultado.get("total_recursos"),
                          "linhas": resultado.get("linhas"),
                          "homologado": False, "persistido": False},
                         ensure_ascii=False))
        return 0
    except PermissionError:
        print(json.dumps({"fonte_id": args.fonte, "status": "BLOQUEIO_OU_CREDENCIAL_AUSENTE"}))
        return 2
    except Exception:
        # Não imprimir exceções HTTP: URL pode carregar API key na query.
        print(json.dumps({"fonte_id": args.fonte, "status": "CONSULTA_NAO_VALIDADA"}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
