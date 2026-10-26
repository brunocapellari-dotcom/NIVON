"""Inventário do NIVON por METADADOS. Dry-run sem rede por padrão."""
import argparse
import json
import sys
from nivon.prontidao_golive_piloto import (
    PROJETO,DATASET,BUCKET,REGIAO,consultar_metadados
)


def main(argv=None):
    p=argparse.ArgumentParser(description="Gate GCP read-only do piloto ANTT")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado":"PLANO_SEM_REDE",
                          "projeto":PROJETO,"dataset":DATASET,
                          "bucket":BUCKET,"regiao":REGIAO,
                          "libera_deploy":False,"libera_whatsapp":False}))
        return 0
    try:
        from google.cloud import bigquery,storage
        from google.api_core.exceptions import NotFound
        from nivon.agro_bigquery_loader import _TIPOS
        r=consultar_metadados(bq=bigquery.Client(project=PROJETO),
            storage=storage.Client(project=PROJETO),
            erro_nao_encontrado=NotFound,tipos_stage=_TIPOS)
        print(json.dumps(r,ensure_ascii=False,sort_keys=True))
        return 0 if r["estado"]=="PILOTO_DADOS_READONLY_PRONTO" else 2
    except Exception as exc:
        # Nunca ecoar exceção de IAM, projeto, tokens ou credencial.
        print(json.dumps({"estado":"GCP_READONLY_NAO_COMPROVADO",
                          "tipo_erro":type(exc).__name__,
                          "libera_deploy":False,"libera_whatsapp":False}),
              file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
