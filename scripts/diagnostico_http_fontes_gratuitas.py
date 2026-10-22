"""Diagnóstico HTTP PONTUAL não persistente e não paginado, com saída sanitizada.

Uso manual: python scripts/diagnostico_http_fontes_gratuitas.py --executar
Sem --executar nem variável de liberação nunca acessa rede.
"""
from __future__ import annotations

import argparse
import json
from time import monotonic

from nivon.bcb_sicor_mdcr import consultar_sicor
from nivon.fontes_abertas_lote import consultar as consultar_catalogo

CHECKS = (
    ("BCB_SICOR_MDCR", lambda: consultar_sicor(
        entidade="RegiaoUF", limite=3, executar=True)),
    ("MAPA_ZARC", lambda: consultar_catalogo("MAPA_ZARC", executar=True)),
    ("ANTT_CIOT", lambda: consultar_catalogo("ANTT_CIOT", executar=True)),
    ("UN_COMTRADE_PREVIEW", lambda: consultar_catalogo(
        "UN_COMTRADE_PREVIEW", ano=2025, executar=True)),
)

def main(argv=None):
    p = argparse.ArgumentParser(description="Uma rodada HTTP pública, sem persistência")
    p.add_argument("--executar", action="store_true")
    args = p.parse_args(argv)
    if args.executar is not True:
        print(json.dumps({"status": "REDE_DESATIVADA", "fontes_testadas": 0}))
        return 2
    good = 0
    total = 0
    for name, operation in CHECKS:
        start = monotonic()
        total += 1
        try:
            out = operation()
            good += 1
            result = {"fonte_id": name, "estado": "HTTP_OK_PARSER_OK_SEM_HOMOLOGACAO",
                      "sha256": out.get("sha256_original"),
                      "registros": out.get("registros_recebidos", out.get(
                          "linhas", out.get("total_recursos"))),
                      "duracao_segundos": round(monotonic() - start, 2),
                      "persistido": False, "publicavel": False}
        except Exception:
            # Não exibir exceções com URL, dados ou proxies/headers de rede.
            result = {"fonte_id": name, "estado": "FALHA_OU_BLOQUEIO_NAO_CLASSIFICADO",
                      "duracao_segundos": round(monotonic() - start, 2)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(json.dumps({"sumario": "CONSULTAS_PONTUAIS_SEM_PERSISTENCIA",
                      "fontes_testadas": total, "fontes_com_parser": good}))
    return 0 if good == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
