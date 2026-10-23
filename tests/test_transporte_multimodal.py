import unittest
from nivon.transporte_multimodal import (
    ErroTransporte, baixar_antt, link_antt, interpretar_csv_antt,
    RESUMOS_ANTAQ_2025, conferir_tku_hidrovias_2025,
)

COLUNAS = "Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;Estacao_Destino;UF_Destino;TU;TKU\\n".replace("\\n", "\n")
AMOSTRA = "02/2026;RMO;SOJA;Rondonopolis;MT;Santos;SP;1.234,50;987654,00\\n".replace("\\n", "\n")


class TestANTT(unittest.TestCase):
    def test_link_verificado(self):
        self.assertIn("dados.antt.gov.br", link_antt(2026))
        with self.assertRaises(ErroTransporte): link_antt(2024)

    def test_rede_optin(self):
        with self.assertRaises(PermissionError): baixar_antt(2026)

    def test_parse_registro(self):
        raw = (COLUNAS + AMOSTRA).encode("utf-8-sig")
        r, m = interpretar_csv_antt(raw, ano=2026, coleta_utc="2026-10-22T12:00:00Z")
        self.assertEqual(m.referencia_maxima, "2026-02")
        self.assertEqual(m.registros, 1)
        self.assertEqual(r[0]["toneladas_uteis"], "1234.50")
        self.assertEqual(r[0]["tku_raw"], "987654.00")
        self.assertFalse(r[0]["unidade_tku_confirmada"])
        self.assertEqual(r[0]["uf_origem"], "MT")

    def test_formato_invalido_bloqueia(self):
        casos = [
            COLUNAS + AMOSTRA.replace("02/2026", "02/2025"),
            COLUNAS + AMOSTRA.replace("1.234,50", "-10"),
            COLUNAS + AMOSTRA.replace("1.234,50", "NaN"),
            COLUNAS + AMOSTRA.replace("987654,00", "0"),
            COLUNAS.replace("TKU", "TKUX") + AMOSTRA,
            COLUNAS + AMOSTRA.replace(";MT;", ";;"),
        ]
        for caso in casos:
            with self.subTest(caso=caso[:48]):
                with self.assertRaises(ErroTransporte):
                    interpretar_csv_antt(caso.encode(), ano=2026, coleta_utc="2026-10-22T12:00:00Z")

    def test_mes_ano_dicionario_oficial_mm_aa(self):
        raw = (COLUNAS + AMOSTRA.replace("02/2026", "02_26")).encode()
        rows, meta = interpretar_csv_antt(
            raw, ano=2026, coleta_utc="2026-10-22T12:00:00Z")
        self.assertEqual(rows[0]["competencia"], "2026-02")
        self.assertEqual(meta.referencia_maxima, "2026-02")
        raw_2006 = (COLUNAS + AMOSTRA.replace("02/2026", "02_06")).encode()
        rows, _ = interpretar_csv_antt(
            raw_2006, ano=2006, coleta_utc="2026-10-22T12:00:00Z")
        self.assertEqual(rows[0]["competencia"], "2006-02")

    def test_2025_isolado(self):
        raw = (COLUNAS + AMOSTRA.replace("02/2026", "2025-02")).encode()
        r, _ = interpretar_csv_antt(raw, ano=2025, coleta_utc="2026-10-22T12:00:00Z")
        self.assertEqual(r[0]["ano"], 2025)


class TestANTAQ(unittest.TestCase):
    def test_conceitos_distintos(self):
        r = {x["recorte"] + "_" + x["metrica"]: x for x in RESUMOS_ANTAQ_2025}
        self.assertEqual(r["NAVEGACAO_INTERIOR_ESTRITA_TONELADAS"]["valor"], "91300000")
        self.assertEqual(r["TODAS_VIAS_INTERIORES_TONELADAS"]["valor"], "145000000")
        self.assertEqual(r["NAVEGACAO_INTERIOR_ESTRITA_TKU"]["natureza"], "ESTIMADO_ANTAQ")

    def test_tku_nao_igual_toneladas(self):
        m = conferir_tku_hidrovias_2025()
        self.assertEqual(m["tku_total"], 42703889135)
        self.assertGreater(m["tku_demais"], 0)
        self.assertEqual(m["tku_por_hidrovia_subconjunto"]["MADEIRA"], 12806337334)


if __name__ == "__main__":
    unittest.main()
