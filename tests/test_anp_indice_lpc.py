import unittest

from nivon.anp_indice_lpc import descobrir_semanas_lpc, ErroIndiceLPC, URL_INDICE


class TestIndiceLPC(unittest.TestCase):
    def html(self):
        return ("""<html><body><h1>ANP Levantamento de preços</h1>
          <a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc/2026/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx/view">
            Preços médios semanais Brasil estados municípios
          </a>
          <a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc/2026/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx/view">Repetido</a>
          <a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc/2026/revendas_lpc_2026-10-04_2026-10-10.xlsx/view">Postos individuais</a>
          <a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc/2025/resumo_semanal_lpc_2025-10-05_2025-10-11.xlsx">Ano anterior</a>
          </body></html>""").encode("utf-8")

    def test_descobre_semana_real_sem_criar_outra(self):
        r=descobrir_semanas_lpc(self.html(),ano=2026)
        self.assertEqual(r["total_semanas"],1)
        x=r["semanas"][0]
        self.assertEqual(x["semana_inicio"],"2026-10-04")
        self.assertEqual(x["semana_fim"],"2026-10-10")
        self.assertFalse(x["baixado"])
        self.assertFalse(x["schema_homologado"])
        self.assertNotIn("revendas_lpc",x["url_pagina"])

    def test_semana_ainda_nao_publicada_nao_e_inventada(self):
        x=descobrir_semanas_lpc(("<html><body><a href='/outro'>index</a>" + "Descrição da pesquisa semanal"*5 + "</body></html>").encode(),ano=2026)
        self.assertEqual(x["semanas"],[])
        self.assertIn("não significa",x["alerta"])

    def test_ano_diferente_nao_mistura(self):
        self.assertEqual(descobrir_semanas_lpc(self.html(),ano=2025)["total_semanas"],1)

    def test_nao_descobre_host_terceiro(self):
        p=('<html><body><a href="https://evil.example/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx">' + "link externo</a>" + "Recursos semanais de petróleo"*3 + "</body></html>").encode()
        self.assertEqual(descobrir_semanas_lpc(p,ano=2026)["semanas"],[])

    def test_url_indice_alheia_bloqueada(self):
        with self.assertRaises(ErroIndiceLPC):
            descobrir_semanas_lpc(self.html(),ano=2026,
                                   url_indice="https://outro.example.com")

    def test_arquivo_de_periodo_invalido_nao_e_planilha_da_semana(self):
        a=self.html().replace(b"2026-10-10.xlsx",b"2026-10-12.xlsx")
        self.assertEqual(descobrir_semanas_lpc(a,ano=2026)["total_semanas"],0)

    def test_html_waf_rejeitado(self):
        with self.assertRaises(ErroIndiceLPC):
            descobrir_semanas_lpc(b"<h1>Request Rejected</h1>",ano=2026)


if __name__=="__main__":
    unittest.main()
