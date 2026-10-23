"""SIO Granos: testes de janelas, formato es-AR e quarentena (sem rede)."""
import sqlite3
from datetime import datetime, timezone
from unittest import TestCase

from nivon.argentina_sio_exportacoes import (
    ErroSIO, PORTAL, planejar_periodos, importar_exportacao_sio,
)

MAPPING={
    'id_operacao':'Nro. Operacion','data_concertacao':'Fecha Concertacion',
    'produto':'Producto','toneladas':'Cantidad (TN)',
    'provincia_origem':'Provincia','moeda':'Moneda',
    'preco_por_tonelada':'Precio/TN',
}
CSV=('Nro. Operacion;Fecha Concertacion;Producto;Cantidad (TN);Provincia;Moneda;Precio/TN\n'
     '128001;21/10/2026;Soja;1.234,50;Santa Fe;ARS;300.500,00\n'
     '128002;21/10/2026;Maíz;500,00;Córdoba;USD;220,50\n').encode('utf-8')
HORA=datetime(2026,10,22,23,0,tzinfo=timezone.utc)
WINDOW={'inicio':'2026-10-01','fim':'2026-10-22','consulta_url':PORTAL}


class TestExportSIO(TestCase):
    def test_periodo_maximo_e_sem_sobreposicao(self):
        a=planejar_periodos('2025-12-31','2026-10-22',dias_por_janela=180)
        self.assertEqual(a[0]['inicio'],'2025-12-31')
        self.assertEqual(a[-1]['fim'],'2026-10-22')
        self.assertEqual(len(a),2)
        self.assertEqual(a[1]['inicio'],'2026-06-29')
        for d in a:self.assertLessEqual(
            (datetime.fromisoformat(d['fim'])-datetime.fromisoformat(d['inicio'])).days,179)

    def test_periodos_invalidos_reprovados(self):
        for kw in [
            ('2026-10-23','2026-10-22',90),('2026-01-01','2026-12-31',181),
            ('x','2026-10-22',90)]:
            with self.subTest(kw=kw):
                with self.assertRaises(ErroSIO):
                    planejar_periodos(kw[0],kw[1],dias_por_janela=kw[2])

    def test_csv_es_ar_snapshot_sqlite_versionado(self):
        db=sqlite3.connect(':memory:')
        kw=dict(db=db,arquivo=CSV,janela=WINDOW,colunas=MAPPING,chave_hmac=b'A'*32,
                coletado_em=HORA,direitos_confirmados=True,layout_validado=True)
        a=importar_exportacao_sio(**kw)
        b=importar_exportacao_sio(**kw)
        self.assertTrue(a['nova_edicao'])
        self.assertFalse(b['nova_edicao'])
        self.assertFalse(a['publicacao_automatica'])
        self.assertEqual(db.execute('SELECT count(*) FROM sio_operacoes').fetchone()[0],2)
        row=db.execute("SELECT toneladas,preco_por_tonelada FROM sio_operacoes WHERE produto='Soja'").fetchone()
        self.assertEqual(row,('1234.50','300500.00'))
        self.assertEqual(db.execute('SELECT length(id_hmac) FROM sio_operacoes LIMIT 1').fetchone()[0],64)
        db.close()

    def test_gate_sem_direitos_ou_layout(self):
        db=sqlite3.connect(':memory:')
        kw=dict(db=db,arquivo=CSV,janela=WINDOW,colunas=MAPPING,chave_hmac=b'A'*32,coletado_em=HORA)
        with self.assertRaises(PermissionError):
            importar_exportacao_sio(**kw)
        with self.assertRaises(PermissionError):
            importar_exportacao_sio(**kw,direitos_confirmados=True)
        self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0],0)
        db.close()

    def test_recusa_sem_chave_robusta_ou_sem_colunas(self):
        db=sqlite3.connect(':memory:')
        kw=dict(db=db,arquivo=CSV,janela=WINDOW,colunas=MAPPING,chave_hmac=b'123',
                coletado_em=HORA,direitos_confirmados=True,layout_validado=True)
        with self.assertRaises(ErroSIO):importar_exportacao_sio(**kw)
        with self.assertRaises(ErroSIO):
            importar_exportacao_sio(**{**kw,'chave_hmac':b'X'*32,'colunas':{'produto':'Producto'}})
        db.close()

    def test_data_ou_duplicata_nao_entram(self):
        db=sqlite3.connect(':memory:')
        kw=dict(db=db,arquivo=CSV,janela=WINDOW,colunas=MAPPING,chave_hmac=b'A'*32,
                coletado_em=HORA,direitos_confirmados=True,layout_validado=True)
        for payload in [CSV.replace(b'21/10/2026',b'01/01/2025'),
                        CSV+CSV.split(b'\n')[1]+b'\n',
                        b'<html>bad response</html>',
                        CSV.replace(b'1.234,50',b'1234.50')]:
            with self.subTest(payload=payload[:25]):
                with self.assertRaises(ErroSIO):
                    importar_exportacao_sio(**{**kw,'arquivo':payload})
        db.close()


if __name__=='__main__':
    import unittest
    unittest.main()
