import unittest
from nivon.mjo_rmm import RMMInvalido, normalizar_rmm_bom, ultimo_rmm_ate


CABECALHO = "year month day RMM1 RMM2 phase amplitude source"
DADOS = CABECALHO + "\n2026 10 17 0.60 0.80 6 1.00 Final\n2026 10 18 0.30 0.40 6 0.50 Final\n"
CAPTURA = "2026-10-20T14:00:00Z"


def normalizar(texto=DADOS, **kwargs):
    return normalizar_rmm_bom(texto=texto, coletado_em=CAPTURA, **kwargs)


class TestIndiceMJO(unittest.TestCase):
    def test_diagnostico_e_amplitude_sem_previsao(self):
        out = normalizar(publicado_em="2026-10-20T13:00:00Z")
        self.assertEqual(len(out["observacoes"]), 2)
        self.assertEqual([x["sinal"] for x in out["observacoes"]], ["ATIVO", "FRACO"])
        self.assertEqual(out["observacoes"][0]["fase_fonte"], 6)
        self.assertFalse(out["operacional"])
        self.assertEqual(len(out["hash_sha256"]), 64)
        self.assertFalse(out["licenca_verificada"])

    def test_ausente_e_sem_inventar_dados(self):
        dado = DADOS + "2026 10 19 999.0 999.0 999.0 999.0 Final\n"
        out = normalizar(texto=dado)
        self.assertEqual(out["linhas_ausentes"], 1)
        self.assertEqual(len(out["observacoes"]), 2)

    def test_amplitude_incompativel_reprovada(self):
        with self.assertRaises(RMMInvalido):
            normalizar(texto=DADOS.replace("0.80 6 1.00", "0.80 6 2.50"))

    def test_fase_invalida_reprovada(self):
        with self.assertRaises(RMMInvalido):
            normalizar(texto=DADOS.replace("0.80 6 1.00", "0.80 9 1.00"))

    def test_data_duplicada_e_fora_da_coleta(self):
        with self.assertRaises(RMMInvalido):
            normalizar(texto=DADOS + DADOS.splitlines()[-1] + "\n")
        with self.assertRaises(RMMInvalido):
            normalizar(texto=DADOS + "2026 10 21 0.3 0.4 7 0.5 Final\n")

    def test_fuso_e_publicacao_bloqueantes(self):
        with self.assertRaises(RMMInvalido):
            normalizar(publicado_em="2026-10-20T15:00:00Z")
        with self.assertRaises(RMMInvalido):
            normalizar_rmm_bom(texto=DADOS, coletado_em="2026-10-20T12:00:00")

    def test_asof_exige_vintage_e_publicacao(self):
        out = normalizar()
        self.assertIsNone(ultimo_rmm_ate(snapshot=out, corte_em="2026-10-20T16:00:00Z"))
        out = normalizar(publicado_em="2026-10-20T13:00:00Z")
        self.assertIsNone(ultimo_rmm_ate(snapshot=out, corte_em="2026-10-19T20:00:00Z"))
        self.assertIsNone(ultimo_rmm_ate(snapshot=out, corte_em="2026-10-20T13:30:00Z"))
        self.assertEqual(ultimo_rmm_ate(snapshot=out, corte_em="2026-10-20T14:00:00Z")["data"], "2026-10-18")

    def test_mistura_de_indice_bloqueada(self):
        with self.assertRaises(RMMInvalido):
            normalizar(fonte_id="CPC_10_EEOF")
        with self.assertRaises(RMMInvalido):
            normalizar(licenca_verificada="sim")

    def test_invalido_nao_vira_zero(self):
        with self.assertRaises(RMMInvalido):
            normalizar(texto=CABECALHO + "\n")
        with self.assertRaises(RMMInvalido):
            normalizar(texto=DADOS.replace("0.60", "nan"))

    def test_entrada_de_7_campos_permitida(self):
        src = "2026 10 18 0.30 0.40 6 0.50\n"
        self.assertEqual(normalizar(texto=src)["observacoes"][0]["data"], "2026-10-18")


if __name__ == "__main__":
    unittest.main()
