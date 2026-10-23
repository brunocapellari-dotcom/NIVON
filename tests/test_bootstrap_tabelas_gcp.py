"""Duas tabelas GCP: bootstrap sem duplicação, modo consulta, gate e retry."""
import io
import json
import unittest
from contextlib import redirect_stdout

from nivon.bootstrap_tabelas_gcp import (
    ativar_destinos, main, ErroAtivacaoGCP,
)
from nivon.carga_bigquery_fontes import ErroCargaBigQuery


CFG={"projeto":"nivon-data","dataset":"nivon_raw","bucket":"nivon-data-raw-2026"}


class TestBootstrapNivonGCP(unittest.TestCase):
    def test_ler_ambas_ausentes_sem_efeito(self):
        passos=[]
        def canonical(**kwargs):
            passos.append(("canonico",kwargs["criar_tabela"]))
            raise ErroCargaBigQuery("tabela BigQuery ausente; bootstrap explicito necessario")
        def staging(**kwargs):
            passos.append(("agro",kwargs["aplicar"]))
            return {"estado":"TABELA_AUSENTE","criou_tabela":False}
        out=ativar_destinos(**CFG,canonical=canonical,staging=staging)
        self.assertEqual(out["status"],"FALTAM_TABELAS_BIGQUERY")
        self.assertEqual(out["canonico"]["estado"],"TABELA_AUSENTE")
        self.assertEqual(out["agro_quarentena"]["estado"],"TABELA_AUSENTE")
        self.assertFalse(out["go_live"])
        self.assertFalse(out["carregou_dados"])
        self.assertEqual(passos,[("canonico",False),("agro",False)])

    def test_aplicar_gated_antes_de_qualquer_write(self):
        chamadas=[]
        def block(**kwargs):
            chamadas.append("CHAMADO")
            raise AssertionError("não deveria consultar nuvem")
        with self.assertRaises(PermissionError):
            ativar_destinos(**CFG,aplicar=True,autorizado=False,
                            canonical=block,staging=block)
        self.assertEqual(chamadas,[])

    def test_criar_duas_tabelas_distintas_uma_unica_vez(self):
        tabelas=set()
        passos=[]
        def canonical(**kwargs):
            self.assertEqual(kwargs["projeto"],"nivon-data")
            assert kwargs["criar_tabela"] is True
            novo="nivon_observacoes" not in tabelas
            tabelas.add("nivon_observacoes")
            passos.append("canonical")
            return {"bucket_existe":True,"tabela_validada":True,
                    "tabela_criada":novo}
        def staging(**kwargs):
            assert kwargs["aplicar"] and kwargs["aprovado"] and kwargs["verificar"]
            novo="agro_publicacoes_staging" not in tabelas
            tabelas.add("agro_publicacoes_staging")
            passos.append("stage")
            return {"estado":"SCHEMA_VALIDADO","criou_tabela":novo}
        kw=dict(CFG,aplicar=True,autorizado=True,canonical=canonical,staging=staging)
        primeira=ativar_destinos(**kw)
        self.assertEqual(primeira["status"],"DESTINOS_BIGQUERY_VERIFICADOS")
        self.assertTrue(primeira["canonico"]["criada_neste_lote"])
        self.assertTrue(primeira["agro_quarentena"]["criada_neste_lote"])
        self.assertFalse(primeira["agro_quarentena"]["publicavel_como_dado_canonico"])
        self.assertEqual(tabelas,{"nivon_observacoes","agro_publicacoes_staging"})
        segunda=ativar_destinos(**kw)
        self.assertFalse(segunda["canonico"]["criada_neste_lote"])
        self.assertFalse(segunda["agro_quarentena"]["criada_neste_lote"])
        self.assertEqual(passos,["canonical","stage","canonical","stage"])

    def test_erros_de_schema_nao_sao_falsamente_sucesso(self):
        def invalid(**kw):
            raise ErroCargaBigQuery("schema BigQuery divergente")
        with self.assertRaisesRegex(ErroCargaBigQuery,"schema"):
            ativar_destinos(**CFG,canonical=invalid,
                staging=lambda **kw: {"estado":"SCHEMA_VALIDADO"})
        with self.assertRaises(ErroAtivacaoGCP):
            ativar_destinos(**CFG,
                canonical=lambda **kw: {"tabela_validada":False},
                staging=lambda **kw: {"estado":"SCHEMA_VALIDADO"})
        with self.assertRaises(ErroAtivacaoGCP):
            ativar_destinos(**CFG,
                canonical=lambda **kw: {"tabela_validada":True},
                staging=lambda **kw: {"estado":"INCONCLUSIVO"})

    def test_retry_apos_primeira_tabela_criada(self):
        criadas={"nivon_observacoes"}
        def canonical(**kw):
            return {"tabela_validada":True,"tabela_criada":False}
        def staging(**kw):
            novo="agro_publicacoes_staging" not in criadas
            criadas.add("agro_publicacoes_staging")
            return {"estado":"SCHEMA_VALIDADO","criou_tabela":novo}
        out=ativar_destinos(**CFG,aplicar=True,autorizado=True,
                            canonical=canonical,staging=staging)
        self.assertTrue(out["tabelas_operacionais_verificadas"])
        self.assertEqual(out["status"],"DESTINOS_BIGQUERY_VERIFICADOS")
        self.assertFalse(out["canonico"]["criada_neste_lote"])
        self.assertTrue(out["agro_quarentena"]["criada_neste_lote"])

    def test_cli_default_nao_acessa_cloud(self):
        output=io.StringIO()
        with redirect_stdout(output):
            result=main([
                "--projeto","nivon-data","--dataset","nivon_raw",
                "--bucket","nivon-data-raw-2026",
            ])
        self.assertEqual(result,0)
        plan=json.loads(output.getvalue())
        self.assertFalse(plan["consultou_cloud"])
        self.assertEqual(plan["destinos"],
                         ["nivon_observacoes","agro_publicacoes_staging"])
        with self.assertRaises(PermissionError):
            main(["--projeto","nivon-data","--dataset","nivon_raw",
                  "--bucket","nivon-data-raw-2026","--aplicar"])


if __name__=="__main__":
    unittest.main()
