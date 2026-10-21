import copy
import json
import tempfile
import unittest
from pathlib import Path

from nivon.historico_municipal import abrir, consultar_em, registrar


class TestHistoricoMunicipal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arquivo = Path(self.tmp.name) / "agregado.json"
        self.con = abrir(":memory:")
        self.addCleanup(self.con.close)
        self.base = {
            "fonte": "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL",
            "licenca_catalogo": "Creative Commons Attribution",
            "sha256_arquivo": "a" * 64,
            "data_coleta_utc": "2026-10-17T08:00:00+00:00",
            "municipios_distintos_com_fabricante_ativo_racao": 2,
            "municipios_candidatos": [
                {"uf": "GO", "municipio": "RIO VERDE", "registros_distintos": 2},
                {"uf": "MT", "municipio": "SORRISO", "registros_distintos": 1},
            ],
        }

    def gravar(self):
        self.arquivo.write_text(json.dumps(self.base), encoding="utf-8")
        return registrar(self.con, self.arquivo)

    def test_nova_edicao(self):
        r = self.gravar()
        self.assertTrue(r["nova_edicao"])
        self.assertTrue(r["nova_coleta"])
        self.assertEqual(r["municipios"], 2)
        self.assertEqual(self.con.execute("SELECT count(*) FROM cidades").fetchone()[0], 2)

    def test_repeticao_mesma_coleta_idempotente(self):
        self.gravar()
        r = self.gravar()
        self.assertFalse(r["nova_edicao"])
        self.assertFalse(r["nova_coleta"])
        self.assertEqual(self.con.execute("SELECT count(*) FROM coletas").fetchone()[0], 1)

    def test_recaptura_sem_mudanca_preserva_historico(self):
        self.gravar()
        self.base["data_coleta_utc"] = "2026-10-18T08:00:00+00:00"
        r = self.gravar()
        self.assertFalse(r["nova_edicao"])
        self.assertTrue(r["nova_coleta"])
        self.assertEqual(self.con.execute("SELECT count(*) FROM edicoes").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT count(*) FROM coletas").fetchone()[0], 2)

    def test_asof_sem_antecipar_coleta(self):
        self.gravar()
        self.assertEqual(consultar_em(self.con, "2026-10-16T23:59:00Z")["estado"], "SEM_COLETA")
        x = consultar_em(self.con, "2026-10-17T08:05:00Z")
        self.assertEqual(x["estado"], "DISPONIVEL")
        self.assertEqual(len(x["municipios"]), 2)

    def test_hash_diferente_cria_outra_edicao(self):
        self.gravar()
        self.base["sha256_arquivo"] = "b" * 64
        self.base["data_coleta_utc"] = "2026-10-18T08:00:00Z"
        self.base["municipios_candidatos"].append(
            {"uf": "SP", "municipio": "CAMPINAS", "registros_distintos": 1})
        self.base["municipios_distintos_com_fabricante_ativo_racao"] = 3
        r = self.gravar()
        self.assertTrue(r["nova_edicao"])
        self.assertEqual(len(consultar_em(self.con, "2026-10-17T09:00:00Z")["municipios"]), 2)
        self.assertEqual(len(consultar_em(self.con, "2026-10-18T09:00:00Z")["municipios"]), 3)

    def test_mesmo_hash_fonte_cidades_divergentes_rejeitado(self):
        self.gravar()
        self.base["municipios_candidatos"][0]["municipio"] = "GOIANIA"
        self.base["data_coleta_utc"] = "2026-10-18T08:00:00Z"
        with self.assertRaises(ValueError):
            self.gravar()
        self.assertEqual(self.con.execute("SELECT count(*) FROM coletas").fetchone()[0], 1)

    def test_coleta_exige_fuso(self):
        self.base["data_coleta_utc"] = "2026-10-17T08:00:00"
        with self.assertRaises(ValueError):
            self.gravar()

    def test_entrada_dado_individual_extra_rejeitada(self):
        self.base["municipios_candidatos"][0]["razao_social"] = "NAO PERMITIDO"
        with self.assertRaises(ValueError):
            self.gravar()


if __name__ == "__main__":
    unittest.main()
