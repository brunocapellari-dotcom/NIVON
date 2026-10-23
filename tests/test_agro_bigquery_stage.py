"""Staging offline de tres fontes -> JSONL BigQuery sem PII ou upload."""
import json
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from nivon.argentina_agricultura import importar_csv_autorizado
from nivon.argentina_sio_exportacoes import PORTAL,importar_exportacao_sio
from nivon.cotacoes_agrobr_coletor import armazenar_quarentena
from nivon.agro_bigquery_stage import ErroStageAgro,exportar_stage

TS=datetime(2026,10,22,20,tzinfo=timezone.utc)
AR_CSV=('cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n'
        'Soja,2025,2025/26,Cordoba,014,Capital,00010,100,90,270,3000\n').encode()
SIO_CSV=('ID;Fecha;Producto;Cantidad;Provincia\n'
         '0001;21/10/2026;Soja;1.000,0;Cordoba\n'
         '0002;21/10/2026;Soja;500,0;Cordoba\n').encode()
MAP={'id_operacao':'ID','data_concertacao':'Fecha','produto':'Producto','toneladas':'Cantidad',
     'provincia_origem':'Provincia'}


class TestStageAgro(TestCase):
    def setUp(self):
        self.ctx=TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.root=Path(self.ctx.name)
        self.private=self.root/'out'
        self.private.mkdir(mode=0o700)
        self.db=self.root/'ingestao.db'

    def _preencher(self):
        importar_csv_autorizado(AR_CSV,banco=self.db,recurso='todos',
           edicao_id='ARG_2026_A',
           origem_url='https://datos.magyp.gob.ar/dataset/estimaciones-agricolas',
           coletado_em=TS,direitos_armazenamento_verificados=True)
        with sqlite3.connect(self.db) as db:
            armazenar_quarentena(db,fonte='IMEA',produto='soja',
               registros=[{'indicador_id':'708192508838936580','indicador':'Preço soja',
                    'localidade':'Sorriso','valor':122.5,'variacao':0.3,
                    'unidade':'R$/sc','safra':'26/27',
                    'data_publicacao':datetime(2026,10,22,18,30)}],
               metadata=SimpleNamespace(source_url='https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes',
                                        selected_source='imea'),coletado_em=TS)
            importar_exportacao_sio(db=db,arquivo=SIO_CSV,
                janela={'inicio':'2026-10-01','fim':'2026-10-22','consulta_url':PORTAL},
                colunas=MAP,chave_hmac=b'K'*32,coletado_em=TS,
                direitos_confirmados=True,layout_validado=True)

    def test_exportacao_tres_fontes_sem_ids_operacoes(self):
        self._preencher()
        path=self.private/'agro.jsonl'
        r=exportar_stage(banco=self.db,saida=path)
        self.assertEqual(r['linhas'],6) # 4 medidas SAGyP, IMEA 1, SIO agregado 1
        self.assertEqual(r['por_fonte'],{'ARG_SAGYP':4,'IMEA':1,'ARG_SIO_GRANOS':1})
        rows=[json.loads(x) for x in path.read_text().splitlines()]
        self.assertEqual(len(rows),6)
        self.assertEqual({x['status'] for x in rows},{'QUARENTENA_NAO_PUBLICAVEL'})
        sio=next(x for x in rows if x['source_id']=='ARG_SIO_GRANOS')
        self.assertEqual(sio['valor'],'1500.0')
        self.assertNotIn('id_hmac',str(rows))
        self.assertNotIn('id_operacao',path.read_text())
        self.assertNotIn('id_hmac',path.read_text())
        self.assertEqual(sio['classe'],'DECLARADO_NAO_ENTREGUE')
        self.assertIsNone(sio['data_declaracao'])
        self.assertIn('SEM_DATA_DECLARACAO',sio['qualidade'])
        self.assertFalse(r['google_cloud_gravado'])

    def test_stage_idempotente_mesma_origem(self):
        self._preencher()
        path=self.private/'agro.jsonl'
        a=exportar_stage(banco=self.db,saida=path)
        b=exportar_stage(banco=self.db,saida=path)
        self.assertEqual(a['sha256_jsonl'],b['sha256_jsonl'])
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_sem_dados_nao_cria_jsonl(self):
        with sqlite3.connect(self.db) as db:
            db.execute('create table exemplo(x)')
        path=self.private/'agro.jsonl'
        with self.assertRaises(ErroStageAgro):
            exportar_stage(banco=self.db,saida=path)
        self.assertFalse(path.exists())

    def test_pasta_nao_privada_recusada(self):
        self._preencher()
        self.root.chmod(0o755)
        path=self.root/'publico.jsonl'
        with self.assertRaises(ErroStageAgro):
            exportar_stage(banco=self.db,saida=path)
        self.root.chmod(0o700)

    def test_nao_exporta_arquivo_simbolico(self):
        self._preencher()
        original=self.private/'origem.jsonl'
        original.write_text('nao tocar')
        link=self.private/'stage.jsonl'
        link.symlink_to(original)
        with self.assertRaises(ErroStageAgro):
            exportar_stage(banco=self.db,saida=link)
        self.assertEqual(original.read_text(),'nao tocar')


if __name__=='__main__':
    import unittest
    unittest.main()
