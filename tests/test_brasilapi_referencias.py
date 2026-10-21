import json
import unittest

from nivon.brasilapi_referencias import (
    ErroBrasilAPI, NCM_URL_BASE, TAXAS_URL,
    normalizar_ncm_individual, normalizar_taxas_sem_data,
)

COLETA = "2026-10-21T11:00:00-04:00"
NCM = {
    "codigo": "3305.10.00", "descricao": "- Xampus",
    "data_inicio": "2022-04-01", "data_fim": "9999-12-31",
    "tipo_ato": "Res Camex", "numero_ato": "000272", "ano_ato": "2021",
}


def raw(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class TestBrasilAPIReferencias(unittest.TestCase):
    def ncm(self, item=None, **kw):
        return normalizar_ncm_individual(raw(NCM if item is None else item),
                                         codigo_consultado="33051000", coletado_em=COLETA, **kw)

    def taxas(self, obj=None):
        return normalizar_taxas_sem_data(
            raw(obj if obj is not None else [
                {"nome": "Selic", "valor": 13.75},
                {"nome": "CDI", "valor": 13.65},
                {"nome": "IPCA", "valor": 4.58},
            ]), coletado_em=COLETA)

    def test_ncm_individual_consistente_com_amostra_fornecida(self):
        r = self.ncm()
        self.assertEqual(r["codigo_ncm"], "33051000")
        self.assertEqual(r["origem_url"], NCM_URL_BASE + "33051000")
        self.assertEqual(r["coleta"], "2026-10-21T15:00:00+00:00")
        self.assertEqual(r["numero_ato"], "000272")
        self.assertIsNone(r["vigencia_fim"])
        self.assertTrue(r["vigencia_sem_fim_definido"])
        self.assertFalse(r["apto_publicacao_automatica"])
        self.assertEqual(len(r["sha256_original"]), 64)

    def test_ncm_com_fim_finito(self):
        r = self.ncm({**NCM, "data_fim": "2026-09-30"})
        self.assertEqual(r["vigencia_fim"], "2026-09-30")
        self.assertFalse(r["vigencia_sem_fim_definido"])

    def test_ncm_nao_pode_trocar_identificador(self):
        with self.assertRaises(ErroBrasilAPI):
            self.ncm({**NCM, "codigo": "1201.90.00"})

    def test_ncm_nao_inventa_registro_se_ausente(self):
        for dado in ([], [NCM], {}, {"codigo": "3305.10.00"}, {**NCM, "descricao": ""}):
            with self.subTest(dado=dado), self.assertRaises(ErroBrasilAPI):
                self.ncm(dado)

    def test_ncm_data_invalida_ou_invertida(self):
        for item in ({**NCM, "data_inicio": "2022-02-31"},
                     {**NCM, "data_inicio": "2022-04-01", "data_fim": "2022-03-31"}):
            with self.assertRaises(ErroBrasilAPI):
                self.ncm(item)

    def test_ncm_nao_converte_codigos_de_sete_ou_nove_digitos(self):
        for codigo in ("421870705", "5105259", "abcd.10.00", "330510000"):
            with self.assertRaises(ErroBrasilAPI):
                normalizar_ncm_individual(raw(NCM), codigo_consultado=codigo, coletado_em=COLETA)

    def test_taxas_inspecao_sem_datas_e_sem_publicacao(self):
        r = self.taxas()
        self.assertEqual(r["origem_url"], TAXAS_URL)
        self.assertEqual(len(r["indicadores"]), 3)
        self.assertEqual(r["indicadores"][-1]["valor_reportado"], "13.75")
        self.assertTrue(all(x["referencia"] is None for x in r["indicadores"]))
        self.assertFalse(r["apto_briefing"])
        self.assertFalse(r["apto_tendencias"])
        self.assertFalse(r["apto_serie_historica"])

    def test_taxas_aceitam_valores_negativos_sem_fingir_data(self):
        r = self.taxas([{"nome": "IPCA", "valor": -0.12}])
        self.assertEqual(r["indicadores"][0]["valor_reportado"], "-0.12")

    def test_taxas_rejeitam_payload_invalido(self):
        for item in ([], {}, [{"nome": "CDI", "valor": "13.65"}],
                     [{"nome": "IPCA", "valor": float("nan")}],
                     [{"nome": "CDI", "valor": 13}, {"nome": "cdi", "valor": 14}],
                     [{"nome": "CDI", "valor": True}]):
            with self.subTest(item=item), self.assertRaises(ErroBrasilAPI):
                self.taxas(item)

    def test_json_com_chave_duplicada_rejeitado(self):
        with self.assertRaises(ErroBrasilAPI):
            normalizar_ncm_individual(b'{"codigo":"3305.10.00","codigo":"3305.10.00"}',
                                      codigo_consultado="33051000", coletado_em=COLETA)

    def test_nao_aceita_coleta_sem_fuso(self):
        with self.assertRaises(ErroBrasilAPI):
            normalizar_taxas_sem_data(raw([{"nome": "CDI", "valor": 13.65}]),
                                      coletado_em="2026-10-21T11:00:00")

    def test_rejeita_json_gigante_e_vazio(self):
        for payload in (b"", b"x" * 1_000_001):
            with self.assertRaises(ErroBrasilAPI):
                normalizar_taxas_sem_data(payload, coletado_em=COLETA)


if __name__ == "__main__":
    unittest.main()
