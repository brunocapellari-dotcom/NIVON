import unittest
from nivon.antaq_replica_hidrovia import (
    ErroReplicaANTAQ, nome_normalizado, validar_linhas, resumo_2025, serializar_resumo,
)

SHA = "a"*64
REV = "b"*40


def amostra():
    return [
        {"Hidrovia": "Hidrovia do Madeira", "Ano": 2025,
         "tonelagem_total": 12057214.601, "n_registros": 26547},
        {"Hidrovia": "Hidrovia do TapajÃ³s", "Ano": 2025,
         "tonelagem_total": 16804955.29, "n_registros": 8357},
        {"Hidrovia": "HidroviaÂ do Baixo Amazonas", "Ano": 2025,
         "tonelagem_total": 70135296.916, "n_registros": 287849},
    ]


class TestReplicaANTAQ(unittest.TestCase):
    def test_resolver_mojibake_sem_inventar_hidrovia(self):
        self.assertEqual(nome_normalizado("Hidrovia do TapajÃ³s"), "Hidrovia do Tapajós")
        self.assertEqual(nome_normalizado("HidroviaÂ do Baixo Amazonas"), "Hidrovia do Baixo Amazonas")

    def test_agregado_secundario_nao_equivale_fonte_primaria(self):
        doc = validar_linhas(amostra(), sha256=SHA, revisao=REV)
        self.assertEqual(doc["n_linhas"], 3)
        self.assertEqual(doc["anos"], [2025])
        self.assertTrue(all(x["classificacao"] == "DERIVADO_TERCEIRO_NAO_CONCILIADO" for x in doc["registros"]))
        self.assertFalse(doc["registros"][0]["aditividade_entre_hidrovias_confirmada"])
        res = resumo_2025(doc)
        self.assertEqual(res["madeira_terceiro_ton"], "12057214.601")
        self.assertTrue(res["comparacao_compatibilidade_1pct"])
        self.assertIn("NÃO SOMAR", res["regra"])
        self.assertIn("source_sha256", serializar_resumo(doc))

    def test_sem_evidencia_bloqueia_uso(self):
        rows = amostra()
        rows[0]["tonelagem_total"] = float("nan")
        with self.assertRaises(ErroReplicaANTAQ):
            validar_linhas(rows, sha256=SHA, revisao=REV)
        rows = amostra() + [amostra()[0]]
        with self.assertRaises(ErroReplicaANTAQ):
            validar_linhas(rows, sha256=SHA, revisao=REV)
        rows = amostra()
        rows[0]["Ano"] = "2025"
        with self.assertRaises(ErroReplicaANTAQ):
            validar_linhas(rows, sha256=SHA, revisao=REV)

    def test_sem_madeira_nao_confirma_comparacao(self):
        doc=validar_linhas(amostra()[1:], sha256=SHA, revisao=REV)
        with self.assertRaises(ErroReplicaANTAQ):
            resumo_2025(doc)


if __name__ == "__main__":
    unittest.main()
