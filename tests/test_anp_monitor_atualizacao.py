import hashlib
import unittest

from nivon.anp_indice_lpc import URL_INDICE
from nivon.anp_monitor_atualizacao import (
    ErroMonitorANP, URL_SERIE_2026, auditar_publicacoes_anp
)

AGORA="2026-10-20T16:00:00-03:00"
COLETA="2026-10-20T15:00:00-03:00"


def index(semanas=("2026-10-04_2026-10-10", "2026-10-11_2026-10-17")):
    rows="".join(
        '<a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/'
        'arquivos-lpc/2026/resumo_semanal_lpc_'+week.replace("_","_")+
        '.xlsx/view">Preços médios por município</a>' for week in semanas
    )
    return ("<html><body><h1>ANP - Levantamento semanal</h1>"+rows+
            "<p>Dados por semana e por municipio em arquivo XLSX.</p></body></html>").encode()


def annual():
    return {
        "pagina_url":URL_SERIE_2026,
        "pagina_atualizada_em":"2026-10-20T14:34:00-03:00",
        "pagina_coletada_em":"2026-10-20T15:00:00-03:00",
        "html_sha256":"a"*64,
        "arquivo_baixado":False,
        "schema_homologado":False,
    }


class TestMonitorAtualizacaoANP(unittest.TestCase):
    def monitor(self,source=None,**kwargs):
        return auditar_publicacoes_anp(
            index() if source is None else source,
            indice_coletado_em=COLETA,gerado_em=AGORA,**kwargs)

    def test_semana_atual_identificada_sem_cotacao_inventada(self):
        result=self.monitor()
        self.assertEqual(result["ultima_semana_linkada"]["semana_fim"],"2026-10-17")
        self.assertEqual(result["dias_desde_fim_semana"],3)
        self.assertEqual(result["semanas_indexadas"],2)
        self.assertFalse(result["coleta_preco_executada"])
        self.assertFalse(result["publicacao_autorizada"])
        self.assertNotIn("INDICE_SEMANAL_DEFASADO",result["alertas"])

    def test_historico_alterado_nao_prova_preco_de_revenda(self):
        result=self.monitor(anual=annual())
        self.assertFalse(result["arquivo_anual"]["arquivo_baixado"])
        self.assertIn("PAGINA_ANUAL_ATUALIZADA_NAO_PROVA_DADOS_DA_SEMANA",result["alertas"])

    def test_semana_nova_efetivamente_observada(self):
        r=self.monitor(semanas_anteriormente_observadas=frozenset({"2026-10-10"}))
        self.assertEqual(r["novas_competencias_observadas"],["2026-10-17"])
        self.assertEqual(r["competencias_removidas"],[])

    def test_semana_removida_do_indice_gera_alerta(self):
        r=self.monitor(semanas_anteriormente_observadas=frozenset(
            {"2026-10-10","2026-10-17","2026-10-03"}))
        self.assertEqual(r["competencias_removidas"],["2026-10-03"])
        self.assertIn("SEMANAS_ANTES_PRESENTES_REMOVIDAS_DO_INDICE",r["alertas"])

    def test_indice_desatualizado_nao_e_atual(self):
        old=index(("2026-09-06_2026-09-12",))
        r=self.monitor(source=old)
        self.assertIn("INDICE_SEMANAL_DEFASADO",r["alertas"])

    def test_html_alterado_sem_semana_nova_e_revisao_candidata(self):
        r=self.monitor(indice_anterior_sha256="b"*64,
                       semanas_anteriormente_observadas=frozenset(
                           {"2026-10-10","2026-10-17"}))
        self.assertIn("HTML_ALTERADO_SEM_NOVA_SEMANA_VERIFICADA",r["alertas"])

    def test_sem_link_nao_inventa_zero_pesquisa(self):
        html=("<html><body><a href='/anp/'>Início</a>"+"Resultados ainda não expostos"*4+"</body></html>").encode()
        r=self.monitor(source=html)
        self.assertIsNone(r["ultima_semana_linkada"])
        self.assertIn("SEM_SEMANA_LOCALIZADA_NO_INDICE",r["alertas"])
        self.assertFalse(r["publicacao_autorizada"])

    def test_metadata_futuro_proibido(self):
        a=annual()
        a["pagina_atualizada_em"]="2026-10-21T09:00:00-03:00"
        with self.assertRaises(ErroMonitorANP):
            self.monitor(anual=a)

    def test_nao_transformar_download_em_prova_pelo_indice(self):
        a=annual()
        a["arquivo_baixado"]=True
        with self.assertRaises(ErroMonitorANP):
            self.monitor(anual=a)

    def test_semana_que_termina_no_futuro_alertada(self):
        next_week=index(("2026-10-25_2026-10-31",))
        r=self.monitor(source=next_week)
        self.assertIn("PERIODO_SEMANAL_TERMINA_NO_FUTURO",r["alertas"])

    def test_timestamps_captura_apos_geracao_invalidos(self):
        with self.assertRaises(ErroMonitorANP):
            auditar_publicacoes_anp(index(),indice_coletado_em="2026-10-21T10:00:00-03:00",
                                    gerado_em=AGORA)

    def test_hash_arquivo_sem_homologacao_nao_passa(self):
        a=annual()
        a["html_sha256"]="x"*64
        with self.assertRaises(ErroMonitorANP):
            self.monitor(anual=a)


if __name__ == "__main__":
    unittest.main()
