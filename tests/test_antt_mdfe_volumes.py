"""Testes sintéticos sem rede da ingestão ANTT MDF-e."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from nivon.antt_mdfe_volumes import DadosANTTInvalidos, importar, parse_csv, resumo, baixar_csv_oficial

def csv_dados(ton="40,5", destino="Itaituba", ncm="1201"):
    return (f"Competência;Origem;Destino;Toneladas;NCM;Categoria;Chaves MDF-e\n"
            f"2026-09;Sorriso;{destino};{ton};{ncm};ETC;2\n").encode("utf-8")

class TestANTTVolumes(unittest.TestCase):
    def test_decimal_e_ncm_amostral(self):
        x = parse_csv(csv_dados(), nivel="RGI")
        self.assertEqual(x[0]["toneladas"], "40.5")
        self.assertEqual(x[0]["mdfes"], 2)
        self.assertEqual(x[0]["ncm"], "1201")

    def test_rejeitar_invalidos(self):
        for dado in (csv_dados("-1"), csv_dados("abc"), csv_dados("1.234"),
                     csv_dados("40", "TOTAL"), csv_dados("40", "X")):
            with self.subTest(dado=dado):
                with self.assertRaises(DadosANTTInvalidos):
                    parse_csv(dado, nivel="RGI")

    def test_revisoes_historicas_sem_duplicar(self):
        with TemporaryDirectory() as pasta:
            db = Path(pasta) / "antt.db"
            a = importar(db, csv_dados(), arquivo="exp.csv", recorte="soja-sorriso-itaituba", nivel="RGI")
            self.assertEqual(a["estado"], "NOVA_REVISAO_ARMAZENADA")
            b = importar(db, csv_dados(), arquivo="exp.csv", recorte="soja-sorriso-itaituba", nivel="RGI")
            self.assertEqual(b["estado"], "REUTILIZADO_SEM_DUPLICAR")
            self.assertEqual(resumo(db, "soja-sorriso-itaituba", "2026-09")["toneladas_no_recorte"], "40.5")
            importar(db, csv_dados("60,0"), arquivo="rev.csv", recorte="soja-sorriso-itaituba", nivel="RGI")
            self.assertEqual(resumo(db, "soja-sorriso-itaituba", "2026-09")["toneladas_no_recorte"], "60.0")
            with sqlite3.connect(db) as conexao:
                self.assertEqual(conexao.execute("SELECT COUNT(*) FROM antt_mdfe_lotes").fetchone()[0], 2)
                self.assertEqual(conexao.execute("SELECT COUNT(*) FROM antt_mdfe_lotes WHERE ativo=1").fetchone()[0], 1)

    def test_rejeitar_mistura_total_e_ncm(self):
        dado = csv_dados() + b"2026-09;Sinop;Itaituba;12;;ETC;1\n"
        with self.assertRaises(DadosANTTInvalidos):
            parse_csv(dado, nivel="MUNICIPIO")

    def test_rejeitar_api_privada_powerbi(self):
        with self.assertRaises(DadosANTTInvalidos):
            baixar_csv_oficial("https://app.powerbi.com/view?r=abc")

if __name__ == "__main__":
    unittest.main()
