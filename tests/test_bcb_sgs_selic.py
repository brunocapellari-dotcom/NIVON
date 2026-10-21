import json
import unittest

from nivon.bcb_sgs_selic import ErroSGS, normalizar_selic_diaria


def parse(obj, coleta="2026-10-21T12:00:00-04:00"):
    return normalizar_selic_diaria(json.dumps(obj).encode(), coletado_em=coleta)


class TestSelicSGS(unittest.TestCase):
    def test_observacoes_datadas_e_unidade_diaria_sem_confundir_meta(self):
        r = parse([{"data": "19/10/2026", "valor": "0.054266"},
                   {"data": "20/10/2026", "valor": "0.054300"}])
        self.assertEqual(r["dataset_id"], "BCB_SGS_TAXA_SELIC_DIARIA")
        self.assertEqual(r["observacoes"][0]["data_referencia"], "2026-10-19")
        self.assertEqual(r["observacoes"][0]["valor_pct_ao_dia"], "0.054266")
        self.assertEqual(r["observacoes"][0]["unidade"], "PERCENTUAL_AO_DIA")
        self.assertEqual(r["observacoes"][0]["coleta"], "2026-10-21T16:00:00+00:00")
        self.assertIsNone(r["observacoes"][0]["publicacao"])
        self.assertTrue(r["sem_hora_publicacao"])
        self.assertFalse(r["apto_publicacao_automatica"])

    def test_nao_converter_campo_valor_em_percentual_anual(self):
        r = parse([{"data": "19/10/2026", "valor": "0,054266"}])
        self.assertEqual(r["observacoes"][0]["valor_pct_ao_dia"], "0.054266")

    def test_recusa_duplicatas_e_datas_invalidas(self):
        casos = [
            [{"data": "19/10/2026", "valor": "0.05"},
             {"data": "19/10/2026", "valor": "0.05"}],
            [{"data": "31/02/2026", "valor": "0.05"}],
            [{"data": "2026-10-19", "valor": "0.05"}],
            [{"data": "19/10/2026", "valor": ""}],
            [{"data": "19/10/2026", "valor": "13.75%"}],
            [{"data": "19/10/2026", "valor": "-10"}],
            [{"data": "19/10/2026", "valor": "nan"}],
        ]
        for c in casos:
            with self.subTest(c=c), self.assertRaises(ErroSGS):
                parse(c)

    def test_ordenar_periodos_sem_inferir_dias_sem_observacao(self):
        r = parse([{"data": "20/10/2026", "valor": "0.05"},
                   {"data": "16/10/2026", "valor": "0.06"}])
        self.assertEqual([x["data_referencia"] for x in r["observacoes"]],
                         ["2026-10-16", "2026-10-20"])
        self.assertEqual(len(r["observacoes"]), 2)

    def test_resposta_vazia_ou_com_chave_duplicada_falha(self):
        for raw in (b"", b"[]", b"{}",
                    b'[{"data":"19/10/2026","valor":"0.05","valor":"0.06"}]'):
            with self.assertRaises(ErroSGS):
                normalizar_selic_diaria(raw, coletado_em="2026-10-21T16:00:00Z")

    def test_timestamp_coleta_sem_fuso_recusado(self):
        with self.assertRaises(ErroSGS):
            parse([{"data": "19/10/2026", "valor": "0.054"}],
                  coleta="2026-10-21T12:00:00")


if __name__ == "__main__":
    unittest.main()
