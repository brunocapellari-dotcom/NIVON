import unittest
from nivon.anp_manifesto import manifestar_anp_diesel,ErroManifestoANP
BASE="https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsan/2026"
def page(*slugs):
    return ("<html><body>"+"".join(f'<a href="{BASE}/{s}">{s}</a>' for s in slugs)+
            "</body>"+" " * 60).encode()
class TestManifestoANP(unittest.TestCase):
    def montar(self,files,months=frozenset({8,9})):
        return manifestar_anp_diesel([page(*files)],ano=2026,meses_solicitados=months)
    def test_arquivos_diesel_mensais_com_nomes_diferentes(self):
        r=self.montar(["08-dados-abertos-precos-2026-08-diesel-gnv.csv",
                       "09-dados-abertos-precos-2026-09-diesel-gnv.csv"])
        self.assertEqual(len(r["arquivos"]),2)
        self.assertEqual(r["meses_sem_link"],[])
        self.assertEqual(r["downloads_realizados"],0)
    def test_mes_faltante_explicito_nao_e_zero(self):
        r=self.montar(["09-dados-abertos-precos-2026-09-diesel-gnv.csv"])
        self.assertEqual(r["meses_sem_link"],["2026-08"])
    def test_nao_confunde_glp_e_gasolina(self):
        r=self.montar(["08-dados-abertos-precos-2026-08-glp.csv",
                       "09-dados-abertos-precos-2026-09-gasolina-etanol.csv"])
        self.assertEqual(r["arquivos"],[])
    def test_redirecionamento_de_dominio_rejeitado(self):
        r=manifestar_anp_diesel([page("09-dados-abertos-precos-2026-09-diesel-gnv.csv")+
            b'<a href="https://evil.example/09-dados-abertos-precos-diesel-gnv.csv">bad</a>'],
            ano=2026,meses_solicitados=frozenset({9}))
        self.assertEqual(len(r["arquivos"]),1)
    def test_links_duplicados_de_paginas_paginadas_idempotentes(self):
        x="09-dados-abertos-precos-2026-09-diesel-gnv.csv"
        r=manifestar_anp_diesel([page(x),page(x)],ano=2026,
                                meses_solicitados=frozenset({9}))
        self.assertEqual(len(r["arquivos"]),1)
    def test_duas_edicoes_do_mes_bloqueiam(self):
        with self.assertRaises(ErroManifestoANP):
            self.montar(["09-dados-abertos-precos-2026-09-diesel-gnv.csv",
                         "09-outro-diesel-gnv.csv"])
    def test_sem_meses_validos_falha(self):
        with self.assertRaises(ErroManifestoANP):
            self.montar(["09-diesel-gnv.csv"],months=frozenset({0}))
    def test_ano_antigo_sem_contrato_mensal(self):
        with self.assertRaises(ErroManifestoANP):
            manifestar_anp_diesel([page("09-diesel-gnv.csv")],ano=2004,
                                  meses_solicitados=frozenset({9}))
