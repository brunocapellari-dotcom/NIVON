"""Ponte CONAB com RAW XLSX sintetico e normalizador preexistente; sem rede."""
from datetime import datetime,timezone
from hashlib import sha256
from io import BytesIO
import json
import unittest
from zipfile import ZipFile,ZIP_DEFLATED

from nivon.conab_agrobr import normalizar_progresso
from nivon.conab_fila_publicacoes import atualizar_fila
from nivon.conab_indice_progresso import INDICE,extrair_edicoes_indice
from nivon.conab_ingestao_xlsx import (
    processar_xlsx_local, ErroIngestaoConab,
)
from nivon.registro_snapshots import abrir_registro

SEMANA=INDICE+'/acompanhamento-das-lavouras-12-10-a-18-10-26'
LINK=SEMANA+'/plantio-e-colheita-10-10-a-16-10'
XLSX=SEMANA+'/plantio-e-colheita-10-10-a-16-10.xlsx'
TS='2026-10-22T20:00:00+00:00'
IDX=f'<html><title>CONAB</title><a href="{SEMANA}">Acompanhamento das Lavouras - 12/10 a 18/10/26</a></html>'.encode()
PAG=f'<html><title>Conab</title><a href="{LINK}">Plantio e Colheita 10-10 a 16-10</a></html>'.encode()
CAT={'datasets':[{'id':'CONAB_PROGRESSO_SEMANAL','source_id':'CONAB','enabled':False,'collection_authorized':False}]}


def fixture_xlsx():
    buff=BytesIO()
    with ZipFile(buff,'w',ZIP_DEFLATED) as f:
        f.writestr('[Content_Types].xml','<Types/>')
        f.writestr('xl/workbook.xml','<workbook/>')
    return buff.getvalue()


def normalizador_mock(payload,*,sha256_origem,url_origem,coletado_em,publicado_em):
    assert sha256(payload).hexdigest()==sha256_origem
    assert publicado_em is None
    r=normalizar_progresso([{
        'cultura':'Soja','safra':'2026/27','operacao':'Semeadura',
        'uf':'MT','semana_atual':'2026-10-16',
        'pct_semana_atual':0.24,'pct_semana_anterior':0.19,
        'pct_ano_anterior':0.14,'pct_media_5_anos':0.20,
    }],fonte_url=url_origem,coletado_em=datetime.fromisoformat(coletado_em))
    row=dict(r[0])
    row.pop('coleta')
    return {'raw_sha256':sha256_origem,'parser_id':'MOCK_SINTETICO',
            'mapa_semantico':{'chave-testada':json.dumps(row)}}


class TestIngestaoXlsxConab(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro()
        indice=extrair_edicoes_indice(IDX,coletado_em=datetime.fromisoformat(TS))
        atualizar_fila(self.db,indice=indice,paginas={SEMANA:PAG})

    def tearDown(self):
        self.db.close()

    def _run(self,**extra):
        d={'pagina_url':SEMANA,'url_candidata':LINK,'url_arquivo':XLSX,
           'arquivo':fixture_xlsx(),'coletado_em':TS,'parser_sintetico':normalizador_mock}
        d.update(extra)
        return processar_xlsx_local(self.db,CAT,**d)

    def test_xlsx_para_store_versionado_duas_execucoes(self):
        r=self._run()
        self.assertEqual(r['observacoes'],1)
        self.assertFalse(r['publicacao_permitida'])
        self.assertTrue(r['snapshot_local']['hash_conferido_com_bytes'])
        self.assertTrue(r['snapshot_local']['nova_versao'])
        r2=self._run()
        self.assertFalse(r2['snapshot_local']['nova_versao'])
        self.assertFalse(r2['snapshot_local']['nova_coleta'])
        self.assertEqual(self.db.execute('select count(*) from nivon_conab_progresso').fetchone()[0],1)
        self.assertEqual(self.db.execute('select count(*) from nivon_snapshots').fetchone()[0],1)

    def test_sem_fila_nao_persiste(self):
        with self.assertRaises(ErroIngestaoConab):
            self._run(url_candidata=SEMANA+'/outro')
        self.assertEqual(self.db.execute('select count(*) from nivon_snapshots').fetchone()[0],0)

    def test_url_fora_da_edicao_recusa(self):
        with self.assertRaises(ErroIngestaoConab):
            self._run(url_arquivo='https://www.gov.br/fora-da-edicao/data.xlsx')

    def test_real_nao_permite_parser_mock_ou_catalogo_off(self):
        with self.assertRaises(PermissionError):
            self._run(modo='REAL_AUTORIZADO',direitos_armazenamento=True,
                      autorizacoes=frozenset({'COLETA','ARMAZENAMENTO'}),evidencia_direitos='contrato/2026')
        with self.assertRaises(PermissionError):
            self._run(modo='REAL_AUTORIZADO')

    def test_resultado_parser_tem_que_vincular_bytes(self):
        def adulterado(*args,**kwargs):
            return {**normalizador_mock(*args,**kwargs),'raw_sha256':'0'*64}
        with self.assertRaises(ErroIngestaoConab):
            self._run(parser_sintetico=adulterado)
        self.assertEqual(self.db.execute('select count(*) from nivon_snapshots').fetchone()[0],0)

    def test_pdf_nao_passaria_parser_concreto(self):
        with self.assertRaises(Exception):
            self._run(arquivo=b'%PDF-1.5',parser_sintetico=None)


if __name__=='__main__':
    unittest.main()
