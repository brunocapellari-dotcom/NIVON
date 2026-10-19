import unittest

from nivon.antt_ferrovia import ErroFerrovia
from nivon.antt_ferrovia_csv import extrair_csv, resumo_safra_ferroviaria

HEADER = ("Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;"
          "UF_Origem;Estacao_Destino;UF_Destino;TU;TKU\n")


def montar(*linhas):
    return (HEADER + "".join(linhas)).encode("cp1252")


class TestCSVAnttSIADE(unittest.TestCase):
    def linha(self, *, mes="01/2026", merc="Grãos - Milho", origem="Rondonópolis",
              destino="Santos", uf_orig="MT", uf_dest="SP", tu="33.420", tku="28.774.620"):
        return ";".join((mes, "FERROVIA TESTE", merc, origem, uf_orig,
                         destino, uf_dest, tu, tku)) + "\n"

    def test_convert_ptbr_toneladas_e_tku(self):
        x=extrair_csv(montar(self.linha()))[0]
        self.assertEqual(x["tu_t"],33420)
        self.assertEqual(x["tku"],28774620)
        self.assertEqual(x["periodo"],"2026-01")
        self.assertEqual(x["local_tipo"],"ESTACAO_NAO_MUNICIPIO")

    def test_registros_multiple_mes(self):
        r=extrair_csv(montar(self.linha(),self.linha(mes="02/2026",tu="10.500")))
        s=resumo_safra_ferroviaria(r)
        self.assertEqual(s["linhas_totais"],2)
        self.assertEqual(len(s["por_mes"]),2)
        self.assertEqual(len(s["fluxos_mt_por_estacao"]),2)

    def test_nao_mistura_farelo_com_soja(self):
        r=extrair_csv(montar(self.linha(merc="Soja"),
                             self.linha(merc="Farelo de Soja")))
        s=resumo_safra_ferroviaria(r)
        self.assertEqual({x["mercadoria_fonte"] for x in s["fluxos_mt_por_estacao"]},
                         {"SOJA_FONTE_ANTT","FARELO_SOJA_FONTE_ANTT"})

    def test_origem_de_outra_uf_nao_e_mt(self):
        r=extrair_csv(montar(self.linha(uf_orig="GO")))
        self.assertEqual(resumo_safra_ferroviaria(r)["fluxos_mt_por_estacao"],[])

    def test_numero_fracionario_ptbr_explicitado(self):
        r=extrair_csv(montar(self.linha(tu="1.234,50",tku="50,75")))
        self.assertEqual(r[0]["tu_t"],1234.5)
        self.assertEqual(r[0]["tku"],50.75)

    def test_tu_sem_separador_nao_inferido(self):
        r=extrair_csv(montar(self.linha(tu="2000",tku="1.000")))
        self.assertEqual(r[0]["tu_t"],2000)

    def test_tu_em_formato_ingles_falha(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(montar(self.linha(tu="1,200.50")))

    def test_uf_invalida_bloqueia(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(montar(self.linha(uf_orig="XX")))

    def test_sem_mercadoria_bloqueia(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(montar(self.linha(merc="")))

    def test_mes_invalido_bloqueia(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(montar(self.linha(mes="13/2026")))

    def test_schema_alterado_bloqueia(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(b"Mes_Ano;Estacao_Origem\n01/2026;A\n")

    def test_arquivo_vazio_bloqueia(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(b"")

    def test_numero_negativo_bloqueia(self):
        with self.assertRaises(ErroFerrovia):
            extrair_csv(montar(self.linha(tu="-1")))

    def test_hash_de_arquivo_preservado(self):
        x=extrair_csv(montar(self.linha()))[0]
        self.assertEqual(len(x["arquivo_sha256"]),64)

    def test_duas_edicoes_nao_podem_ser_somadas(self):
        r=extrair_csv(montar(self.linha()))
        r2=extrair_csv(montar(self.linha(tu="10")))
        with self.assertRaises(ErroFerrovia):
            resumo_safra_ferroviaria(r+r2)


if __name__ == "__main__":
    unittest.main()
