import unittest

from nivon.bcb_ptax import ErroPTAX, normalizar_ptax_odata


URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
    "dataFinalCotacao=@dataFinalCotacao)"
)
COLETA = "2026-10-19T18:00:00Z"


class TestPTAX(unittest.TestCase):
    def row(self, **extra):
        d = {
            "cotacaoCompra": 5.28,
            "cotacaoVenda": 5.30,
            "dataHoraCotacao": "2026-10-19 13:00:00",
            "tipoBoletim": "Fechamento",
        }
        d.update(extra)
        return d

    def analisar(self, linhas=None):
        return normalizar_ptax_odata(
            {"value": linhas if linhas is not None else [self.row()]},
            moeda="USD", coletado_em=COLETA, consulta_url=URL,
        )

    def test_ptax_conversao_fuso_sem_inventar_publicacao(self):
        res = self.analisar()
        x = res["observacoes"][0]
        self.assertEqual(x["referencia_data_hora_utc"], "2026-10-19T16:00:00+00:00")
        self.assertEqual(x["competencia"], "2026-10-19")
        self.assertIsNone(x["publicacao"])
        self.assertEqual(x["coleta"], "2026-10-19T18:00:00+00:00")

    def test_paridades_opcionais_em_pares(self):
        x = self.analisar([self.row(paridadeCompra=1.0, paridadeVenda=1.01)])
        self.assertEqual(x["observacoes"][0]["paridade_venda"], 1.01)

    def test_lista_vazia_nao_retorna_preco_zero(self):
        with self.assertRaises(ErroPTAX):
            self.analisar([])

    def test_preco_compra_venda_nao_inverter(self):
        with self.assertRaises(ErroPTAX):
            self.analisar([self.row(cotacaoVenda=5.0)])

    def test_nao_aceitar_url_fora_bcb(self):
        with self.assertRaises(ErroPTAX):
            normalizar_ptax_odata(
                {"value": [self.row()]}, moeda="USD", coletado_em=COLETA,
                consulta_url="https://ptax.invalid/odata/"
            )

    def test_moeda_sem_contrato_rejeitada(self):
        with self.assertRaises(ErroPTAX):
            normalizar_ptax_odata(
                {"value": [self.row()]}, moeda="XYZ", coletado_em=COLETA,
                consulta_url=URL
            )

    def test_vintos_de_boletim_nao_viram_mesmo_dado(self):
        res = self.analisar([
            self.row(dataHoraCotacao="2026-10-19 10:00:00", tipoBoletim="Abertura"),
            self.row(dataHoraCotacao="2026-10-19 13:00:00", tipoBoletim="Fechamento"),
        ])
        self.assertEqual(res["numero_de_boletins"], 2)

    def test_mesmo_boletim_duplicado_bloqueado(self):
        with self.assertRaises(ErroPTAX):
            self.analisar([self.row(), self.row()])

    def test_payload_malformado_bloqueado(self):
        with self.assertRaises(ErroPTAX):
            normalizar_ptax_odata({}, moeda="USD", coletado_em=COLETA, consulta_url=URL)

    def test_ausencia_fuso_na_coleta(self):
        with self.assertRaises(ErroPTAX):
            normalizar_ptax_odata(
                {"value": [self.row()]}, moeda="USD",
                coletado_em="2026-10-19T13:00:00", consulta_url=URL
            )


if __name__ == "__main__":
    unittest.main()

    def test_paginacao_nao_descarta_boletins(self):
        with self.assertRaises(ErroPTAX):
            normalizar_ptax_odata(
                {"value":[self.row()],"@odata.nextLink":"https://olinda.bcb.gov.br/other"},
                moeda="USD",coletado_em=COLETA,consulta_url=URL)
