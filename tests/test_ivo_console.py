import contextlib
import io
import json
import unittest

from nivon.ivo_console import main


class TestIVOConsole(unittest.TestCase):
    def rodar(self, *argv):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = main(list(argv))
        return codigo, json.loads(saida.getvalue())

    def test_consulta_real_offline(self):
        codigo, doc = self.rodar("--pergunta", "Previsao para soja e chuva em MT")
        self.assertEqual(codigo, 0)
        self.assertIn("SOJA", {f["id"] for f in doc["frentes"]})
        self.assertIn("METEOROLOGIA", {f["id"] for f in doc["frentes"]})
        self.assertEqual(doc["ferramentas_executadas"], 0)

    def test_rejeita_payload_invalido(self):
        codigo, doc = self.rodar("--pergunta", "soja", "--max-frentes", "-1")
        self.assertEqual(codigo, 2)
        self.assertEqual(doc["status"], "BLOQUEADO")

    def test_pergunta_sem_escopo_nao_alucina(self):
        codigo, doc = self.rodar("--pergunta", "Como esta tudo?")
        self.assertEqual(codigo, 0)
        self.assertEqual(doc["status"], "PRECISA_DE_ESCOPO")


if __name__ == "__main__":
    unittest.main()
