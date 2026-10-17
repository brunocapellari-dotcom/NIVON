import json
import tempfile
import unittest
from pathlib import Path

from nivon.cadastro_derivado import ErroCadastroDerivado, carregar_municipios_racao


class TestCadastroDerivado(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agregado.json"
        self.dados = {
            "fonte": "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL",
            "licenca_catalogo": "Creative Commons Attribution",
            "sha256_arquivo": "a" * 64,
            "data_coleta_utc": "2026-10-17T03:00:00+00:00",
            "municipios_distintos_com_fabricante_ativo_racao": 2,
            "municipios_candidatos": [
                {"uf": "GO", "municipio": "RIO VERDE", "registros_distintos": 2},
                {"uf": "SC", "municipio": "CHAPECO", "registros_distintos": 1},
            ],
        }

    def ler(self):
        self.path.write_text(json.dumps(self.dados), encoding="utf-8")
        return carregar_municipios_racao(self.path)

    def test_agregado_valido_com_fabricas_racao_candidatas(self):
        r = self.ler()
        self.assertEqual(r["municipios"], 2)
        self.assertTrue(all(x.racao_registrada for x in r["fabrica_candidata_por_municipio"]))
        self.assertEqual(len(r["hash_arquivo_agregado_sha256"]), 64)

    def test_arquivo_com_dados_individuais_extras_bloqueado(self):
        self.dados["municipios_candidatos"][0]["cnpj"] = "123"
        with self.assertRaises(ErroCadastroDerivado):
            self.ler()

    def test_numero_registros_sem_hash_nao_servem(self):
        del self.dados["sha256_arquivo"]
        with self.assertRaises(ErroCadastroDerivado):
            self.ler()

    def test_duplicatas_bloqueadas(self):
        self.dados["municipios_candidatos"].append(
            {"uf": "GO", "municipio": "RIO VERDE", "registros_distintos": 3}
        )
        self.dados["municipios_distintos_com_fabricante_ativo_racao"] = 3
        with self.assertRaises(ErroCadastroDerivado):
            self.ler()

    def test_fonte_diferente_rejeitada(self):
        self.dados["fonte"] = "NAO_VERIFICADA"
        with self.assertRaises(ErroCadastroDerivado):
            self.ler()


if __name__ == "__main__":
    unittest.main()
