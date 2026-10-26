"""Coleta privada das estimativas agrícolas oficiais argentinas (CC BY 4.0)."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

CATALOGO = 'https://datos.magyp.gob.ar/api/3/action/package_show?id=estimaciones-agricolas'
RECURSO = '95d066e6-8a0f-4a80-b59d-6f28f88eacd5'
LIMITE = 100_000_000

class SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def baixar(url: str, limite: int) -> bytes:
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'datos.magyp.gob.ar' or p.fragment or p.username:
        raise ValueError('Destino fora da fonte oficial permitida')
    with build_opener(SemRedirect).open(Request(url, headers={'User-Agent': 'NIVON/1.0'}), timeout=60) as r:
        raw = r.read(limite + 1)
    if not raw or len(raw) > limite:
        raise ValueError('Resposta vazia ou excede limite')
    return raw

def selecionar(raw: bytes) -> tuple[dict, dict]:
    envelope = json.loads(raw)
    if envelope.get('success') is not True:
        raise ValueError('Catálogo sem sucesso')
    dataset = envelope['result']
    if dataset.get('license_id') != 'CC-BY-4.0':
        raise ValueError('Licença alterada; revisar antes da coleta')
    recursos = [r for r in dataset['resources'] if r['id'] == RECURSO and r['format'].upper() == 'CSV']
    if len(recursos) != 1:
        raise ValueError('Recurso oficial ausente ou ambíguo')
    return dataset, recursos[0]

def validar(raw: bytes) -> dict:
    text = raw.decode('utf-8-sig')
    reader = csv.reader(io.StringIO(text), strict=True)
    header = next(reader)
    required = {'cultivo', 'campania', 'provincia', 'departamento',
                'superficie_sembrada_ha', 'superficie_cosechada_ha', 'produccion_tm', 'rendimiento_kgxha'}
    if len(set(header)) != len(header) or not required.issubset(header):
        raise ValueError('Esquema CSV alterado')
    count = 0
    campaigns, crops = set(), set()
    for row in reader:
        if len(row) != len(header):
            raise ValueError(f'Quantidade de colunas inválida na linha {reader.line_num}')
        item = dict(zip(header, row))
        campaigns.add(item['campania'])
        crops.add(item['cultivo'])
        count += 1
    if not count:
        raise ValueError('CSV sem registros')
    return {'registros': count, 'colunas': header, 'safras': sorted(campaigns), 'culturas': sorted(crops)}

def coletar(destino: Path, transporte=baixar) -> dict:
    if destino.is_symlink():
        raise ValueError('Diretório de saída via symlink')
    catalogo = transporte(CATALOGO, 2_000_000)
    dataset, recurso = selecionar(catalogo)
    raw = transporte(recurso['url'], LIMITE)
    qc = validar(raw)
    sha = hashlib.sha256(raw).hexdigest()
    destino.mkdir(parents=True, exist_ok=True)
    pasta = destino / sha
    manifest = {'fonte': 'MAGyP / Dirección de Estimaciones Agrícolas',
                'catalogo': CATALOGO, 'url': recurso['url'], 'recurso_id': RECURSO,
                'licenca': dataset['license_id'], 'atribuicao_obrigatoria': True,
                'coletado_em': datetime.now(timezone.utc).isoformat(),
                'modificado_fonte': recurso.get('last_modified'), 'sha256': sha,
                'natureza': 'ESTIMATIVA_OFICIAL', 'homologado': False, **qc}
    if pasta.exists():
        if pasta.is_symlink():
            raise ValueError('Snapshot via symlink')
        if hashlib.sha256((pasta / 'estimaciones.csv').read_bytes()).hexdigest() != sha:
            raise ValueError('Snapshot existente divergente')
        return json.loads((pasta / 'manifest.json').read_text())
    import tempfile, os
    with tempfile.TemporaryDirectory(dir=destino) as tmp:
        staging = Path(tmp) / 'snapshot'
        staging.mkdir()
        (staging / 'estimaciones.csv').write_bytes(raw)
        (staging / 'catalogo.json').write_bytes(catalogo)
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        os.rename(staging, pasta)
    return manifest

def persistir_raw(*, destino: Path, banco: Path, raw_dir: Path,
                  transporte=baixar) -> dict:
    """Conecta a coleta ao ledger canônico sem fabricar referência/publicação.

    CSV e metadados de licença ficam QUARANTINED, sem linhas analíticas.
    Reexecução revalida os bytes antes de arquivar e não duplica snapshots.
    """
    from .ingestao_fontes_reais import gravar_lote
    manifest = coletar(destino, transporte)
    pasta = destino / manifest['sha256']
    catalogo = (pasta / 'catalogo.json').read_bytes()
    dataset, recurso = selecionar(catalogo)
    if recurso['url'] != manifest['url'] or dataset['license_id'] != manifest['licenca']:
        raise ValueError('Metadados persistidos divergentes')
    raw = (pasta / 'estimaciones.csv').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('RAW persistido divergente')
    qc = validar(raw)
    if any(qc[k] != manifest[k] for k in qc):
        raise ValueError('Manifesto estrutural divergente')
    saida = []
    for ds, url, body, tipo in (
        ('ARGENTINA_MAGYP_CATALOGO', CATALOGO, catalogo, 'application/json'),
        ('ARGENTINA_MAGYP_ESTIMACIONES', recurso['url'], raw, 'text/csv'),
    ):
        saida.append(gravar_lote(
            banco=banco, diretorio_bruto=raw_dir, dataset_id=ds, origem=url,
            raw=body, tipo=tipo, coletado_em=manifest['coletado_em'],
            estado='QUARANTINED', registros=[]))
    return {'manifesto': manifest, 'snapshots': saida,
            'estado': 'RAW_OFICIAL_SEM_PROMOCAO_ANALITICA',
            'bigquery_executado': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destino', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(coletar(args.destino), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
