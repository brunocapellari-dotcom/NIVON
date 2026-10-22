import sqlite3
import unittest
from copy import deepcopy

from nivon.anp_semanal_store import (
    ErroANPOficial, consultar_preco_semanal,
    gravar_edicao_semanal, inicializar_store_anp,
)


def resumo(sha="a"*64, preco=5.85, semana="2026-10-17",
           coleta="2026-10-20T15:00:00+00:00"):
    return {
        "dataset_id": "ANP_PRECO_REVENDA_DIESEL",
        "fonte": "ANP_RESUMO_LPC_SEMANAL",
        "sha256": sha, "coletado_em": coleta,
        "url_origem": "https://www.gov.br/anp/pt-br/assuntos/precos/arquivos-lpc/teste.xlsx",
        "publicavel": False,
        "observacoes": [{
            "uf": "MT", "municipio": "SORRISO", "produto": "DIESEL S10",
            "semana_inicio_oficial": "2026-10-11",
            "semana_fim_oficial": semana,
            "preco_medio_revenda_rs_l": preco,
            "postos_pesquisados": 8,
            "natureza": "MEDIA_AMOSTRAL_REVENDA_MUNICIPIO_ANP_SEMANA_OFICIAL",
        }],
    }


class TestANPSemanalStore(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        inicializar_store_anp(self.db)

    def tearDown(self):
        self.db.close()

    def grava(self, r=None, *, classe="SINTETICO",
              pub="2026-10-19T12:00:00+00:00", **kwargs):
        return gravar_edicao_semanal(
            self.db, resumo=r if r is not None else resumo(),
            data_publicacao=pub, prova_publicacao_sha="b"*64,
            classe=classe, **kwargs,
        )

    def consulta(self, **kw):
        params = dict(municipio="SORRISO", produto="DIESEL S10", uf="MT",
                      as_of="2026-10-20T17:00:00+00:00")
        params.update(kw)
        return consultar_preco_semanal(self.db, **params)

    def test_sintetico_nao_vira_real_ou_publicavel(self):
        self.assertFalse(self.grava()["fonte_publicavel"])
        self.assertEqual(self.consulta()["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 1)

    def test_idempotencia_e_coletas_separadas(self):
        self.assertTrue(self.grava()["captura_nova"])
        self.assertFalse(self.grava()["captura_nova"])
        mais = resumo(coleta="2026-10-20T16:00:00+00:00")
        self.assertTrue(self.grava(r=mais)["captura_nova"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_capturas").fetchone()[0], 2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_observacoes").fetchone()[0], 1)

    def test_publicacao_e_coleta_independentes_no_asof(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.assertEqual(self.consulta(
            as_of="2026-10-18T20:00:00+00:00")["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.consulta(
            as_of="2026-10-19T20:00:00+00:00")["status"], "SEM_EDICAO_REAL_ASOF")
        item = self.consulta()
        self.assertEqual(item["status"], "AMOSTRA_HISTORICA_PIT")
        self.assertEqual(item["preco_medio_revenda_brl_l"], "5.85")
        self.assertEqual(item["semana_fim_oficial"], "2026-10-17")
        self.assertFalse(item["publicavel"])
        self.assertEqual(item["primeira_coleta"], "2026-10-20T15:00:00+00:00")
        self.assertNotIn("frete", item["classe"].lower().replace("nao_frete",""))

    def test_revisao_entre_edicoes_nao_substitui_preco_implicitamente(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        novo = resumo(sha="d"*64, preco=5.90)
        novo["coletado_em"] = "2026-10-20T18:00:00+00:00"
        self.grava(r=novo, classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="e"*64)
        self.assertEqual(self.consulta()["status"], "AMOSTRA_HISTORICA_PIT")
        self.assertEqual(self.consulta(
            as_of="2026-10-21T00:00:00+00:00")["status"], "REVISOES_CONFLITANTES")
        self.assertFalse(self.consulta(
            as_of="2026-10-21T00:00:00+00:00")["publicavel"])

    def test_semana_vencida_nao_e_cotacao_atual(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.assertEqual(self.consulta(
            as_of="2026-12-01T00:00:00+00:00")["status"], "DADO_VENCIDO")

    def test_sem_direitos_nao_grava_fonte_real(self):
        with self.assertRaises(PermissionError):
            self.grava(classe="REAL_AUTORIZADO")
        with self.assertRaises(ErroANPOficial):
            self.grava(direitos_confirmados=True)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_conflito_mesmo_sha_nao_muda_historico(self):
        self.grava()
        dif = resumo(preco=6.5)
        with self.assertRaisesRegex(ErroANPOficial, "mesmo SHA"):
            self.grava(r=dif)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_capturas").fetchone()[0], 1)

    def test_datas_de_publicacao_e_serie_incorretas(self):
        with self.assertRaises(ErroANPOficial):
            self.grava(pub="2026-10-21T12:00:00+00:00")
        with self.assertRaises(ErroANPOficial):
            self.grava(pub="2026-10-19T12:00:00")
        with self.assertRaises(ErroANPOficial):
            self.grava(r=resumo(semana="2026-11-17"))
        with self.assertRaises(ErroANPOficial):
            self.grava(r=resumo(coleta="2026-10-18T12:00:00+00:00"))

    def test_duplicatas_e_campos_adversariais(self):
        for change in [
            {"produto": "GASOLINA"},
            {"preco_medio_revenda_rs_l": -1},
            {"preco_medio_revenda_rs_l": float("nan")},
            {"preco_medio_revenda_rs_l": True},
            {"postos_pesquisados": 0},
            {"semana_inicio_oficial": "2026-10-12"},
            {"municipio": ""},
            {"natureza": "DIESEL_PRECO_CONTRATADO"},
        ]:
            r = resumo()
            r["observacoes"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ErroANPOficial):
                self.grava(r=r)
        dup = resumo()
        dup["observacoes"].append(deepcopy(dup["observacoes"][0]))
        with self.assertRaisesRegex(ErroANPOficial, "repetida"):
            self.grava(r=dup)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_edição_não_confunde_com_csv_mensal(self):
        r = resumo()
        r["fonte"] = "ANP_SERIE_ABERTA_PRECOS_DIESEL"
        with self.assertRaises(ErroANPOficial):
            self.grava(r=r)

    def test_uf_produto_e_municipio_nao_intercambiam(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.assertEqual(self.consulta(produto="DIESEL")["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.consulta(uf="GO")["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.consulta(municipio="SINOP")["status"], "SEM_EDICAO_REAL_ASOF")


if __name__ == "__main__":
    unittest.main()
