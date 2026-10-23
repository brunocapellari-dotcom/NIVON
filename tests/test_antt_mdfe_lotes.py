"""Testes sintéticos para histórico e processamento por manifesto."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from nivon.antt_mdfe_volumes import resumo, DadosANTTInvalidos
from scripts.ingest_antt_mdfe_lotes import executar

class TestLotes(unittest.TestCase):
    def test_historico_incremental(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)
            for mes in ("08", "09"):
                (p / f"antt_{mes}.csv").write_text(
                    "competencia;origem;destino;toneladas\n2026-"+mes+";Sorriso;Itaituba;12\n")
            (p / "manifesto.json").write_text(json.dumps({"lotes": [
                {"arquivo": f"antt_{mes}.csv", "recorte": f"mt_{mes}", "nivel": "RGI"}
                for mes in ("08", "09")]}))
            bd = p / "vol.db"
            self.assertEqual(len(executar(str(p), str(bd))), 2)
            self.assertEqual(resumo(bd, "mt_09", "2026-09")["toneladas_no_recorte"], "12")
            self.assertEqual([x["estado"] for x in executar(str(p), str(bd))],
                             ["REUTILIZADO_SEM_DUPLICAR"] * 2)

    def test_manifesto_perigoso(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "manifesto.json").write_text(json.dumps({"lotes": [
                {"arquivo": "../escape.csv", "recorte": "a", "nivel": "RGI"}]}))
            with self.assertRaises(DadosANTTInvalidos):
                executar(str(p), str(p / "vol.db"))

if __name__ == "__main__":
    unittest.main()
