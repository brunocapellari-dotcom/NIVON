import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nivon.argentina_magyp import CATALOGO, persistir_raw
from nivon.arquivo_raw_gcs import preparar_manifesto, arquivar_gcs
from test_argentina_magyp import CAT, CSV
from test_arquivo_raw_gcs import Client

class TestLedger(unittest.TestCase):
    def test_e2e_coleta_ledger_gcs_simulado_sem_duplicar(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            def transporte(url, limite): return CAT if url == CATALOGO else CSV
            args = dict(destino=base/'snapshots', banco=base/'ledger.sqlite',
                        raw_dir=base/'raw', transporte=transporte)
            primeiro = persistir_raw(**args)
            persistir_raw(**args)
            with sqlite3.connect(args['banco']) as db:
                self.assertEqual(db.execute('select count(*) from snapshots').fetchone()[0], 2)
                self.assertEqual(db.execute('select count(*) from observacoes').fetchone()[0], 0)
                self.assertEqual(db.execute('select distinct estado from snapshots').fetchall(), [('QUARANTINED',)])
            cloud = dict(banco=args['banco'], raw_dir=args['raw_dir'], bucket='nivon-raw-archive',
                         snapshot_ids=[x['snapshot_id'] for x in primeiro['snapshots']])
            self.assertEqual(preparar_manifesto(**cloud)['quantidade'], 2)
            client = Client()
            a = arquivar_gcs(**cloud, client=client, executar=True)
            b = arquivar_gcs(**cloud, client=client, executar=True)
            self.assertEqual((a['novos'], b['ja_existiam']), (2, 2))
            self.assertFalse(b['bigquery_executado'])
            pasta = args['destino']/primeiro['manifesto']['sha256']
            m = json.loads((pasta/'manifest.json').read_text())
            m['registros'] += 1
            (pasta/'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError): persistir_raw(**args)

    def test_cli_dry_run_e_gate_antes_http(self):
        path = Path(__file__).parents[1]/'scripts/coletar_argentina_magyp.py'
        spec = importlib.util.spec_from_file_location('coletor_arg', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp, patch.object(mod, 'persistir_raw') as coletar:
            base = Path(tmp)/'nao_criar'
            self.assertEqual(mod.executar(base=base)['estado'], 'PLANO_SEM_REDE')
            with patch.dict('os.environ', {}, clear=True):
                with self.assertRaises(PermissionError):
                    mod.executar(base=base, executar=True, gcs=True, bucket='nivon-raw-archive')
            coletar.assert_not_called()
            self.assertFalse(base.exists())
