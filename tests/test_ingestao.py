import tempfile
import unittest
from pathlib import Path
from nivon.ingestao import ContratoCSV, ler_csv_local
from nivon.motores import DadoInvalido


class TestIngestao(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.arquivo = Path(self.temp.name) / "amostra.csv"
        self.arquivo.write_text("uf;municipio;volume_t\nMT;SORRISO;10\nMT;LUCAS DO RIO VERDE;20\n", encoding="utf-8")
        self.contrato = ContratoCSV("SIMULADO", ("uf", "municipio", "volume_t"),
                                    "APROVADA", frozenset({"LEITURA_LOCAL"}))

    def carregar(self, contrato=None):
        return ler_csv_local(self.arquivo, contrato or self.contrato,
                             competencia="2026-01", referencia="2026-01-31", publicacao=None)

    def test_importacao_com_hash_e_datas(self):
        resultado = self.carregar()
        self.assertEqual(resultado["linhas_lidas"], 2)
        self.assertEqual(len(resultado["hash_sha256"]), 64)
        self.assertIn("coleta", resultado["datas"])

    def test_fonte_pendente_bloqueada(self):
        with self.assertRaises(PermissionError):
            self.carregar(ContratoCSV("SIMULADO", ("uf",)))

    def test_coluna_ausente_falha(self):
        with self.assertRaises(DadoInvalido):
            self.carregar(ContratoCSV("SIMULADO", ("nao_existe",), "APROVADA", frozenset({"LEITURA_LOCAL"})))

    def test_linha_nula_falha(self):
        self.arquivo.write_text("uf;municipio;volume_t\nMT;SORRISO;\n", encoding="utf-8")
        with self.assertRaises(DadoInvalido):
            self.carregar()

    def test_csv_limite_de_bytes(self):
        with self.assertRaises(DadoInvalido):
            self.carregar(ContratoCSV("SIMULADO", ("uf",), "APROVADA", frozenset({"LEITURA_LOCAL"}), tamanho_maximo=5))

    def test_csv_cabecalho_duplicado(self):
        self.arquivo.write_text("uf;uf;municipio;volume_t\nMT;MT;S;1\n", encoding="utf-8")
        with self.assertRaises(DadoInvalido):
            self.carregar()

    def test_limite_de_linhas(self):
        with self.assertRaises(DadoInvalido):
            self.carregar(ContratoCSV("SIMULADO", ("uf",), "APROVADA", frozenset({"LEITURA_LOCAL"}), linhas_maximas=1))


if __name__ == "__main__":
    unittest.main()
