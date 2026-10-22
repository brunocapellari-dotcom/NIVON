"""NIVON FAOSTAT QCL — backfill seletivo e opt-in com evidência sem valor de safra.

Sem --executar: nenhuma rede. Sem --sqlite: nenhuma gravação local.
A publicação em produtos do NIVON continua separada e bloqueada.
"""
from __future__ import annotations

import argparse
import json
from nivon.faostat_bulk_manifest import consultar_manifest
from nivon.faostat_qcl_stream import executar_qcl, ErroQCL


def main(argv=None):
    p=argparse.ArgumentParser(description="FAOSTAT QCL: leitura ZIP seletiva")
    p.add_argument("--pais",choices=["BRA","ARG","USA"],default="BRA")
    p.add_argument("--cultura",choices=["SOJA","MILHO","TRIGO"],default="SOJA")
    p.add_argument("--inicio",type=int,default=2023)
    p.add_argument("--fim",type=int,default=2023)
    p.add_argument("--sqlite",help="caminho para SQLite local — opt-in")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado":"BLOQUEADO_SEM_EXECUTAR"}))
        return 2
    try:
        m=consultar_manifest(executar=True)
        result=executar_qcl(manifest=m,pais=args.pais,cultura=args.cultura,
                           inicio=args.inicio,fim=args.fim,
                           executar=True,arquivo_banco=args.sqlite)
        print(json.dumps({
            "estado":"QCL_ZIP_FILTRADO_SEM_PUBLICACAO",
            "fonte":"FAOSTAT","pais":args.pais,"cultura":args.cultura,
            "ano_inicio":args.inicio,"ano_fim":args.fim,
            "linhas_varridas":result["linhas_varridas"],
            "selecionadas":result["selecionadas"],
            "sha256_zip":result["sha256_zip"],
            "bytes_zip":result["bytes_download"],
            "sqlite_local":result["persistencia"] is not None,
            "inseridas_no_stage_local":(result["persistencia"] or {}).get("inseridas",0),
            "publicacao_automatica":False,"banco_cloud_atualizado":False,
            "cron_ativado":False
        },ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"estado":"FALHA_HOMOLOGACAO_QCL",
                          "tipo_erro":type(exc).__name__,
                          "motivo":str(exc)[:100] if isinstance(exc,ErroQCL) else "FALHA_REDE_OU_FORA_PARSER"},
                         ensure_ascii=False))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
