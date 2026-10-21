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
            "pickup_entity_id": "PICKUP_SYNTHETIC_001",
            "ponto_embarque": "Armazém Sintético Norte",
            "transportadora": "Transporte Sintético Alfa",
            "produto": "SOJA", "equipamento": "BITREM",
            "regime_pf_pj": "PJ", "condicao_pedagio": "INCLUSO",
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

    def test_registro_incompleto_nao_pode_aparecer_como_divulgacao(self):
        for campo in ("pickup_entity_id","ponto_embarque","transportadora",
                      "produto","equipamento","regime_pf_pj","condicao_pedagio"):
            with self.subTest(campo=campo):
                registro=frete()
                registro.pop(campo)
                b=gerar(registro)
                self.assertEqual(b["fretes_incluidos"],0)
                self.assertNotIn("FRETES ANUNCIADOS",b["texto"])
                self.assertTrue(any(x["tipo"]=="FRETE" for x in b["rejeicoes"]))

    def test_mesma_rota_dois_estabelecimentos_transportadoras_sem_media(self):
        registro_a=frete()
        registro_b=frete(pickup_entity_id="PICKUP_SYNTHETIC_002",
                          ponto_embarque="Armazém Sintético Sul",
                          transportadora="Transporte Sintético Beta",
                          valor_rs_t=145, volume_t_dia=600)
        b=gerar(registro_a,registro_b)
        self.assertEqual(b["fretes_incluidos"],2)
        self.assertIn("Armazém Sintético Norte [PICKUP_SYNTHETIC_001]",b["texto"])
        self.assertIn("Armazém Sintético Sul [PICKUP_SYNTHETIC_002]",b["texto"])
        self.assertIn("Transporte Sintético Alfa",b["texto"])
        self.assertIn("Transporte Sintético Beta",b["texto"])
        self.assertIn("R$ 130,00/t",b["texto"])
        self.assertIn("R$ 145,00/t",b["texto"])
        self.assertNotIn("média municipal",b["texto"])
        linhas=[l for l in b["texto"].splitlines() if " | embarque: " in l]
        self.assertEqual(len(linhas),2)

    def test_nao_duplica_anuncio_exatamente_repetido(self):
        b=gerar(frete(),frete())
        self.assertEqual(b["fretes_incluidos"],1)
        self.assertTrue(any("duplicado" in x["motivo"] for x in b["rejeicoes"]))

    def test_nao_publica_referencia_futura(self):
        self.assertEqual(gerar(frete(referencia="2026-10-21T11:00:00-03:00"))["fretes_incluidos"],0)

    def test_sem_cotacao_fabricada(self):
        b = gerar(frete())
        self.assertNotIn("Chicago Soja", b["texto"])
        self.assertIn("RESUMO ESTRATÉGICO", b["texto"])


if __name__ == "__main__":
    unittest.main()
