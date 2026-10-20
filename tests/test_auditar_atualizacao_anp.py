import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.auditar_atualizacao_anp import auditar


def index(semanas):
    links="".join(
        '<a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/'
        'precos/arquivos-lpc/2026/resumo_semanal_lpc_'+p+'.xlsx/view">Link oficial</a>'
        for p in semanas
    )
    return ("<html><body><h1>ANP levantamento preços</h1>"+
            links+"<p>Índice oficial semanal.</p></body></html>").encode("utf-8")


class TestAuditoriaANPOffline(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.index=self.root/"indice.html"
        self.output=self.root/"status.json"
        self.coletado="2026-10-20T14:00:00-03:00"
        self.gerado="2026-10-20T15:00:00-03:00"

    def tearDown(self):
        self.temp.cleanup()

    def audit(self, **updates):
        kw=dict(indice_html=self.index,indice_coletado_em=self.coletado,
                gerado_em=self.gerado,saida=self.output)
        kw.update(updates)
        return auditar(**kw)

    def test_cria_json_sem_coletar_preco(self):
        self.index.write_bytes(index(("2026-10-11_2026-10-17",)))
        r=self.audit()
        self.assertEqual(r["semanas"],1)
        self.assertFalse(r["publicacao_autorizada"])
        info=json.loads(self.output.read_text())
        self.assertFalse(info["coleta_preco_executada"])
        self.assertEqual(info["competencias_atualmente_no_indice"],["2026-10-17"])
        self.assertEqual(info["ultima_semana_linkada"]["semana_fim"],"2026-10-17")

    def test_alerta_de_remocao_com_edicao_anterior(self):
        self.index.write_bytes(index(("2026-10-04_2026-10-10",)))
        self.audit()
        anterior=self.root/"anterior.json"
        self.output.replace(anterior)
        self.index.write_bytes(index(("2026-10-11_2026-10-17",)))
        r=self.audit(anterior=anterior)
        self.assertIn("SEMANAS_ANTES_PRESENTES_REMOVIDAS_DO_INDICE",r["alertas"])
        info=json.loads(self.output.read_text())
        self.assertEqual(info["novas_competencias_observadas"],["2026-10-17"])

    def test_fonte_anual_meta_sem_download_nao_homologa(self):
        self.index.write_bytes(index(("2026-10-11_2026-10-17",)))
        annual=self.root/"anual.json"
        annual.write_text(json.dumps({
            "pagina_url":"https://www.gov.br/anp/pt-br/assuntos/"
                        "precos-e-defesa-da-concorrencia/precos/"
                        "precos-revenda-e-de-distribuicao-combustiveis/"
                        "shlp/semanal/semanal-municipios-2026.xlsx/view",
            "pagina_atualizada_em":"2026-10-20T13:00:00-03:00",
            "pagina_coletada_em":self.coletado,
            "html_sha256":"a"*64,
            "arquivo_baixado":False,"schema_homologado":False
        }))
        res=self.audit(anual_meta=annual)
        self.assertIn("PAGINA_ANUAL_ATUALIZADA_NAO_PROVA_DADOS_DA_SEMANA",res["alertas"])

    def test_nunca_sobrescrever_html(self):
        self.index.write_bytes(index(("2026-10-11_2026-10-17",)))
        with self.assertRaises(ValueError):
            self.audit(saida=self.index)

    def test_link_sem_data_nao_e_semana_zero(self):
        self.index.write_bytes(("<html><body><a href='/anp'>Indice ANP</a>" + "Estudo semanal sem links "*7 + "</body></html>").encode())
        res=self.audit()
        self.assertIn("SEM_SEMANA_LOCALIZADA_NO_INDICE",res["alertas"])

    def test_mantem_sem_envio_quando_direitos_desconhecidos(self):
        self.index.write_bytes(index(("2026-10-11_2026-10-17",)))
        res=self.audit()
        self.assertEqual(res["status"],"AUDITADO_OFFLINE_SEM_COLETA_PRECO")
        self.assertNotIn("mensagem_enviada",json.loads(self.output.read_text()))

    def test_symlink_de_entrada_rejeitado(self):
        self.index.write_bytes(index(("2026-10-11_2026-10-17",)))
        target=self.root/"symlink.html"
        try:
            target.symlink_to(self.index)
        except (OSError,NotImplementedError):
            self.skipTest("symlinks não suportados")
        with self.assertRaises(ValueError):
            self.audit(indice_html=target)


if __name__=="__main__":
    unittest.main()
