import unittest
from urllib.parse import parse_qs,urlsplit
from nivon.ptax_plano import planejar_consultas_ptax,ErroPlanoPTAX,BASE
from nivon.bcb_ptax import normalizar_ptax_odata

class TestPlanoPTAX(unittest.TestCase):
    def test_usd_doc_dolar_periodo(self):
        p=planejar_consultas_ptax(moeda="USD",inicio="2026-10-01",fim="2026-10-19")
        self.assertEqual(len(p),1)
        self.assertIn("CotacaoDolarPeriodo(",p[0]["url"])
        self.assertTrue(p[0]["url"].startswith(BASE))
        q=parse_qs(urlsplit(p[0]["url"]).query)
        self.assertEqual(q["@dataInicial"],["'10-01-2026'"])
        self.assertEqual(q["@dataFinalCotacao"],["'10-19-2026'"])
        self.assertEqual(q["$format"],["json"])
        self.assertEqual(p[0]["estado"],"PLANEJADO_OFFLINE_SEM_COLETA")
    def test_eur_doc_moeda_periodo(self):
        p=planejar_consultas_ptax(moeda="EUR",inicio="2026-10-01",fim="2026-10-01")
        self.assertIn("CotacaoMoedaPeriodo(",p[0]["url"])
        self.assertEqual(parse_qs(urlsplit(p[0]["url"]).query)["@moeda"],["'EUR'"])
    def test_paginas_sem_sobreposicao(self):
        p=planejar_consultas_ptax(moeda="USD",inicio="2026-10-01",fim="2026-11-01")
        self.assertEqual([(x["inicio"],x["fim"]) for x in p],[
          ("2026-10-01","2026-10-20"),("2026-10-21","2026-11-01")])
    def test_lote_ate_366_dias(self):
        p=planejar_consultas_ptax(moeda="EUR",inicio="2025-10-19",fim="2026-10-19")
        self.assertEqual(p[0]["inicio"],"2025-10-19")
        self.assertEqual(p[-1]["fim"],"2026-10-19")
    def test_bloqueia_periodos_invalidos(self):
        for a,b in (("2026-10-22","2026-10-01"),("2025-01-01","2026-10-01"),
                    ("01-10-2026","2026-10-01"),("2026-13-01","2026-10-01")):
            with self.assertRaises(ErroPlanoPTAX):
                planejar_consultas_ptax(moeda="USD",inicio=a,fim=b)
    def test_bloqueia_entrada_injetada_ou_moeda_errada(self):
        for moeda in ("BTC","BRL","USD';drop",None):
            with self.assertRaises(ErroPlanoPTAX):
                planejar_consultas_ptax(moeda=moeda,inicio="2026-10-01",fim="2026-10-05")
    def test_janela_bloqueada(self):
        for n in (0,21,True,2.5):
            with self.assertRaises(ErroPlanoPTAX):
                planejar_consultas_ptax(moeda="USD",inicio="2026-10-01",
                                        fim="2026-10-05",dias_janela=n)
    def test_compativel_normalizador_sem_rede(self):
        url=planejar_consultas_ptax(moeda="USD",inicio="2026-10-15",fim="2026-10-16")[0]["url"]
        fake={"value":[{"cotacaoCompra":5.0,"cotacaoVenda":5.02,
                        "dataHoraCotacao":"2026-10-15 13:10:35.4469"}]}
        d=normalizar_ptax_odata(fake,moeda="USD",coletado_em="2026-10-19T16:00:00Z",
                                consulta_url=url)
        self.assertEqual(d["numero_de_boletins"],1)
        self.assertIsNone(d["observacoes"][0]["publicacao"])

    def test_semantica_usd_nao_garante_boletins_intradiarios(self):
        p=planejar_consultas_ptax(moeda="USD",inicio="2026-10-01",fim="2026-10-02")
        self.assertEqual(p[0]["semantica"],"DOLAR_DIARIO_NAO_INTRADIARIO")
        e=planejar_consultas_ptax(moeda="EUR",inicio="2026-10-01",fim="2026-10-02")
        self.assertIn("MULTIPLOS_BOLETINS",e[0]["semantica"])
