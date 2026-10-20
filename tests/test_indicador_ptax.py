"""PTAX armazenada (mock autorizado em catálogo isolado) -> briefing, sem rede.

Nenhuma cotação real, licença de fonte ou publicação é inferida pelo teste.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nivon.pipeline_api_dados import abrir_registro, ingerir_json_local
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.indicador_ptax import indicador_ptax_sqlite, ErroIndicadorPTAX
from nivon.indicadores_historicos import compor_pacote_historico
from nivon.rotina_diaria import preparar_rotina
from nivon.ensaio_vertical import executar
from nivon.hermes_adapter import NivonProjectAdapter

NOW="2026-10-20T15:00:00+00:00"
EARLY="2026-10-20T11:59:00+00:00"
CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB",
                  "enabled":True,"collection_authorized":True}]}
RIGHTS={"BCB_PTAX":{"status_direitos":"APROVADA",
                    "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
        "CME":{"status_direitos":"APROVADA",
               "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]}}
PLAN=planejar_consultas_ptax(moeda="USD",inicio="2026-10-19",fim="2026-10-20")[0]
BOLSA={"fonte_id":"CME","secao":"BOLSAS","titulo":"CBOT fixture",
       "valor":"1.000 cents/bu","fonte":"CME fixture não real",
       "referencia":NOW}


def body(entries):
    return json.dumps({"value":entries}).encode()


def boletim(cotacao=5.2, hora="2026-10-20 09:04:00", tipo="Fechamento"):
    return {"cotacaoCompra":cotacao,"cotacaoVenda":cotacao+.02,
            "dataHoraCotacao":hora,"tipoBoletim":tipo}


class TestPTAXIndicador(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")

    def tearDown(self):
        self.db.close()

    def registrar(self, entries=None, *, coleta="2026-10-20T13:00:00+00:00",
                  tipo="REAL_AUTORIZADO"):
        return ingerir_json_local(
            self.db,CAT,dataset_id="BCB_PTAX",
            payload=body(entries if entries is not None else [boletim()]),
            plano=PLAN,coletado_em=coleta,tipo=tipo,
            autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
            evidencia_direitos="APENAS_FIXTURE_TESTE",
        )

    def test_ptax_fechamento_no_briefing_sem_dolar_comercial(self):
        self.registrar()
        r=indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes=RIGHTS)
        self.assertEqual(r["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("Fechamento",r["indicador"]["titulo"])
        self.assertIn("5,2000",r["indicador"]["valor"])
        self.assertIn("5,2200",r["indicador"]["valor"])
        self.assertFalse(r["evidencia"]["apto_backtest_por_publicacao"])
        self.assertEqual(r["evidencia"]["classe"],"REAL_AUTORIZADO")
        pacote=compor_pacote_historico(
            db_conab=None,db_portos=None,db_mercados=self.db,
            incluir_ptax_usd=True,fontes=RIGHTS,gerado_em=NOW,
            indicadores_externos=[BOLSA])
        self.assertEqual(pacote["resultados"][0]["origem"],"BCB_PTAX")
        final=preparar_rotina(
            pacote=pacote["pacote"],gerado_em=NOW,
            auditor=lambda b:not b["rejeicoes"])
        self.assertEqual(final["status"],"VALIDADO_DRY_RUN")
        self.assertIn("PTAX USD/BRL",final["texto"])
        self.assertIn("CBOT fixture",final["texto"])

    def test_sinteticos_nao_entram_mesmo_se_fonte_aprovada(self):
        self.registrar(tipo="SINTETICO")
        r=indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes=RIGHTS)
        self.assertEqual(r["status"],"SEM_OBSERVACAO_REAL")
        pacote=compor_pacote_historico(
            db_conab=None,db_portos=None,db_mercados=self.db,
            incluir_ptax_usd=True,fontes=RIGHTS,gerado_em=NOW)
        self.assertEqual(pacote["resultados"][0]["status"],"SEM_OBSERVACAO_REAL")

    def test_direitos_ausentes_bloqueiam(self):
        self.registrar()
        self.assertEqual(
            indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes={})["status"],
            "BLOQUEADO_DIREITOS")

    def test_sem_banco_impede_o_briefing_com_ptax_exigida(self):
        pacote=compor_pacote_historico(
            db_conab=None,db_portos=None,db_mercados=None,
            incluir_ptax_usd=True,fontes=RIGHTS,gerado_em=NOW)
        self.assertEqual(pacote["resultados"][0]["status"],"SEM_HISTORICO")

    def test_cotacao_posterior_ao_corte_nao_vaza(self):
        self.registrar()
        r=indicador_ptax_sqlite(self.db,gerado_em=EARLY,fontes=RIGHTS)
        self.assertEqual(r["status"],"SEM_OBSERVACAO_REAL")

    def test_rejeita_cotacao_vencida(self):
        self.registrar(entries=[boletim(hora="2026-10-01 09:04:00")])
        r=indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes=RIGHTS)
        self.assertEqual(r["status"],"DADO_VENCIDO")

    def test_preenche_fechamento_antes_intermediario(self):
        self.registrar(entries=[
            boletim(5.25,hora="2026-10-20 09:04:00",tipo="Fechamento"),
            boletim(5.30,hora="2026-10-20 09:10:00",tipo="Intermediário"),
        ],coleta="2026-10-20T14:00:00+00:00")
        r=indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes=RIGHTS)
        self.assertIn("5,2500",r["indicador"]["valor"])
        self.assertEqual(r["evidencia"]["tipo_selecionado"],"FECHAMENTO")

    def test_revisao_incompatível_na_mesma_hora_bloqueia(self):
        self.registrar(entries=[boletim(5.10)],coleta="2026-10-20T13:00:00+00:00")
        self.registrar(entries=[boletim(5.30)],coleta="2026-10-20T14:00:00+00:00")
        r=indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes=RIGHTS)
        self.assertEqual(r["status"],"VINTAGES_CONFLITANTES")

    def test_valores_nao_finitos_ou_corrompidos_bloqueiam(self):
        self.registrar()
        self.db.execute("""UPDATE nivon_observacoes_api
          SET observacao_json=?""",(json.dumps({
              "moeda":"USD",
              "referencia_data_hora_utc":"2026-10-20T12:04:00+00:00",
              "cotacao_compra_brl_por_moeda":-1,
              "cotacao_venda_brl_por_moeda":5.2,
          }),))
        with self.assertRaises(ErroIndicadorPTAX):
            indicador_ptax_sqlite(self.db,gerado_em=NOW,fontes=RIGHTS)

    def test_cli_integrado_com_banco_ptax_em_ro(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            self.db.close()
            dbpath=p/"mercado.sqlite"
            self.db=abrir_registro(str(dbpath))
            self.registrar()
            inp=p/"pacote.json"
            inp.write_text(json.dumps({
                "noticias":[],"fontes":RIGHTS,"indicadores":[BOLSA],
            }),encoding="utf8")
            cfg=p/"contratos.json"
            cfg.write_text('{"culturas":[],"portos":[]}',encoding="utf8")
            target=p/"briefing.txt"
            resp=executar(["--entrada",str(inp),"--contratos",str(cfg),
                           "--db-mercados",str(dbpath),"--incluir-ptax-usd",
                           "--gerado-em",NOW,"--saida",str(target)])
            self.assertEqual(resp["status"],"ENSAIO_OFFLINE_VALIDADO")
            self.assertTrue(target.exists())
            self.assertIn("PTAX USD/BRL",target.read_text(encoding="utf8"))

    async def _unused(self):
        pass


class TestHermesPTAX(unittest.IsolatedAsyncioTestCase):
    async def test_hermes_explicitamente_requer_mercado(self):
        adapter=NivonProjectAdapter(
            autorizador=lambda _:True,fontes=RIGHTS)
        r=await adapter.query("briefing.preview",{
            "gerado_em":NOW,"indicadores":[BOLSA],
            "incluir_ptax_usd":True,
        })
        self.assertEqual(r["status"],"BLOQUEADO_HISTORICOS")

    async def test_hermes_nao_aceita_tipo_de_flag_invalido(self):
        adapter=NivonProjectAdapter(
            autorizador=lambda _:True,fontes=RIGHTS)
        with self.assertRaises(ValueError):
            await adapter.query("briefing.preview",{
                "gerado_em":NOW,"incluir_ptax_usd":"sim",
            })


if __name__=="__main__":
    unittest.main()
