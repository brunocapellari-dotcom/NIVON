"""Fixtures sinteticas. Nenhum dado argentino real nem requisicao de rede."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from nivon.argentina_agricultura import (
    ErroArgentina, RECURSOS, consultar_metadados, importar_csv_autorizado,
    interpretar_metadados, ler_linhas_csv, url_recurso,
)

AGORA = datetime(2026, 10, 22, 17, 0, tzinfo=timezone.utc)
CSV = ("cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n"
       "Soja,2025,2025/26,Córdoba,014,Capital,00010,100,90,270,3000\n").encode()

class TestArgentina(unittest.TestCase):
    def test_metadados_recurso_e_sem_download(self):
        self.assertIn(RECURSOS['soja'], url_recurso('soja'))
        payload = json.dumps({'success':True,'result':{'id':RECURSOS['soja'],
            'url':'https://dados.exemplo.org.ar/soja.csv','format':'CSV'}}).encode()
        r=interpretar_metadados(payload,recurso='soja',coletado_em=AGORA)
        self.assertIn('SEM_DOWNLOAD',r['estado'])
        self.assertNotIn('autorizado',r['url_candidata_nao_autorizada'])
        with self.assertRaises(ErroArgentina):
            interpretar_metadados(json.dumps({'success':True,'result':{'id':'outro','url':'https://x/soja.csv','format':'CSV'}}).encode(),recurso='soja',coletado_em=AGORA)

    def test_coleta_bloqueada_por_padrao(self):
        with self.assertRaises(PermissionError):
            consultar_metadados('soja')

    def test_parser_ids_zeros_e_decimal(self):
        linha=list(ler_linhas_csv(CSV))[0]
        self.assertEqual(linha['provincia_id'],'014')
        self.assertEqual(linha['departamento_id'],'00010')
        self.assertEqual(linha['produccion_tm'],'270')

    def test_parser_invalido(self):
        with self.assertRaises(ErroArgentina):
            list(ler_linhas_csv(CSV.replace(b'270,3000',b'270,NaN')))
        with self.assertRaises(ErroArgentina):
            list(ler_linhas_csv(b'<html>erro</html>'))

    def test_sqlite_atomico_idempotente_e_sem_autorizacao(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'ar.sqlite'
            kw=dict(conteudo=CSV,banco=p,recurso='soja',edicao_id='AR_2026_10_22',
                    origem_url='https://datos.magyp.gob.ar/dataset/soja-siembra-cosecha-produccion-rendimiento',
                    coletado_em=AGORA)
            with self.assertRaises(PermissionError):importar_csv_autorizado(**kw)
            r=importar_csv_autorizado(**kw,direitos_armazenamento_verificados=True)
            self.assertEqual(r['linhas'],1)
            self.assertFalse(r['publicacao_permitida'])
            self.assertEqual(importar_csv_autorizado(**kw,direitos_armazenamento_verificados=True)['status'],'DUPLICATA_IDEMPOTENTE')
            with sqlite3.connect(p) as db:
                self.assertEqual(db.execute('select count(*) from ar_estimaciones').fetchone()[0],1)
                self.assertEqual(db.execute('select disponibilidade_verificada from ar_ediciones').fetchone()[0],0)
            with self.assertRaises(ErroArgentina):
                importar_csv_autorizado(**{**kw,'conteudo':CSV.replace(b'270,3000',b'280,3000')},direitos_armazenamento_verificados=True)
            # Falha de duplicata nao persiste edicao parcial
            with self.assertRaises(ErroArgentina):
                importar_csv_autorizado(**{**kw,'edicao_id':'AR_2026_10_23','conteudo':CSV+CSV.split(b'\n',1)[1]},direitos_armazenamento_verificados=True)
            with sqlite3.connect(p) as db:
                self.assertEqual(db.execute('select count(*) from ar_ediciones').fetchone()[0],1)

if __name__=='__main__': unittest.main()
