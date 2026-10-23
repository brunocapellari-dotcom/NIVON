"""Sincronizacao opt-in CONAB, sem HTTP real, com fila versionada."""
import sqlite3
from datetime import datetime,timezone
import unittest

from nivon.conab_indice_progresso import ErroIndiceConab,INDICE,extrair_edicoes_indice
from nivon.conab_sync_metadados import sincronizar_indice_conab,consultar_pagina_semana

SEMANA=INDICE+'/acompanhamento-das-lavouras-12-10-a-18-10-26'
IDX=f'<html><title>Conab</title><a href="{SEMANA}">Acompanhamento das Lavouras - 12/10 a 18/10/26</a></html>'.encode()
PAG=f'<html><title>Conab</title><a href="plantio-e-colheita-10-10-a-16-10">Plantio e Colheita 10-10 a 16-10</a></html>'.encode()

def indice_fake(*,executar,abridor=None):
    assert executar is True
    return extrair_edicoes_indice(IDX,coletado_em=datetime(2026,10,22,tzinfo=timezone.utc))

def semana_fake(url,*,executar,direitos_consulta,abridor=None):
    assert url==SEMANA and executar is True and direitos_consulta is True
    return PAG

class _Response:
    status=200
    headers={'Content-Type':'text/html; charset=UTF-8'}
    def geturl(self):return SEMANA
    def read(self,n):return PAG
    def __enter__(self):return self
    def __exit__(self,*a):return False

class _Opener:
    def open(self,req,timeout):
        self.url=req.full_url
        return _Response()

class TestSyncMetadataConab(unittest.TestCase):
    def test_e2e_sintetico_idempotente(self):
        db=sqlite3.connect(':memory:')
        kw=dict(executar=True,direitos_consulta=True,limite_paginas=2,
                consulta_indice=indice_fake,consulta_semana=semana_fake)
        primeiro=sincronizar_indice_conab(db,**kw)
        segundo=sincronizar_indice_conab(db,**kw)
        self.assertEqual(primeiro['novas_semanas'],1)
        self.assertEqual(primeiro['novos_recursos_candidatos'],1)
        self.assertEqual(segundo['novos_recursos_candidatos'],0)
        self.assertFalse(primeiro['coleta_de_planilhas'])
        self.assertEqual(primeiro['arquivos_pendentes'],1)
        db.close()

    def test_sem_autorizacao_sem_network(self):
        db=sqlite3.connect(':memory:')
        with self.assertRaises(PermissionError):
            sincronizar_indice_conab(db,consulta_indice=indice_fake,consulta_semana=semana_fake)
        self.assertEqual(db.execute('SELECT count(*) FROM sqlite_master').fetchone()[0],0)
        db.close()

    def test_url_fora_da_origem_sem_http(self):
        with self.assertRaises(ErroIndiceConab):
            consultar_pagina_semana('https://evil.invalid',executar=True,
                                   direitos_consulta=True,abridor=_Opener())

    def test_metadados_de_pagina_http_mock(self):
        abridor=_Opener()
        b=consultar_pagina_semana(SEMANA,executar=True,direitos_consulta=True,abridor=abridor)
        self.assertEqual(b,PAG)
        self.assertEqual(abridor.url,SEMANA)

    def test_nao_extrapola_limite_de_paginas(self):
        db=sqlite3.connect(':memory:')
        with self.assertRaises(ErroIndiceConab):
            sincronizar_indice_conab(db,executar=True,direitos_consulta=True,
                      limite_paginas=11,consulta_indice=indice_fake,consulta_semana=semana_fake)
        db.close()

if __name__=='__main__':
    unittest.main()
