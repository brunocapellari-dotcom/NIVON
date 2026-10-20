"""Mercados CME/CEPEA -> briefing: contrato, licença, clock e auditabilidade.

TODAS as cotações e licenças destes testes são sintéticas. Não demonstra
direito efetivo de revenda/redistribuição, nem coleta automática de bolsas.
"""
import json
from pathlib import Path
import tempfile
import unittest

from nivon.cotacoes_briefing import preparar_cotacoes_licenciadas
from nivon.cotacoes_externas import cotacao_para_briefing
from nivon.indicadores_historicos import compor_pacote_historico
from nivon.rotina_diaria import preparar_rotina
from nivon.ensaio_vertical import executar
from nivon.hermes_adapter import NivonProjectAdapter

NOW="2026-10-20T15:00:00+00:00"
REF="2026-10-19T20:00:00+00:00"
COLETA="2026-10-20T12:00:00+00:00"
SHA="a"*64
CME_URL="https://www.cmegroup.com/"
CEPEA_URL="https://www.cepea.esalq.usp.br/"
COTACOES=[
    {"fonte":"CME","tipo":"FECHAMENTO","produto":"Soja",
     "contrato":"NOV26","preco":"1251.50","unidade":"USC/BU",
     "referencia_em":REF,"coletado_em":COLETA,
     "fonte_url":CME_URL,"documento_sha256":SHA},
    {"fonte":"CEPEA","tipo":"INDICADOR_FISICO","produto":"Soja Paranaguá",
     "preco":"154.20","unidade":"BRL/SC60KG",
     "referencia_em":REF,"coletado_em":COLETA,
     "fonte_url":CEPEA_URL,"documento_sha256":"b"*64},
]
LICENCAS={
    fid:{
      "fonte":fid,"status":"APROVADA","id_aprovacao":"FIXTURE_DOCUMENTAL_TESTE",
      "valida_ate":"2026-12-31",
      "operacoes":["LEITURA","ARMAZENAMENTO","PUBLICACAO_DERIVADA",
                  "REDISTRIBUICAO"],
    } for fid in ("CME","CEPEA")
}
FONTES={
    "CME":{"status_direitos":"APROVADA",
           "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "CEPEA":{"status_direitos":"APROVADA",
             "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "BCB":{"status_direitos":"APROVADA",
           "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
CAMBIO={"fonte_id":"BCB","secao":"CAMBIO",
        "titulo":"PTAX fixture","valor":"5,00 BRL/USD",
        "referencia":NOW,"fonte":"BCB fixture não real"}


class TestMercadosBriefing(unittest.TestCase):
    def test_cents_por_bushel_passa_com_fuso_e_contrato(self):
        result=cotacao_para_briefing(COTACOES[0],LICENCAS["CME"],gerado_em=NOW)
        self.assertEqual(result["referencia"],REF)
        self.assertIn("USC/BU",result["valor"])
        self.assertIn("NOV26",result["titulo"])

    def test_doisa_mercados_distintos_e_nao_confunde_fisico(self):
        r=preparar_cotacoes_licenciadas(
            cotacoes=COTACOES,licencas_verificadas=LICENCAS,gerado_em=NOW)
        self.assertEqual(r["status"],"NORMALIZADO_PARA_AUDITORIA")
        self.assertEqual([x["secao"] for x in r["indicadores"]],["BOLSAS","PRECOS"])
        self.assertEqual(len(r["evidencias"]),2)
        self.assertFalse(r["licenca_real_confirmada_pelo_codigo"])
        self.assertFalse(r["envio_automatico"])

    def test_fluxo_composto_ate_texto_com_data_e_fuso(self):
        p=compor_pacote_historico(
            db_conab=None,db_portos=None,
            fontes=FONTES,gerado_em=NOW,
            indicadores_externos=[CAMBIO],
            cotacoes_licenciadas=COTACOES,
            licencas_verificadas=LICENCAS)
        self.assertEqual(p["resultados"][0]["status"],"INDICADOR_VERIFICADO_TEMPO")
        f=preparar_rotina(pacote=p["pacote"],gerado_em=NOW,
                          auditor=lambda x:not x["rejeicoes"])
        self.assertEqual(f["status"],"VALIDADO_DRY_RUN")
        self.assertIn("NOV26",f["texto"])
        self.assertIn("Soja Paranaguá",f["texto"])
        self.assertIn("USC/BU",f["texto"])
        self.assertIn("PTAX fixture",f["texto"])

    def test_licenca_nao_comprovada_bloqueia_pacote(self):
        q=preparar_cotacoes_licenciadas(
            cotacoes=COTACOES,licencas_verificadas={},gerado_em=NOW)
        self.assertEqual(q["status"],"BLOQUEADO")
        self.assertEqual(q["indicadores"],[])
        p=compor_pacote_historico(
            db_conab=None,db_portos=None,fontes=FONTES,gerado_em=NOW,
            indicadores_externos=[CAMBIO],
            cotacoes_licenciadas=COTACOES,licencas_verificadas={})
        self.assertEqual(p["resultados"][0]["status"],"BLOQUEADO_COTACOES")

    def test_sem_redistribuicao_nao_publica(self):
        lic=json.loads(json.dumps(LICENCAS))
        lic["CME"]["operacoes"].remove("REDISTRIBUICAO")
        res=preparar_cotacoes_licenciadas(
            cotacoes=COTACOES,licencas_verificadas=lic,gerado_em=NOW)
        self.assertEqual(res["indicadores"],[])
        self.assertEqual(res["recusados"][0]["fonte"],"CME")

    def test_url_falsa_nao_passou_com_direitos_de_cme(self):
        lista=[{**COTACOES[0],"fonte_url":"https://mercado-exemplo.com/"}]
        r=preparar_cotacoes_licenciadas(
            cotacoes=lista,licencas_verificadas=LICENCAS,gerado_em=NOW)
        self.assertEqual(r["status"],"BLOQUEADO")

    def test_liberacao_nao_reclassifica_cotacao_vencida(self):
        item={**COTACOES[0],
              "referencia_em":"2026-10-01T20:00:00+00:00",
              "coletado_em":"2026-10-02T12:00:00+00:00"}
        r=preparar_cotacoes_licenciadas(
            cotacoes=[item],licencas_verificadas=LICENCAS,gerado_em=NOW)
        self.assertEqual(r["status"],"BLOQUEADO")

    def test_coleta_antes_cotacao_rejeitada(self):
        item={**COTACOES[0],"coletado_em":"2026-10-19T18:00:00+00:00"}
        r=preparar_cotacoes_licenciadas(
            cotacoes=[item],licencas_verificadas=LICENCAS,gerado_em=NOW)
        self.assertEqual(r["status"],"BLOQUEADO")

    def test_duplicatas_nao_contabilizadas_duas_vezes(self):
        r=preparar_cotacoes_licenciadas(
            cotacoes=[COTACOES[0],dict(COTACOES[0])],
            licencas_verificadas=LICENCAS,gerado_em=NOW)
        self.assertEqual(r["status"],"BLOQUEADO")
        self.assertEqual(r["indicadores"],[])

    def test_sem_sha_ou_sem_documento_rejeita(self):
        for invalid in ("",None,"z"*64):
            with self.subTest(invalid=invalid):
                item={**COTACOES[0],"documento_sha256":invalid}
                r=preparar_cotacoes_licenciadas(
                    cotacoes=[item],licencas_verificadas=LICENCAS,gerado_em=NOW)
                self.assertEqual(r["status"],"BLOQUEADO")

    def test_cli_aceita_licencas_controladas_em_arquivo_separado(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/"entrada.json").write_text(json.dumps({
                "fontes":FONTES,
                "noticias":[],
                "indicadores":[CAMBIO],
                "cotacoes_licenciadas":COTACOES,
            }),encoding="utf8")
            (p/"licencas.json").write_text(json.dumps(LICENCAS),encoding="utf8")
            (p/"scope.json").write_text('{"culturas":[],"portos":[]}',encoding="utf8")
            result=executar([
                "--entrada",str(p/"entrada.json"),
                "--contratos",str(p/"scope.json"),
                "--licencas-mercados",str(p/"licencas.json"),
                "--gerado-em",NOW,"--saida",str(p/"briefing.txt"),
            ])
            self.assertEqual(result["status"],"ENSAIO_OFFLINE_VALIDADO")
            self.assertIn("NOV26",(p/"briefing.txt").read_text())

    def test_cli_sem_licencas_nao_cria_arquivo(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/"entrada.json").write_text(json.dumps({
                "fontes":FONTES,"indicadores":[CAMBIO],
                "cotacoes_licenciadas":COTACOES,
            }),encoding="utf8")
            (p/"scope.json").write_text('{"culturas":[],"portos":[]}',encoding="utf8")
            result=executar([
                "--entrada",str(p/"entrada.json"),
                "--contratos",str(p/"scope.json"),
                "--gerado-em",NOW,"--saida",str(p/"briefing.txt"),
            ])
            self.assertEqual(result["status"],"BLOQUEADO_HISTORICO_INCOMPLETO")
            self.assertFalse((p/"briefing.txt").exists())


class TestMercadosHermes(unittest.IsolatedAsyncioTestCase):
    async def test_preview_em_escopo_readonly_operador_aprova_direitos(self):
        a=NivonProjectAdapter(
            autorizador=lambda _:True,fontes=FONTES,
            licencas_mercado=LICENCAS,
        )
        v=await a.query("briefing.preview",{
            "gerado_em":NOW,
            "indicadores":[CAMBIO],
            "cotacoes_licenciadas":COTACOES,
        })
        self.assertEqual(v["status"],"PREVIEW_AUDITADO_NAO_PUBLICADO")
        self.assertFalse(v["envio"])
        self.assertIn("Soja Paranaguá",v["texto"])

    async def test_agente_nao_pode_ter_proprias_licencas_injetadas(self):
        a=NivonProjectAdapter(autorizador=lambda _:True,fontes=FONTES)
        with self.assertRaises(ValueError):
            await a.query("briefing.preview",{
                "gerado_em":NOW,"indicadores":[CAMBIO],
                "cotacoes_licenciadas":COTACOES,"licencas_mercado":LICENCAS,
            })
        x=await a.query("briefing.preview",{
            "gerado_em":NOW,"indicadores":[CAMBIO],
            "cotacoes_licenciadas":COTACOES,
        })
        self.assertEqual(x["status"],"BLOQUEADO_HISTORICOS")


if __name__=="__main__":
    unittest.main()
