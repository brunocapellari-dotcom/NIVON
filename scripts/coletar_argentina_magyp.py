"""MAGyP oficial -> ledger canônico -> GCS opcional; sem carga BigQuery."""
import argparse
import json
import os
from pathlib import Path
from nivon.argentina_magyp import persistir_raw
from nivon.arquivo_raw_gcs import arquivar_gcs


def executar(*, base, executar=False, gcs=False, bucket=None):
    if not executar:
        return {'estado': 'PLANO_SEM_REDE', 'gcs_executado': False,
                'bigquery_executado': False}
    if gcs and (not bucket or os.getenv('NIVON_RAW_ARCHIVE_APPROVED') != 'true'
                or os.getenv('NIVON_ZERO_COST_BQ_APPROVED') != 'true'):
        raise PermissionError('Arquivamento/custo/destino GCS não configurados')
    base = Path(base)
    saida = persistir_raw(destino=base/'snapshots', banco=base/'fontes_reais.sqlite',
                         raw_dir=base/'raw')
    saida['gcs_executado'] = False
    if gcs:
        saida['gcs'] = arquivar_gcs(
            banco=base/'fontes_reais.sqlite', raw_dir=base/'raw', bucket=bucket,
            snapshot_ids=[x['snapshot_id'] for x in saida['snapshots']], executar=True)
        saida['gcs_executado'] = True
    return saida


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--executar', action='store_true')
    p.add_argument('--gcs', action='store_true')
    p.add_argument('--bucket')
    a = p.parse_args()
    print(json.dumps(executar(base=a.base, executar=a.executar, gcs=a.gcs,
                             bucket=a.bucket), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
