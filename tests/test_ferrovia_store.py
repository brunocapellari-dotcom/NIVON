import unittest

from nivon.ferrovia_store import (
    ErroHistoricoFerroviario, abrir_banco, consultar_ferrovia_em, guardar_serie,
)


def carga(*, sha="a"*64,tu=100.0,origem="RONDONOPOLIS",destino="SANTOS"):
    return {
        "arquivo_sha256":sha,
        "periodo":"2026-08",
        "mercadoria_antt":"Grãos - Milho",
        "origem_uf":"MT","destino_uf":"SP",
        "origem_estacao":origem,"destino_estacao":destino,
        "tu_t":tu,"tku":tu*650,
        "modal":"FERROVIARIO","local_tipo":"ESTACAO_NAO_MUNICIPIO",
    }


class TestHistoricoFerrovia(unittest.TestCase):
    def setUp(self):
        self.conn=abrir_banco(":memory:")
        self.addCleanup(self.conn.close)

    def teste(self, cargas=None, instante="2026-09-01T14:00:00Z"):
        return guardar_serie(self.conn, cargas if cargas is not None else [carga()],
                            coletado_em=instante)

    def test_primeira_edicao_e_mes(self):
        x=self.teste()
        self.assertTrue(x["nova_edicao"])
        self.assertEqual(x["series_agregadas"],1)
        y=consultar_ferrovia_em(self.conn,corte_utc="2026-09-02T00:00:00Z",mes="2026-08")
        self.assertEqual(y["rotas"][0]["tu_t"],100)

    def test_antes_de_coleta_nao_conhecia(self):
        self.teste()
        x=consultar_ferrovia_em(self.conn,corte_utc="2026-08-30T00:00:00Z",mes="2026-08")
        self.assertEqual(x["estado"],"SEM_COLETA")

    def test_coleta_repetida_mesmo_hash_idempotente(self):
        self.teste()
        y=self.teste()
        self.assertFalse(y["nova_edicao"])
        self.assertFalse(y["nova_coleta"])

    def test_mesma_edicao_nova_data_preserva_coleta(self):
        self.teste()
        y=self.teste(instante="2026-09-02T14:00:00Z")
        self.assertFalse(y["nova_edicao"])
        self.assertTrue(y["nova_coleta"])
        self.assertEqual(self.conn.execute("select count(*) from coletas_ferrovia").fetchone()[0],2)

    def test_revisao_preserva_antigo_no_asof(self):
        self.teste()
        self.teste([carga(sha="b"*64,tu=110)],instante="2026-09-10T00:00:00Z")
        antigo=consultar_ferrovia_em(self.conn,corte_utc="2026-09-09T00:00:00Z",mes="2026-08")
        novo=consultar_ferrovia_em(self.conn,corte_utc="2026-09-11T00:00:00Z",mes="2026-08")
        self.assertEqual(antigo["rotas"][0]["tu_t"],100)
        self.assertEqual(novo["rotas"][0]["tu_t"],110)

    def test_mesma_chave_agrega_linhas_na_edicao(self):
        x=self.teste([carga(tu=100),carga(tu=40)])
        self.assertEqual(x["registros_origem"],2)
        self.assertEqual(x["series_agregadas"],1)
        y=consultar_ferrovia_em(self.conn,corte_utc="2026-09-02T00:00:00Z",mes="2026-08")
        self.assertEqual(y["rotas"][0]["tu_t"],140)

    def test_mesmo_hash_conteudo_diferente_rejeita(self):
        self.teste()
        with self.assertRaises(ErroHistoricoFerroviario):
            self.teste([carga(tu=99)],instante="2026-09-02T00:00:00Z")

    def test_duas_edicoes_no_mesmo_lote_rejeita(self):
        with self.assertRaises(ErroHistoricoFerroviario):
            self.teste([carga(),carga(sha="b"*64)])

    def test_nao_confunde_rodoviario(self):
        x=carga()
        x["modal"]="RODOVIARIO"
        with self.assertRaises(ErroHistoricoFerroviario):
            self.teste([x])

    def test_volume_negativo_rejeita(self):
        with self.assertRaises(ErroHistoricoFerroviario):
            self.teste([carga(tu=-1)])

    def test_temporal_exige_fuso(self):
        with self.assertRaises(ErroHistoricoFerroviario):
            self.teste(instante="2026-09-01T14:00:00")

    def test_entrada_vazia_falha(self):
        with self.assertRaises(ErroHistoricoFerroviario):
            self.teste([])


if __name__=="__main__":
    unittest.main()
