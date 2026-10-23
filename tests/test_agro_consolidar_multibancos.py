"""Fluxo E2E local: SAGyP e IMEA em SQLite separados, lotes prontos p/ preflight BQ."""
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
import sqlite3

from nivon.argentina_agricultura import importar_csv_autorizado
from nivon.cotacoes_agrobr_coletor import armazenar_quarentena
from nivon.agro_consolidar_multibancos import consolidar_sqlites, ErroConsolidacao
from nivon.agro_bigquery_loader import validar_lote, carregar_bigquery
from nivon.agro_operacao import operar_agro

AGORA=datetime(2026,10,22,21,tzinfo=timezone.utc)
CSV=('cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n'
     'Soja,2025,2025/26,Cordoba,014,Capital,00010,100,90,270,3000\n').encode()

class TestConsolidarAgro(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.output=root/'privados'
        self.output.mkdir(mode=0o700)
        self.arg=root/'arg.sqlite'
        self.imea=root/'imea.sqlite'
        importar_csv_autorizado(CSV,banco=self.arg,recurso='todos',
            edicao_id='ARG_2026_Z',origem_url='https://datos.magyp.gob.ar/dataset/estimaciones-agricolas',
            coletado_em=AGORA,direitos_armazenamento_verificados=True)
        with sqlite3.connect(self.imea) as db:
            armazenar_quarentena(db,fonte='IMEA',produto='soja',
                registros=[{'indicador_id':'708192508838936580','indicador':'Preco',
                    'localidade':'Sorriso','valor':100,'variacao':0.5,'safra':'26/27',
                    'unidade':'R$/sc','data_publicacao':datetime(2026,10,22,18)}],
                metadata=SimpleNamespace(
                    source_url='https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes',
                    selected_source='imea'),coletado_em=AGORA)

    def test_dois_sqlites_geram_lotes_jsonl_e_preflight_sem_cloud(self):
        result=consolidar_sqlites(bancos=[self.imea,self.arg],
            pasta_saida=self.output,max_linhas_por_lote=2)
        self.assertEqual(result['linhas_distintas'],5)
        self.assertEqual(result['por_fonte'],{'ARG_SAGYP':4,'IMEA':1})
        self.assertEqual(len(result['lotes']),3)
        self.assertEqual(result['linhas_duplicadas_descartadas'],0)
        for lote in result['lotes']:
            f=self.output/lote['arquivo']
            self.assertEqual(validar_lote(f)['sha256_jsonl'],lote['sha256_jsonl'])
            resposta=carregar_bigquery(arquivo=f,projeto='nivon-data',dataset='nivon_stage')
            self.assertEqual(resposta['status'],'PREFLIGHT_LOCAL_SEM_CLOUD')
        self.assertTrue((self.output/'agro-manifesto.json').is_file())
        self.assertFalse(result['cloud_write'])

    def test_operacao_unica_preflight_integrado(self):
        resposta=operar_agro(bancos=[self.arg,self.imea],
                    pasta_saida=self.output,projeto='nivon-data',dataset='nivon_stage',
                    max_linhas_por_lote=2)
        self.assertEqual(resposta['linhas_distintas'],5)
        self.assertEqual(len(resposta['lotes']),3)
        self.assertFalse(resposta['cloud_autorizado'])
        self.assertFalse(resposta['cloud_concluido'])
        self.assertEqual(resposta['estado'],'PREFLIGHT_INTEGRADO_APROVADO_SEM_REDE')

    def test_operacao_real_sem_direitos_rejeita_antes_de_preparar_lotes(self):
        with self.assertRaises(PermissionError):
            operar_agro(bancos=[self.arg,self.imea],pasta_saida=self.output,
                     projeto='nivon-data',dataset='nivon_stage',executar_cloud=True)
        self.assertFalse(list(self.output.iterdir()))

    def test_nao_sobrescreve_manifesto_existente(self):
        consolidar_sqlites(bancos=[self.imea,self.arg],pasta_saida=self.output)
        with self.assertRaises(ErroConsolidacao):
            consolidar_sqlites(bancos=[self.arg,self.imea],pasta_saida=self.output)

    def test_deduplica_mesmo_snapshot_em_bancos_separados(self):
        copiar=self.arg.with_name('arg_copia.sqlite')
        with sqlite3.connect(self.arg) as origem, sqlite3.connect(copiar) as dst:
            origem.backup(dst)
        result=consolidar_sqlites(bancos=[self.arg,copiar],pasta_saida=self.output)
        self.assertEqual(result['linhas_distintas'],4)
        self.assertEqual(result['linhas_duplicadas_descartadas'],4)

    def test_nao_aceita_publicacao_em_diretorio_nao_privado(self):
        self.output.chmod(0o755)
        with self.assertRaises(ErroConsolidacao):
            consolidar_sqlites(bancos=[self.imea],pasta_saida=self.output)

    def test_sem_entradas_validas(self):
        with self.assertRaises(ErroConsolidacao):
            consolidar_sqlites(bancos=[self.imea,self.imea],pasta_saida=self.output)

if __name__=='__main__':
    import unittest
    unittest.main()
