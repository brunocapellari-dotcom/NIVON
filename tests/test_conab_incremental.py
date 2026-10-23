"""CONAB lote: seleção segura de duas semanas e reuso de índice offline."""
import unittest
from datetime import datetime,timezone

from nivon.conab_incremental import atualizar_conab_lote,ErroIncrementalConab
from nivon.conab_indice_progresso import extrair_edicoes_indice,INDICE

W1=INDICE+'/acompanhamento-das-lavouras-12-10-a-18-10-26'
W2=INDICE+'/acompanhamento-das-lavouras-05-10-a-11-10-26'
HTML=f'''<html>Conab
<a href="{W1}">Acompanhamento das Lavouras - 12/10 a 18/10/26</a>
<a href="{W2}">Acompanhamento das Lavouras - 05/10 a 11/10/26</a></html>'''.encode()
TS=datetime(2026,10,23,12,tzinfo=timezone.utc)


class TestIncrementalConab(unittest.TestCase):
    def test_duas_semanas_um_indice_uma_importacao(self):
        chamadas=[]
        indice=extrair_edicoes_indice(HTML,coletado_em=TS)
        def buscar(*,executar,abridor=None):
            chamadas.append('indice')
            return indice
        def captar(*,semana_fim,buscar_indice,**k):
            chamadas.append(semana_fim)
            self.assertIs(buscar_indice(executar=True),indice)
            return {'status':'CAPTURA_PONTUAL_CONAB_NAO_PUBLICAVEL',
                    'edicao_id':'ID_'+semana_fim,
                    'sha256_raw':'a'*64}
        def importar(**kwargs):
            chamadas.append('quarentena')
            return {'publicacao_permitida':False,'versoes_novas':2,
                    'observacoes_processadas':116,'arquivos_importados':2}
        a=atualizar_conab_lote(banco='mock',raw_dir='mock',quantidade=2,
            executar=True,direitos_consulta=True,direitos_coleta=True,
            direitos_armazenamento=True,buscar_indice=buscar,
            executar_semana=captar,importar=importar)
        self.assertEqual(chamadas,['indice','2026-10-18','2026-10-11','quarentena'])
        self.assertEqual(a['semanas_processadas'],2)
        self.assertEqual(a['observacoes_reprocessadas'],116)
        self.assertFalse(a['cloud_gravado'])

    def test_execucao_sem_autorizacao_bloqueia_indice(self):
        def sem_acesso(*args,**kwargs):
            self.fail('consulta proibida')
        with self.assertRaises(PermissionError):
            atualizar_conab_lote(banco='x',raw_dir='y',buscar_indice=sem_acesso)

    def test_limite_de_lote_nao_dispara_download(self):
        with self.assertRaises(ErroIncrementalConab):
            atualizar_conab_lote(banco='x',raw_dir='y',quantidade=5,
                executar=True,direitos_consulta=True,direitos_coleta=True,
                direitos_armazenamento=True)

if __name__=='__main__':
    unittest.main()
