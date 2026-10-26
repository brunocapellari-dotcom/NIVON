"""CONAB: teste de lote único integrado com transportes injetados.

HTML com links reais do portal (caminho confirmado); bytes de XLSX aqui
são fixture simulada e a verificação também é simulada. Não atesta fonte.
"""
import hashlib
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from nivon.conab_execucao_edicao import executar_edicao_conab
from nivon.conab_indice_progresso import INDICE,extrair_edicoes_indice

SEM=INDICE+'/acompanhamento-das-lavouras-12-10-a-18-10-26'
DOC=SEM+'/plantio-e-colheita-10-10-a-16-10/view'
ANEXO=SEM+'/plantio-e-colheita-10-10-a-16-10/@@download/file'
IND_HTML=f'<html>Conab <a href="{SEM}">Acompanhamento das Lavouras - 12/10 a 18/10/26</a></html>'.encode()
SEM_HTML=f'<html>Conab <a href="{DOC}">Plantio e Colheita 10-10 a 16-10</a></html>'.encode()
DOC_HTML=b'<html>Conab Publicado em 19/10/2026 17h28 <a href="@@download/file">Plantio e Colheita 10-10 a 16-10.xlsx</a></html>'
RAW=b'PK\x03\x04SIMULADO_NAO_OOXML'
HASH=hashlib.sha256(RAW).hexdigest()
TS=datetime(2026,10,23,13,tzinfo=timezone.utc)


class TestExecucaoEdicaoConab(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.raw=self.root/'raw'
        self.raw.mkdir(mode=0o700)
        self.db=self.root/'controle.db'
        self.downloads=0
        self.links=[]
        self.capturas=[]

    def indice(self,*,executar,abridor=None):
        self.assertTrue(executar)
        self.links.append('indice')
        return extrair_edicoes_indice(IND_HTML,coletado_em=TS)

    def pagina(self,url,*,executar,direitos_consulta,abridor=None):
        self.assertTrue(executar and direitos_consulta)
        self.links.append(url)
        if url==SEM:return SEM_HTML
        if url==DOC:return DOC_HTML
        self.fail('consulta de URL inesperada')

    def capturar(self,reg,*,destino,autoriza_requisicao,direitos_coleta_conferidos,transport=None):
        self.assertTrue(autoriza_requisicao and direitos_coleta_conferidos)
        self.assertEqual(reg['url_anexo'],ANEXO)
        self.assertEqual(reg['id_edicao'],'CONAB_PROG_2026_10_18')
        self.downloads+=1
        self.capturas.append(reg)
        root=Path(destino)
        (root/'conab_progresso_raw.xlsx').write_bytes(RAW)
        (root/'conab_captura_evidencia.json').write_text('{}')
        return {'publicacao_permitida':False,'raw_sha256':HASH}

    def verificar(self,reg,pasta):
        p=Path(pasta)
        self.assertTrue((p/'conab_progresso_raw.xlsx').exists())
        self.assertEqual(hashlib.sha256((p/'conab_progresso_raw.xlsx').read_bytes()).hexdigest(),HASH)
        return {'sha256':HASH,'observacoes':3,'publicacao_permitida':False}

    def run_one(self,**kwargs):
        settings=dict(banco=self.db,raw_dir=self.raw,autorizado=True,
            direitos_consulta=True,direitos_coleta=True,direitos_armazenamento=True,
            buscar_indice=self.indice,buscar_pagina=self.pagina,
            capturar=self.capturar,verificar=self.verificar)
        settings.update(kwargs)
        return executar_edicao_conab(**settings)

    def test_uma_execucao_tres_paginas_e_raw(self):
        resultado=self.run_one()
        self.assertEqual(resultado['status'],'CAPTURA_PONTUAL_CONAB_NAO_PUBLICAVEL')
        self.assertEqual(resultado['quantidade_observacoes'],3)
        self.assertEqual(self.downloads,1)
        self.assertEqual(self.links,['indice',SEM,DOC])
        self.assertFalse(resultado['publicado_no_nivon'])
        self.assertFalse(resultado['google_cloud_gravado'])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('select count(*) from conab_anexos_resolvidos').fetchone()[0],1)

    def test_rerun_nao_repete_download(self):
        self.run_one()
        antigo=self.run_one()
        self.assertIn('RAW_ANTERIOR',antigo['status'])
        self.assertEqual(self.downloads,1)

    def test_sem_direito_nem_http_nem_sqlite(self):
        with self.assertRaises(PermissionError):
            self.run_one(direitos_armazenamento=False)
        self.assertFalse(self.db.exists())
        self.assertEqual(self.links,[])

    def test_capture_sem_manifesto_nao_e_sucesso(self):
        def mock_vazio(reg,*,destino,autoriza_requisicao,direitos_coleta_conferidos,transport=None):
            return {'publicacao_permitida':False,'raw_sha256':HASH}
        with self.assertRaises(AssertionError):
            self.run_one(capturar=mock_vazio)
        self.assertEqual(self.downloads,0)

if __name__=='__main__':
    unittest.main()
