"""ANP diesel S10 anônimo: CSV -> SQLite vintage -> briefing, fixtures offline."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nivon.anp_diesel import CAMPOS, resumo_diesel_municipal
from nivon.anp_diesel_store import (
    abrir_historico_diesel, gravar_resumo_diesel,
    indicador_diesel_municipal, ErroHistoricoDiesel,
)
from nivon.indicadores_historicos import compor_pacote_historico
from nivon.rotina_diaria import preparar_rotina
from nivon.ensaio_vertical import executar
from nivon.hermes_adapter import NivonProjectAdapter


TIME="2026-10-20T16:00:00+00:00"
URL="https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/fixture"
RIGHTS={
    "ANP_DIESEL":{"status_direitos":"APROVADA",
                  "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "CME":{"status_direitos":"APROVADA",
           "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "BCB":{"status_direitos":"APROVADA",
           "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
LOCAL={"uf":"MT","municipio":"SINOP","produto":"DIESEL S10"}
INDICADORES=[
 {"fonte_id":"CME","secao":"BOLSAS","titulo":"CBOT simulado","valor":"1020 c/bu",
  "referencia":TIME,"fonte":"CME fixture não real"},
 {"fonte_id":"BCB","secao":"CAMBIO","titulo":"PTAX simulada","valor":"R$ 5,10",
  "referencia":TIME,"fonte":"BCB fixture não real"},
]


def amostra(valor="6,45", produto="DIESEL S10", municipio="SINOP",
            data="19/10/2026", identidade="SEGREDO_CNPJ_SINTETICO"):
    record={
        "Regiao - Sigla":"CO","Estado - Sigla":"MT","Municipio":municipio,
        "Revenda":"SEGREDO_REVENDA_SINTETICO",
        "CNPJ da Revenda":identidade,"Nome da Rua":"SEGREDO_RUA_SINTETICO",
        "Numero Rua":"1","Complemento":"","Bairro":"CENTRO",
        "Cep":"00000000","Produto":produto,"Data da Coleta":data,
        "Valor de Venda":valor,"Valor de Compra":"",
        "Unidade de Medida":"R$ / litro","Bandeira":"BRANCA",
    }
    return ";".join(record[x] for x in CAMPOS)+"\n"


def csv(*linhas):
    return (";".join(CAMPOS)+"\n"+"".join(linhas)).encode("utf-8-sig")


class TestANPDieselStore(unittest.TestCase):
    def setUp(self):
        self.db=abrir_historico_diesel()

    def tearDown(self):
        self.db.close()

    def armazenar(self, *, preco="6,45", produto="DIESEL S10",
                  data="19/10/2026", coleta="2026-10-20T14:00:00+00:00",
                  classe="REAL_AUTORIZADO"):
        resumo=resumo_diesel_municipal(
            csv(amostra(preco,produto=produto,data=data)),mes_esperado="2026-10")
        return gravar_resumo_diesel(self.db,resumo,fonte_url=URL,
             coletado_em=coleta,tipo=classe,
             evidencia_direitos=("FIXTURE_DOCUMENTO" if classe=="REAL_AUTORIZADO" else None),
             direitos_confirmados=(classe=="REAL_AUTORIZADO"))

    def indicador(self, **kw):
        return indicador_diesel_municipal(
            self.db, gerado_em=TIME, fontes=RIGHTS, **{**LOCAL,**kw})

    def test_guarda_apenas_agregados_sem_cnpj(self):
        self.armazenar()
        full=json.dumps({
            "edicoes":[tuple(row) for row in self.db.execute("SELECT * FROM diesel_edicoes")],
            "linhas":[tuple(row) for row in self.db.execute("SELECT * FROM diesel_municipios")],
        })
        for forbidden in ("SEGREDO_CNPJ_SINTETICO","SEGREDO_REVENDA_SINTETICO",
                          "SEGREDO_RUA_SINTETICO"):
            self.assertNotIn(forbidden,full)

    def test_preco_s10_com_evidencia_e_sem_paridade(self):
        self.armazenar()
        r=self.indicador()
        self.assertEqual(r["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("R$ 6.450/L",r["indicador"]["valor"])
        self.assertIn("DIESEL S10",r["indicador"]["titulo"])
        self.assertEqual(r["evidencia"]["postos_observacoes"],1)
        self.assertIsNone(r["evidencia"]["publicacao"])
        self.assertIn("NAO_PPI",r["evidencia"]["classificacao"])
        self.assertTrue(r["evidencia"]["amostra_parcial_possivel"])

    def test_sintetico_nao_pode_ser_publicado(self):
        self.armazenar(classe="SINTETICO")
        self.assertEqual(self.indicador()["status"],"SEM_OBSERVACAO_REAL")

    def test_sem_direito_derivado_bloqueia(self):
        self.armazenar()
        r=indicador_diesel_municipal(self.db,gerado_em=TIME,
                                    fontes={},**LOCAL)
        self.assertEqual(r["status"],"BLOQUEADO_DIREITOS")

    def test_falta_licenca_para_real_nao_grava(self):
        summary=resumo_diesel_municipal(
            csv(amostra()),mes_esperado="2026-10")
        with self.assertRaises(PermissionError):
            gravar_resumo_diesel(self.db,summary,fonte_url=URL,
                 coletado_em=TIME,tipo="REAL_AUTORIZADO")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM diesel_edicoes").fetchone()[0],0)

    def test_dados_distintos_mesmo_conteudo_rejeitados(self):
        self.armazenar()
        self.armazenar()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM diesel_edicoes").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM diesel_capturas").fetchone()[0],1)
        with self.assertRaises(ErroHistoricoDiesel):
            self.armazenar(classe="SINTETICO")

    def test_revenda_diesel_e_s10_nao_misturados(self):
        self.armazenar(produto="DIESEL")
        self.assertEqual(self.indicador()["status"],"SEM_OBSERVACAO_REAL")
        r=self.indicador(produto="DIESEL")
        self.assertEqual(r["status"],"INDICADOR_VERIFICADO_TEMPO")

    def test_vintage_no_futuro_nao_vaza(self):
        self.armazenar(coleta="2026-10-21T14:00:00+00:00")
        self.assertEqual(self.indicador()["status"],"SEM_OBSERVACAO_REAL")

    def test_arquivo_anp_antigo_nao_renovado_pela_coleta(self):
        self.armazenar(data="01/10/2026")
        r=self.indicador(limite_dias_semana=5)
        self.assertEqual(r["status"],"DADO_VENCIDO")

    def test_duas_edicoes_conflitantes_na_mesma_semana(self):
        self.armazenar(preco="6,45")
        self.armazenar(preco="6,50",coleta="2026-10-20T15:00:00+00:00")
        self.assertEqual(self.indicador()["status"],"VINTAGES_CONFLITANTES")

    def test_conexao_readonly_closing_versus_escrita(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"diesel.sqlite"
            self.db.close()
            self.db=abrir_historico_diesel(path)
            self.armazenar()
            self.db.commit()
            self.db.close()
            inp=Path(d)/"in.json"
            cfg=Path(d)/"scope.json"
            dest=Path(d)/"briefing.txt"
            inp.write_text(json.dumps({"fontes":RIGHTS,"indicadores":INDICADORES,
                                       "noticias":[]}),encoding="utf-8")
            cfg.write_text(json.dumps({"culturas":[],"portos":[],
                                       "diesel":[LOCAL]}),encoding="utf-8")
            resp=executar(["--entrada",str(inp),"--contratos",str(cfg),
                          "--db-diesel",str(path),"--gerado-em",TIME,
                          "--saida",str(dest)])
            self.assertEqual(resp["status"],"ENSAIO_OFFLINE_VALIDADO")
            txt=dest.read_text(encoding="utf-8")
            self.assertIn("DIESEL S10 revenda",txt)
            self.assertIn("CBOT simulado",txt)
            self.db=abrir_historico_diesel(path)

    def test_bloqueio_nao_gera_briefing_incompleto(self):
        p=compor_pacote_historico(db_conab=None,db_portos=None,
                                 db_diesel=self.db,diesel_localidades=[LOCAL],
                                 gerado_em=TIME,fontes=RIGHTS,
                                 indicadores_externos=INDICADORES)
        self.assertEqual(p["resultados"][0]["status"],"SEM_OBSERVACAO_REAL")


class TestHermesDiesel(unittest.IsolatedAsyncioTestCase):
    async def test_preview_sem_base_falha_fechada(self):
        adapter=NivonProjectAdapter(autorizador=lambda _:True,fontes=RIGHTS)
        r=await adapter.query("briefing.preview",{
            "gerado_em":TIME,"indicadores":INDICADORES,
            "diesel_localidades":[LOCAL]})
        self.assertEqual(r["status"],"BLOQUEADO_HISTORICOS")

    async def test_lista_municipios_malformada(self):
        adapter=NivonProjectAdapter(autorizador=lambda _:True,fontes=RIGHTS)
        with self.assertRaises(ValueError):
            await adapter.query("briefing.preview",{
                "gerado_em":TIME,"diesel_localidades":[{"uf":"MT","sql":"DROP TABLE"}]})


if __name__=="__main__":
    unittest.main()
