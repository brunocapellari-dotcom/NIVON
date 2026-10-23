"""Testes sintéticos do exportador: não consulta terceiros nem envia dados à nuvem."""
import json
from pathlib import Path
import tempfile
import unittest

from nivon.cotacoes import carregar_catalogo
from nivon.widgets_exportacao import ExportacaoBloqueada, cobertura, converter, normalizar

CAT = carregar_catalogo()


def cepea():
    return {
        "id_widget": 121, "fonte_original": "CEPEA", "serie_origem": "soja_paranagua",
        "produto": "soja", "praca": "Paranaguá/PR", "detalhe_cotacao": None,
        "unidade": "BRL/sc60kg", "valor": "150.500000",
        "data_referencia": "2026-10-21", "data_publicacao": None,
        "data_coleta": "2026-10-22 21:18:28.988353+00",
        "natureza": "INFORMADO", "status_qualidade": "VALIDADO",
        "licenca": "CC BY-NC 4.0",
        "url_fonte_original": "https://www.cepea.org.br/br/indicador/soja.aspx",
        "chave_origem": "a" * 64, "hash_versao": "b" * 64,
        "widget_coletado_diretamente": False,
    }


def ptax():
    return {
        "id_widget": 232, "fonte_original": "BCB", "serie_origem": "ptax_USD_compra",
        "produto": "USD", "praca": None,
        "detalhe_cotacao": "COTACAO_DOLAR_DIARIA / 2026-10-22 13:12:09 / COMPRA",
        "unidade": "BRL/USD", "valor": "5.037700000",
        "data_referencia": "2026-10-22", "data_publicacao": None,
        "data_coleta": "2026-10-23 01:30:03.28985+00",
        "natureza": "INFORMADO", "status_qualidade": "REGISTRO_NEON",
        "licenca": "ODbL", "url_fonte_original": None,
        "chave_origem": "neon_ptax_quotes:11:compra", "hash_versao": None,
        "widget_coletado_diretamente": False,
    }


class TestWidgetsExportacao(unittest.TestCase):
    def test_catalogo_completo_sem_coletas_presumidas(self):
        self.assertEqual(cobertura(CAT)["catalogados"], 42)
        self.assertEqual(cobertura(CAT)["widgets_coletados_diretamente"], 0)

    def test_cepea_com_frescor_e_sem_inventar_publicacao(self):
        row = normalizar(cepea(), CAT)
        self.assertEqual(row["atributos"]["widget_id_de_referencia"], 121)
        self.assertEqual(row["data_publicacao"], None)
        self.assertEqual(row["data_coleta"], "2026-10-22T21:18:28.988353Z")
        self.assertFalse(row["atributos"]["hash_raw_fonte_primaria_disponivel"])
        self.assertEqual(row["valor"], "150.5")

    def test_ptax_preserva_lado_e_vintage(self):
        r = normalizar(ptax(), CAT)
        self.assertEqual(r["indicador_id"], "ptax_USD_compra")
        self.assertEqual(r["fonte_id"], "BCB")
        self.assertEqual(len(r["observacao_id"]), 64)
        self.assertEqual(r["valor"], "5.0377")

    def test_mapeamento_diferente_bloqueado(self):
        r = cepea()
        r["id_widget"] = 26
        with self.assertRaises(ExportacaoBloqueada):
            normalizar(r, CAT)

    def test_widget_nao_e_api_de_dados(self):
        r = cepea()
        r["widget_coletado_diretamente"] = True
        with self.assertRaises(ExportacaoBloqueada):
            normalizar(r, CAT)

    def test_nao_aceita_publicacao_posterior_a_coleta(self):
        r = cepea()
        r["data_publicacao"] = "2026-10-24T00:00:00+00:00"
        with self.assertRaises(ExportacaoBloqueada):
            normalizar(r, CAT)

    def test_nao_aceita_data_sem_fuso(self):
        r = ptax()
        r["data_coleta"] = "2026-10-22T14:00:00"
        with self.assertRaises(ExportacaoBloqueada):
            normalizar(r, CAT)

    def test_exportacao_privada_idempotente_e_limpa_em_falha(self):
        with tempfile.TemporaryDirectory() as dir:
            p = Path(dir)
            original, convertido = p / "origem.jsonl", p / "bigquery.jsonl"
            original.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in (cepea(),ptax())) + "\n",encoding="utf8")
            resultado = converter(original, convertido, CAT)
            self.assertEqual(resultado["linhas_exportadas"], 2)
            self.assertEqual(resultado["com_serie_primaria_neste_lote"], [121, 232])
            self.assertFalse(resultado["google_cloud_carregado"])
            self.assertEqual(len(convertido.read_text(encoding="utf8").splitlines()), 2)
            with self.assertRaises(ExportacaoBloqueada):
                converter(original, convertido, CAT)

    def test_exportacao_aborta_sem_resultado_parcial(self):
        with tempfile.TemporaryDirectory() as dir:
            p = Path(dir)
            original, convertido = p / "origem.jsonl", p / "bigquery.jsonl"
            invalida = cepea()
            invalida["widget_coletado_diretamente"] = True
            original.write_text(json.dumps(cepea())+"\n"+json.dumps(invalida)+"\n")
            with self.assertRaises(ExportacaoBloqueada):
                converter(original, convertido, CAT)
            self.assertFalse(convertido.exists())


if __name__ == "__main__":
    unittest.main()
