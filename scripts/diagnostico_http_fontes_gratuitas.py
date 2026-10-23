"""Diagnóstico HTTP PONTUAL não persistente e não paginado, com saída sanitizada.

Uso manual: python scripts/diagnostico_http_fontes_gratuitas.py --executar
Sem --executar nem variável de liberação nunca acessa rede.
"""
from __future__ import annotations

import argparse
import json
from time import monotonic
from urllib.error import HTTPError, URLError
from nivon.coleta_ckan_csv_pontual import ErroCSVCKAN
from nivon.amostra_csv_ckan_range import consultar_prefixo_ckan
from nivon.fontes_abertas_lote import ErroFonteAberta
from nivon.arquivos_publicos_lote import ErroArquivoAberto

from nivon.bcb_sicor_mdcr import consultar_sicor
from nivon.fontes_abertas_lote import consultar as consultar_catalogo

CHECKS = (
    ("BCB_SICOR_MDCR", lambda: consultar_sicor(
        entidade="RegiaoUF", limite=3, executar=True)),
    ("MAPA_ZARC", lambda: consultar_catalogo("MAPA_ZARC", executar=True)),
    ("ANTT_CIOT", lambda: consultar_catalogo("ANTT_CIOT", executar=True)),
    ("ZARC_PREFIX_2026_2027", lambda: consultar_prefixo_ckan(fonte="MAPA_ZARC", recurso_id="139e5a60-1f43-4cc8-aeab-a35dbbf816c0", executar=True)),
    ("UN_COMTRADE_PREVIEW", lambda: consultar_catalogo(
        "UN_COMTRADE_PREVIEW", ano=2025, executar=True)),
)

def main(argv=None):
    p = argparse.ArgumentParser(description="Uma rodada HTTP pública, sem persistência")
    p.add_argument("--executar", action="store_true")
    p.add_argument("--fonte", choices=["todas"] + [name for name, _ in CHECKS], default="todas")
    args = p.parse_args(argv)
    if args.executar is not True:
        print(json.dumps({"status": "REDE_DESATIVADA", "fontes_testadas": 0}))
        return 2
    good = 0
    total = 0
    for name, operation in CHECKS:
        if args.fonte != "todas" and name != args.fonte:
            continue
        start = monotonic()
        total += 1
        try:
            out = operation()
            good += 1
            result = {"fonte_id": name, "estado": "HTTP_OK_PARSER_OK_SEM_HOMOLOGACAO",
                      "sha256_full": out.get("sha256_original"),
                      "sha256_prefixo": out.get("sha256_prefixo"),
                      "colunas_amostra": out.get("colunas"),
                      "arquivo_completo": out.get("arquivo_completo"),
                      "registros": out.get("registros_recebidos", out.get(
                          "linhas", out.get("linhas_amostra_completas", out.get("linhas_amostra", out.get("total_recursos"))))),
                      "duracao_segundos": round(monotonic() - start, 2),
                      "persistido": False, "publicavel": False}
        except (ErroCSVCKAN, ErroFonteAberta, ErroArquivoAberto) as exc:
            result = {"fonte_id": name, "estado": "VALIDADOR_RECUSOU_FONTE",
                      "regra": str(exc)[:120],
                      "duracao_segundos": round(monotonic() - start, 2)}
        except HTTPError as exc:
            result = {"fonte_id": name, "estado": "HTTP_NAO_VALIDADO",
                      "http_status": exc.code,
                      "duracao_segundos": round(monotonic() - start, 2)}
        except URLError as exc:
            result = {"fonte_id": name, "estado": "REDE_NAO_VALIDADA",
                      "causa_tipo": type(exc.reason).__name__,
                      "duracao_segundos": round(monotonic() - start, 2)}
        except Exception as exc:
            result = {"fonte_id": name, "estado": "PARSER_OU_SERVICO_NAO_VALIDADO",
                      "causa_tipo": type(exc).__name__,
                      "duracao_segundos": round(monotonic() - start, 2)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(json.dumps({"sumario": "CONSULTAS_PONTUAIS_SEM_PERSISTENCIA",
                      "fontes_testadas": total, "fontes_com_parser": good}))
    return 0 if good == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
