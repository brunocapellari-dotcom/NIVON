"""Contrato de adaptadores reais do painel com leitores simulados e sem GCP."""
import unittest

from nivon.painel_operacional import ErroMotor
from nivon.ponte_painel_fontes import analisar_fontes
from nivon.painel_operacional import ErroMotor
from test_painel_operacional import AS_OF, preco


CONSULTA = {
    "project_id": "nivon-data", "dataset_id": "agro",
    "fonte": "BR_FRETE_ANUNCIADO", "inicio": "2026-10-01", "fim": "2026-10-23",
    "classe": "FRETE_ANUNCIADO", "serie_id": "RONDONOPOLIS_SANTOS_SOJA_A",
}
REGISTROS = [preco(d, v) for d, v in (
    (10, 100), (11, 100), (12, 100), (17, 105), (18, 110), (20, 110),
)]


class AdaptacaoFonteTests(unittest.TestCase):
    def test_config_bigquery_planejada_sem_rede(self):
        def nao_pode_chamar(**kwargs):
            raise AssertionError("tentou ler BigQuery sem opt-in")
        r = analisar_fontes({"consultas_bigquery": [CONSULTA]}, as_of=AS_OF,
                           leitor_bq=nao_pode_chamar)
        self.assertFalse(r["executou_bigquery"])
        self.assertEqual(r["fontes_bigquery"][0]["status"], "PLANO_SEM_REDE")
        self.assertEqual(r["quantitativo"][0]["status"], "DADOS_INSUFICIENTES")

    def test_consulta_reusa_motor_e_filtra_serie(self):
        chamadas = []
        def ler(**kwargs):
            chamadas.append(kwargs)
            return {"executado": True, "fonte": CONSULTA["fonte"],
                    "as_of": AS_OF.replace("Z", "+00:00"), "quantidade": 6,
                    "observacoes": REGISTROS}
        r = analisar_fontes({"consultas_bigquery": [CONSULTA]}, as_of=AS_OF,
                           executar_bigquery=True, leitor_bq=ler, cliente_bigquery="mock")
        self.assertEqual(len(chamadas), 1)
        self.assertTrue(chamadas[0]["executar"])
        self.assertEqual(chamadas[0]["client"], "mock")
        self.assertEqual(chamadas[0]["classe"], "FRETE_ANUNCIADO")
        self.assertEqual(chamadas[0]["serie_id"], CONSULTA["serie_id"])
        self.assertEqual(r["quantitativo"][0]["tendencia"], "ALTA")
        self.assertEqual(r["fontes_bigquery"][0]["linhas_filtradas"], 6)
        self.assertTrue(r["executou_bigquery"])
        self.assertFalse(r["quantitativo"][0]["publicavel"])

    def test_resposta_fora_do_escopo_e_recusada_sem_filtrar_silenciosamente(self):
        def responder_errado(**kwargs):
            return {"executado":True, "fonte":CONSULTA["fonte"], "as_of":AS_OF,
                    "quantidade":7,
                    "observacoes":REGISTROS+[preco(20,999,serie_id="OUTRA_SERIE")]}
        with self.assertRaises(ErroMotor):
            analisar_fontes({"consultas_bigquery":[CONSULTA]},as_of=AS_OF,
                           executar_bigquery=True,leitor_bq=responder_errado)

    def test_lote_truncado_nao_publica_tendencia_parcial(self):
        def ler(**kwargs):
            return {"executado": True, "fonte": CONSULTA["fonte"],
                    "as_of": AS_OF, "quantidade": 6, "observacoes": REGISTROS}
        cfg = CONSULTA | {"limite": 6}
        r = analisar_fontes({"consultas_bigquery": [cfg]}, as_of=AS_OF,
                           executar_bigquery=True, leitor_bq=ler)
        self.assertEqual(r["quantitativo"][0]["status"], "DADOS_INSUFICIENTES")
        self.assertEqual(r["fontes_bigquery"][0]["status"], "LIMITE_ATINGIDO_SERIE_NAO_AVALIADA")

    def test_resposta_bq_inconsistente_e_config_insegura_bloqueadas(self):
        with self.assertRaises(ErroMotor):
            analisar_fontes({"consultas_bigquery": [CONSULTA]}, as_of=AS_OF,
                            executar_bigquery=True, leitor_bq=lambda **_: {"executado": False})
        with self.assertRaises(ValueError):
            analisar_fontes({"consultas_bigquery": [CONSULTA | {"dataset_id": "x; DROP"}]},
                            as_of=AS_OF)
        with self.assertRaises(ErroMotor):
            analisar_fontes({"consultas_bigquery": [CONSULTA, CONSULTA]}, as_of=AS_OF)
        with self.assertRaises(ErroMotor):
            analisar_fontes({"consultas_bigquery": [CONSULTA] * 11}, as_of=AS_OF)

    def test_sqlite_real_reutilizado_sem_refazer_engenharia_antt(self):
        chamadas = []
        def consultar(banco, **kw):
            chamadas.append((banco, kw))
            return {"estado": "RECORTE_IMPORTADO_NAO_HOMOLOGADO", "recorte": kw["recorte"],
                    "competencia": kw["competencia"], "resumo_polos": []}
        cfg = {"corredores_sqlite": {"banco": "/private/stage/antt.sqlite",
                                    "recorte": "mt_amostra",
                                    "competencia": "2026-09"}}
        r = analisar_fontes(cfg, as_of=AS_OF, leitor_corredores=consultar)
        self.assertEqual(r["logistica"]["recorte"], "mt_amostra")
        self.assertEqual(chamadas[0][0], cfg["corredores_sqlite"]["banco"])
        self.assertEqual(chamadas[0][1]["limite"], 1000)

    def test_bloquear_dupla_fonte_corredores_e_sem_soma_modal(self):
        with self.assertRaises(ErroMotor):
            analisar_fontes({"corredores": {}, "corredores_sqlite": {
                "banco": "a.sqlite", "recorte": "mt", "competencia": "2026-09",
            }}, as_of=AS_OF)
        r = analisar_fontes({}, as_of=AS_OF)
        self.assertEqual(r["logistica"]["status"], "DADOS_INSUFICIENTES")
        self.assertNotIn("volume_intermodal", r)


if __name__ == "__main__":
    unittest.main()
