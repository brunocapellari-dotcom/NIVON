"""Painel agro: leitura de catálogo real e SQLite sintético, sem rede."""
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from nivon.agro_prontidao_fontes import auditar_fontes_agro,ErroPainelAgro
from nivon.argentina_agricultura import importar_csv_autorizado

AGORA=datetime(2026,10,23,11,0,tzinfo=timezone.utc)
CSV=('cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n'
     'Soja,2025,2025/26,Cordoba,014,Capital,00010,100,90,270,3000\n').encode()

class TestAgroProntidao(unittest.TestCase):
    def test_catalogo_oficial_sete_fontes_e_sem_go_live(self):
        x=auditar_fontes_agro(bancos=[],agora=AGORA)
        self.assertEqual(len(x['fontes']),7)
        self.assertFalse(x['cloud_confirmado'])
        self.assertEqual(x['fontes_homologadas_em_producao'],0)
        for d in x['fontes']:
            self.assertFalse(d['coleta_ativada'])
            self.assertFalse(d['go_live_confirmado'])
            self.assertIsNone(d['ultima_coleta_local_utc'])
        s={r['dataset_id']:r for r in x['fontes']}
        self.assertEqual(s['ARG_DJVE_DECLARACOES_EXPORTACAO']['estado'],
                         'ADAPTADOR_REAL_AINDA_NAO_IMPLEMENTADO')

    def test_observacao_local_nao_homologa_fonte(self):
        with TemporaryDirectory() as p:
            bank=Path(p)/'ar.db'
            importar_csv_autorizado(CSV,banco=bank,recurso='todos',
                edicao_id='ARG_2026_Q',
                origem_url='https://datos.magyp.gob.ar/dataset/estimaciones-agricolas',
                coletado_em=AGORA,direitos_armazenamento_verificados=True)
            x=auditar_fontes_agro(bancos=[bank],agora=AGORA)
            sag=next(z for z in x['fontes'] if z['dataset_id']=='ARG_SAGYP_ESTIMACIONES_AGRICOLAS')
            self.assertEqual(sag['edicoes_locais_contadas'],1)
            self.assertEqual(sag['estado'],'EDICOES_PRESENTES_NAO_HOMOLOGADAS')
            self.assertFalse(sag['go_live_confirmado'])
            self.assertFalse(x['cloud_confirmado'])

    def test_banco_repetido_falha(self):
        with TemporaryDirectory() as p:
            bank=Path(p)/'r.db'
            sqlite3.connect(bank).close()
            with self.assertRaises(ErroPainelAgro):
                auditar_fontes_agro(bancos=[bank,bank],agora=AGORA)

if __name__=='__main__':
    unittest.main()
