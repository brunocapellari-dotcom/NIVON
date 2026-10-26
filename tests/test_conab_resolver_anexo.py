"""CONAB: fluxo de endereços reais da página semanal ao download XLSX.

HTML sintético com URLs e títulos confirmados no portal gov.br em 23/10/26.
Não representa captura de bytes oficiais.
"""
from datetime import datetime,timezone
import sqlite3
import unittest

from nivon.auditoria_publicacao_conab import validar_publicacao_conab,ErroProvenienciaConab
from nivon.conab_indice_progresso import INDICE, extrair_edicoes_indice,ErroIndiceConab
from nivon.conab_fila_publicacoes import atualizar_fila,proximos_arquivos
from nivon.conab_resolver_anexo import (
    resolver_html_documento,montar_registro_captura,registrar_resolucao
)

SEMANA=INDICE+'/acompanhamento-das-lavouras-12-10-a-18-10-26'
DOC=SEMANA+'/plantio-e-colheita-10-10-a-16-10/view'
ARQUIVO=SEMANA+'/plantio-e-colheita-10-10-a-16-10/@@download/file'
AGORA=datetime(2026,10,23,11,0,tzinfo=timezone.utc)
INDEX_HTML=f'<html><title>Conab</title><a href="{SEMANA}">Acompanhamento das Lavouras - 12/10 a 18/10/26</a></html>'.encode()
SEM_HTML=f'<html><title>Conab</title><a href="{DOC}">Plantio e Colheita 10-10 a 16-10</a></html>'.encode()
VIS_HTML=('<html><title>Conab - Plantio e Colheita</title>'
          '<p>Publicado em 19/10/2026 17h28</p>'
          '<a href="@@download/file">Plantio e Colheita 10-10 a 16-10.xlsx</a>'
          '</html>').encode()


class TestResolverConab(unittest.TestCase):
    def test_fluxo_indice_pagina_view_manifesto_evidencia(self):
        db=sqlite3.connect(':memory:')
        indice=extrair_edicoes_indice(INDEX_HTML,coletado_em=AGORA)
        atualizar_fila(db,indice=indice,paginas={SEMANA:SEM_HTML})
        candidato=proximos_arquivos(db)[0]
        self.assertEqual(candidato['url'],DOC)
        r=resolver_html_documento(VIS_HTML,pagina_semana=SEMANA,
                        url_documento=candidato['url'],coletado_em=AGORA)
        self.assertEqual(r['url_anexo'],ARQUIVO)
        self.assertEqual(r['publicacao_data'],'2026-10-19')
        self.assertEqual(registrar_resolucao(db,resolucao=r)['novo'],True)
        self.assertEqual(registrar_resolucao(db,resolucao=r)['novo'],False)
        reg=montar_registro_captura(indice_semana=indice['edicoes_candidatas'][0],
                                   resolucao=r)
        checked=validar_publicacao_conab(reg)
        self.assertEqual(checked['id_edicao'],'CONAB_PROG_2026_10_18')
        self.assertEqual(checked['url_pagina'],SEMANA)
        self.assertEqual(checked['url_anexo'],ARQUIVO)
        self.assertEqual(checked['semana_planilha'],'2026-10-16')
        self.assertIsNone(reg['conteudo_sha256_verificado'])
        self.assertFalse(checked['acesso_ao_anexo_comprovado'])
        db.close()

    def test_nao_confunde_view_com_url_de_bytes(self):
        with self.assertRaises(ErroProvenienciaConab):
            validar_publicacao_conab({
                'id_edicao':'CONAB_PROG_2026_10_18',
                'url_pagina':SEMANA,'url_anexo':DOC,
                'publicacao_data':'2026-10-19',
                'pagina_inicio':'2026-10-12','pagina_fim':'2026-10-18',
                'planilha_inicio':'2026-10-10','planilha_fim':'2026-10-16',
                'conteudo_sha256_verificado':None
            })

    def test_anexo_ou_pagina_estranha_reprovados(self):
        evil=VIS_HTML.replace(b'@@download/file',b'https://example.org/planilha.xlsx')
        with self.assertRaises(ErroIndiceConab):
            resolver_html_documento(evil,pagina_semana=SEMANA,url_documento=DOC,
                                    coletado_em=AGORA)
        with self.assertRaises(ErroIndiceConab):
            resolver_html_documento(VIS_HTML,pagina_semana=SEMANA,
                                    url_documento='https://evil.invalid/documento',
                                    coletado_em=AGORA)

    def test_data_ambigua_e_documento_pdf_nao_homologam_xlsx(self):
        with self.assertRaises(ErroIndiceConab):
            resolver_html_documento(VIS_HTML.replace(b'Publicado em 19/10/2026 17h28',
                b'Publicado em 19/10/2026 17h28 Publicado em 18/10/2026 12h10'),
                pagina_semana=SEMANA,url_documento=DOC,coletado_em=AGORA)
        with self.assertRaises(ErroIndiceConab):
            resolver_html_documento(VIS_HTML.replace(b'.xlsx',b'.pdf'),
                pagina_semana=SEMANA,url_documento=DOC,coletado_em=AGORA)

if __name__=='__main__':
    unittest.main()
