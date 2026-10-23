"""Integração sintética CONAB índice->página->fila incremental."""
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from unittest import TestCase

from nivon.conab_indice_progresso import extrair_edicoes_indice,INDICE,ErroIndiceConab
from nivon.conab_fila_publicacoes import (
    examinar_pagina_semana, atualizar_fila, proximos_arquivos,
)

SEMANA=INDICE+'/acompanhamento-das-lavouras-12-10-a-18-10-26'
SEMANA_LINK=SEMANA+'/acompanhamento-das-lavouras-05-10-a-11-10-26'
INDICE_HTML=f'''<html><title>Conab</title>
<a href="{SEMANA_LINK}">Acompanhamento das Lavouras - 12/10 a 18/10/26</a>
</html>'''.encode()
PAGINA_HTML=f'''<html><title>Conab</title>
<a href="plantio-e-colheita-10-10-a-16-10">Plantio e Colheita 10-10 a 16-10</a>
<a href="fenologia-das-lavouras-10-10-a-16-10">Fenologia das Lavouras 10-10 a 16-10</a>
<a href="monitoramento-das-condicoes-das-lavouras">Monitoramento das Condições das Lavouras</a>
<a href="https://malicioso.com.br/recurso">Plantio e Colheita 01-01 a 07-01</a>
<a href="../fora-da-edicao">Plantio e Colheita 01-01 a 07-01</a>
<a href="plantio-e-colheita-10-10-a-16-10">Plantio e Colheita 10-10 a 16-10</a>
</html>'''.encode()
AGORA=datetime(2026,10,22,20,0,tzinfo=timezone.utc)


class TestFILAConab(TestCase):
    def _indice(self):
        return extrair_edicoes_indice(INDICE_HTML,coletado_em=AGORA)

    def test_identifica_tres_recursos_e_nao_finge_download(self):
        result=examinar_pagina_semana(PAGINA_HTML,pagina_url=SEMANA)
        self.assertEqual(len(result['recursos']),3)
        self.assertEqual(result['sha256_html'],sha256(PAGINA_HTML).hexdigest())
        self.assertEqual({r['tipo'] for r in result['recursos']},
                         {'PLANTIO_COLHEITA','FENOLOGIA','MONITORAMENTO'})
        self.assertTrue(all(r['bytes_comprovados'] is False and r['publicado_em'] is None
                            for r in result['recursos']))

    def test_fila_idempotente_e_ligada_ao_indice_existente(self):
        db=sqlite3.connect(':memory:')
        self.assertEqual(self._indice()['edicoes_candidatas'][0]['pagina_oficial'],SEMANA)
        self.assertEqual(self._indice()['edicoes_candidatas'][0]['url_observada_indice'],SEMANA_LINK)
        primeira=atualizar_fila(db,indice=self._indice(),paginas={SEMANA:PAGINA_HTML})
        self.assertEqual(primeira['novas_semanas'],1)
        self.assertEqual(primeira['novos_recursos_candidatos'],3)
        segunda=atualizar_fila(db,indice=self._indice(),paginas={SEMANA:PAGINA_HTML})
        self.assertEqual(segunda['novas_semanas'],0)
        self.assertEqual(segunda['novos_recursos_candidatos'],0)
        fila=proximos_arquivos(db)
        self.assertEqual(len(fila),3)
        self.assertTrue(all(r['url'].startswith(SEMANA+'/') for r in fila))
        self.assertTrue(all('fase' not in r for r in fila))
        db.close()

    def test_edicao_nova_sem_html_fica_pendente_ate_coleta(self):
        db=sqlite3.connect(':memory:')
        res=atualizar_fila(db,indice=self._indice(),paginas={})
        self.assertEqual(res['novas_semanas'],1)
        self.assertEqual(proximos_arquivos(db),[])
        res2=atualizar_fila(db,indice=self._indice(),paginas={SEMANA:PAGINA_HTML})
        self.assertEqual(res2['novos_recursos_candidatos'],3)
        db.close()

    def test_falha_atomica_nao_insere_metade(self):
        db=sqlite3.connect(':memory:')
        base=self._indice()
        segunda={**base['edicoes_candidatas'][0],
                 'pagina_oficial':INDICE+'/acompanhamento-das-lavouras-05-10-a-11-10-26'}
        base['edicoes_candidatas'].append(segunda)
        with self.assertRaises(ErroIndiceConab):
            atualizar_fila(db,indice=base,paginas={
                SEMANA:PAGINA_HTML,
                segunda['pagina_oficial']:b'<html>erro do provedor</html>'
            })
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conab_semanas_descobertas'").fetchone())
        db.close()

    def test_ignora_payload_externo_e_rejeita_outros(self):
        with self.assertRaises(ErroIndiceConab):
            examinar_pagina_semana(PAGINA_HTML,pagina_url='https://evil.invalid/semana')
        r=examinar_pagina_semana(b'<html>Conab</html>',pagina_url=SEMANA)
        self.assertEqual(r['recursos'],[])

    def test_conflito_mesma_edicao_nao_sobrescreve(self):
        db=sqlite3.connect(':memory:')
        indice=self._indice()
        atualizar_fila(db,indice=indice,paginas={SEMANA:PAGINA_HTML})
        outra={**indice,'edicoes_candidatas':[
            {**indice['edicoes_candidatas'][0],'titulo':'Alterado arbitrariamente'}]}
        with self.assertRaises(ErroIndiceConab):
            atualizar_fila(db,indice=outra,paginas={})
        self.assertEqual(len(proximos_arquivos(db)),3)
        db.close()


if __name__=='__main__':
    import unittest
    unittest.main()
