import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from nivon.cotacoes import carregar_catalogo, importar, normalizar, url_incorporacao


class TestCotacoes(unittest.TestCase):
    def setUp(self):
        self.catalogo = carregar_catalogo()
        self.observacao = {
            "id_widget": 199, "instrumento": "soja disponivel", "praca": "Sorriso-MT",
            "vencimento": None, "valor": "120.25", "unidade": "BRL/60kg",
            "data_referencia": "2026-10-20", "data_publicacao": "2026-10-20T18:00:00-04:00",
            "data_coleta": "2026-10-21T09:00:00-04:00", "competencia": "2026-10",
            "classificacao": "SINTETICO", "fonte_original": "FIXTURE"}

    def test_catalogo_completo_ids_unicos(self):
        self.assertEqual(len(self.catalogo["indicadores"]), 42)
        self.assertEqual(len({i["id"] for i in self.catalogo["indicadores"]}), 42)

    def test_url_apenas_catalogados(self):
        self.assertIn("id=199", url_incorporacao(199, self.catalogo))
        with self.assertRaises(ValueError):
            url_incorporacao(999999, self.catalogo)

    def test_ingestao_idempotente_e_historico_de_correcao(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem, banco = Path(pasta) / "dados.json", Path(pasta) / "dados.sqlite3"
            origem.write_text(json.dumps([self.observacao]), encoding="utf-8")
            self.assertEqual(importar(origem, banco, sintetico=True)["inseridos"], 1)
            self.assertEqual(importar(origem, banco, sintetico=True)["duplicados"], 1)
            corrigido = dict(self.observacao, valor="120.75")
            origem.write_text(json.dumps([corrigido]), encoding="utf-8")
            self.assertEqual(importar(origem, banco, sintetico=True)["inseridos"], 1)
            with sqlite3.connect(banco) as con:
                self.assertEqual(con.execute("select count(*) from cotacoes").fetchone()[0], 2)
                self.assertEqual(con.execute("select count(distinct chave_serie) from cotacoes").fetchone()[0], 1)

    def test_nao_importa_dado_real_sem_autorizacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "dados.json"
            origem.write_text(json.dumps([dict(self.observacao, classificacao="INFORMADO")]), encoding="utf-8")
            with self.assertRaises(PermissionError):
                importar(origem, Path(pasta) / "dados.sqlite3")

    def test_datas_unidades_e_classificacao(self):
        casos = [
            dict(self.observacao, unidade=""),
            dict(self.observacao, competencia="2026-09"),
            dict(self.observacao, data_coleta="2026-10-21T09:00:00"),
            dict(self.observacao, classificacao="OBSERVADO"),
            dict(self.observacao, valor="NaN"),
        ]
        for item in casos:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    normalizar(item, self.catalogo, True)

    def test_importacao_atomica(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem, banco = Path(pasta) / "dados.json", Path(pasta) / "dados.sqlite3"
            origem.write_text(json.dumps([self.observacao, dict(self.observacao, id_widget=9999)]), encoding="utf-8")
            with self.assertRaises(ValueError):
                importar(origem, banco, sintetico=True)
            self.assertFalse(banco.exists())

    def test_catalogo_impede_liberdade_de_coleta(self):
        self.assertEqual(self.catalogo["permissoes"]["coleta_automatizada"], "NAO_COMPROVADA")


if __name__ == "__main__":
    unittest.main()
