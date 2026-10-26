"""Ligar quarentena de XLSX real CONAB a stage BigQuery sem ativar cloud."""
import json
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase

from nivon.conab_quarentena_real import _SCHEMA
from nivon.agro_bigquery_stage import exportar_stage
from nivon.agro_bigquery_loader import validar_lote


class TestQuarentenaConabParaStage(TestCase):
    def test_uma_edicao_quarentena_gera_quatro_metricas_em_stage(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            pasta=root/'privado'
            pasta.mkdir(mode=0o700)
            banco=root/'conab.db'
            with sqlite3.connect(banco) as db:
                db.executescript(_SCHEMA)
                db.execute('INSERT INTO conab_real_edicoes_quarentena VALUES (?,?,?,?,?,?,?,?,?,?)',
                    ('CONAB_PROG_2026_10_18','a'*64,
                     'https://www.gov.br/conab/edicao',
                     'https://www.gov.br/conab/arquivo',
                     '2026-10-19','2026-10-16','2026-10-23T12:26:00+00:00',
                     1,'NIVON_PROGRESSO_XLSX_OOXML_V1','QUARENTENA_DADO_REAL_NAO_HOMOLOGADO'))
                obs={'dataset_id':'CONAB_PROGRESSO_SEMANAL',
                     'operacao':'Semeadura','cultura':'Soja',
                     'safra':'2026/27','uf':'MT','competencia':'2026-10-16',
                     'source_url':'https://www.gov.br/conab/arquivo',
                     'pct_semana_atual':0.12,'pct_semana_anterior':0.08,
                     'pct_ano_anterior':0.22,'pct_media_5_anos':0.11}
                db.execute('INSERT INTO conab_real_observacoes_quarentena VALUES (?,?,?,?)',
                           ('CONAB_PROG_2026_10_18','a'*64,'chave',
                            json.dumps(obs)))
            arquivo=pasta/'stage.jsonl'
            stage=exportar_stage(banco=banco,saida=arquivo)
            self.assertEqual(stage['linhas'],4)
            self.assertEqual(stage['por_fonte'],{'CONAB':4})
            self.assertEqual(validar_lote(arquivo)['linhas'],4)
            rows=[json.loads(x) for x in arquivo.read_text().splitlines()]
            self.assertEqual({x['status'] for x in rows},{'QUARENTENA_NAO_PUBLICAVEL'})
            self.assertEqual({x['data_publicacao_original'] for x in rows},{'2026-10-19'})
            self.assertEqual({x['data_publicacao'] for x in rows},{'2026-10-19'})
            self.assertEqual({x['data_referencia'] for x in rows},{'2026-10-16'})
            self.assertTrue(all(x['data_coleta']==x['coletado_utc'] for x in rows))
            self.assertEqual({x['source_sha256'] for x in rows},{'a'*64})
            self.assertTrue(all(x['classe']=='INFORMADO_QUARENTENA' for x in rows))

if __name__=='__main__':
    import unittest
    unittest.main()
