"""CEPEA/IMEA via agrobr: fixtures sintéticas, sem rede e sem fontes de terceiros."""
import asyncio
from datetime import date,datetime,timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from nivon.cotacoes_agrobr_coletor import (
    ErroCotacoes, coletar_cotacoes, armazenar_quarentena,
)

class _Frame:
    def __init__(self,rows):self.rows=rows
    def to_dict(self,orient='records'):
        assert orient=='records'
        return self.rows


class _API:
    def __init__(self,rows,link):
        self.rows=rows
        self.url=link
        self.called=0
    async def indicador(self,product,*,return_meta=False):
        assert return_meta and product=='soja'
        self.called+=1
        return _Frame(self.rows),SimpleNamespace(source_url=self.url,selected_source='cepea')
    async def cotacoes(self,product,*,return_meta=False):
        assert return_meta and product=='soja'
        self.called+=1
        return _Frame(self.rows),SimpleNamespace(source_url=self.url,selected_source='imea')


HORA=datetime(2026,10,22,21,0,tzinfo=timezone.utc)
CEPEA=[dict(data=date(2026,10,21),produto='soja',praca='Paranaguá/PR',
            valor=123.50,unidade='BRL/sc60kg',fonte='cepea')]
IMEA=[dict(cadeia='soja',indicador_id='708192508838936580',
           indicador='Preço soja disponível compra',localidade='Sorriso',
           valor=119.2,variacao=-0.5,safra='26/27',unidade='R$/sc',
           data_publicacao=datetime(2026,10,22,19,0))]


class TestColetorAgrobr(TestCase):
    def test_cepea_persiste_versionado_e_idempotente(self):
        with TemporaryDirectory() as d:
            banco=Path(d)/'mercado.sqlite'
            api=_API(CEPEA,'https://www.cepea.esalq.usp.br/br/indicador/soja.aspx')
            kw=dict(fonte='CEPEA',produto='soja',banco=banco,executar=True,
                    direitos_consulta=True,direitos_armazenamento=True,api=api,coletado_em=HORA)
            one=asyncio.run(coletar_cotacoes(**kw))
            two=asyncio.run(coletar_cotacoes(**kw))
            self.assertTrue(one['nova_edicao'])
            self.assertFalse(two['nova_edicao'])
            self.assertFalse(one['publicacao_temporal_independente'])
            self.assertFalse(one['prova_raw_original'])
            self.assertEqual(api.called,2)
            with sqlite3.connect(banco) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM cotacao_lotes').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT count(*) FROM cotacao_linhas').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT fonte_linha FROM cotacao_linhas').fetchone()[0],'cepea')

    def test_imea_preserva_indicador_com_id_grande_e_data_local(self):
        api=_API(IMEA,'https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes')
        with TemporaryDirectory() as d:
            r=asyncio.run(coletar_cotacoes(fonte='IMEA',produto='soja',
                 banco=Path(d)/'b.sqlite',executar=True,direitos_consulta=True,
                 direitos_armazenamento=True,api=api,coletado_em=HORA))
            self.assertEqual(r['linhas'],1)
            with sqlite3.connect(Path(d)/'b.sqlite') as db:
                item=db.execute('SELECT serie_id,data_publicacao_local,valor,variacao FROM cotacao_linhas').fetchone()
                self.assertEqual(item,('IMEA_708192508838936580','2026-10-22T19:00:00','119.2','-0.5'))

    def test_cache_e_fallback_cepea_nao_saem_como_dado_oficial(self):
        with sqlite3.connect(':memory:') as db:
            meta=SimpleNamespace(source_url='https://www.noticiasagricolas.com.br/soja',
                                 selected_source='cache_fallback')
            r=armazenar_quarentena(db,fonte='CEPEA',produto='soja',
                registros=[{**CEPEA[0],'fonte':'noticias_agricolas'}],metadata=meta,coletado_em=HORA)
            self.assertTrue(r['cache_relatado'])
            self.assertEqual(db.execute('SELECT alerta FROM cotacao_linhas').fetchone()[0],
                             'PROVEDOR_ALTERNATIVO')

    def test_zero_imea_nao_e_dado_faltante(self):
        with sqlite3.connect(':memory:') as db:
            meta=SimpleNamespace(source_url='https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes',selected_source='imea')
            armazenar_quarentena(db,fonte='IMEA',produto='soja',
                registros=[{**IMEA[0],'valor':0}],metadata=meta,coletado_em=HORA)
            r=db.execute('SELECT valor,alerta FROM cotacao_linhas').fetchone()
            self.assertEqual(r,('0','ZERO_COM_SIGNIFICADO_NAO_COMPROVADO'))

    def test_bloqueia_antes_de_chamar_api(self):
        api=_API(CEPEA,'https://www.cepea.esalq.usp.br/br/indicador/soja.aspx')
        with TemporaryDirectory() as d:
            with self.assertRaises(PermissionError):
                asyncio.run(coletar_cotacoes(fonte='CEPEA',produto='soja',banco=Path(d)/'b.sqlite',api=api))
            self.assertEqual(api.called,0)
            self.assertFalse((Path(d)/'b.sqlite').exists())

    def test_recusa_host_arbitrario_e_falta_campo(self):
        with sqlite3.connect(':memory:') as db:
            with self.assertRaises(ErroCotacoes):
                armazenar_quarentena(db,fonte='IMEA',produto='soja',
                    registros=IMEA,metadata=SimpleNamespace(source_url='https://evil.invalid'),
                    coletado_em=HORA)
            meta=SimpleNamespace(source_url='https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes')
            with self.assertRaises(ErroCotacoes):
                armazenar_quarentena(db,fonte='IMEA',produto='soja',
                    registros=[{'valor':123}],metadata=meta,coletado_em=HORA)

    def test_dedupe_exato_e_preserva_preco_alterado(self):
        with sqlite3.connect(':memory:') as db:
            meta=SimpleNamespace(source_url='https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes',selected_source='imea')
            r=armazenar_quarentena(db,fonte='IMEA',produto='soja',
                     registros=[IMEA[0],dict(IMEA[0]),{**IMEA[0],'valor':130}],
                     metadata=meta,coletado_em=HORA)
            self.assertEqual(r['linhas'],2)
            self.assertEqual(db.execute('SELECT count(*) FROM cotacao_linhas').fetchone()[0],2)


if __name__=='__main__':
    import unittest
    unittest.main()
