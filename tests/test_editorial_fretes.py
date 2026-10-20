"""Testes de formatação de frete no resumo editorial NIVON."""
import unittest

from nivon.briefing_composto import montar_briefing

AGORA = "2026-10-20T15:00:00-03:00"
FONTES = {"TESTE": {"status_direitos": "APROVADA",
                    "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"]}}


def frete(**alteracoes):
    item = {"fonte_id": "TESTE", "tipo": "FRETE_ANUNCIADO",
            "origem": "SORRISO", "uf_origem": "MT",
            "destino": "DOM AQUINO", "uf_destino": "MT",
            "valor_rs_t": 130, "referencia": "2026-10-20T11:00:00-03:00",
            "volume_t_dia": 800, "classificacao_volume": "REFERENCIA",
            "volume_realizado": False}
    item.update(alteracoes)
    return item


def gerar(*fretes):
    return montar_briefing(noticias=[], fontes=FONTES, data=AGORA,
                           indicadores=[], fretes=list(fretes))


class TestFreteEditorial(unittest.TestCase):
    def test_corredor_dom_aquino_com_valor_e_volume_classificado(self):
        b = gerar(frete())
        self.assertEqual(b["fretes_incluidos"], 1)
        self.assertIn("SORRISO/MT → DOM AQUINO/MT", b["texto"])
        self.assertIn("R$ 130,00/t", b["texto"])
        self.assertIn("800 t/dia (volume REFERENCIA)", b["texto"])
        self.assertNotIn("800 t/dia realizados", b["texto"])

    def test_corredores_referencia_permitidos_sem_inventar_volume(self):
        for cidade, uf in [("PARANAGUA", "PR"), ("SANTOS", "SP"),
                           ("UBERABA", "MG")]:
            with self.subTest(cidade=cidade):
                r = frete(destino=cidade, uf_destino=uf)
                r.pop("volume_t_dia")
                b = gerar(r)
                self.assertEqual(b["fretes_incluidos"], 1)
                self.assertNotIn("t/dia", b["texto"])

    def test_volume_sem_classificacao_nao_publica(self):
        b = gerar(frete(classificacao_volume=None))
        self.assertEqual(b["fretes_incluidos"], 0)
        self.assertTrue(b["rejeicoes"])

    def test_volume_referencia_nao_se_declara_realizado(self):
        b = gerar(frete(volume_realizado=True))
        self.assertEqual(b["fretes_incluidos"], 0)

    def test_volume_invalido_nao_publica(self):
        for volume in (float("nan"), float("inf"), -1, 0, True):
            with self.subTest(volume=volume):
                self.assertEqual(gerar(frete(volume_t_dia=volume))["fretes_incluidos"], 0)

    def test_sem_cotacao_fabricada(self):
        b = gerar(frete())
        self.assertNotIn("Chicago Soja", b["texto"])
        self.assertIn("RESUMO ESTRATÉGICO", b["texto"])


if __name__ == "__main__":
    unittest.main()
