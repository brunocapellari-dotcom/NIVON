"""Testes de fluxos rodoviários por polos intermodais (dados sintéticos)."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from nivon.antt_mdfe_volumes import importar
from nivon.inteligencia_corredores import (
    ErroCorredor, consultar_corredores, identificar_polos, salvar_relatorio,
)

def tabela():
    return (
      "competencia;origem;destino;toneladas;NCM;Quantidade MDFe\n"
      "2026-09;Sorriso;Rondonópolis;40,5;1201;2\n"
      "2026-09;Sinop;Itiquira;22,3;1005;1\n"
      "2026-09;Sorriso;Dom Aquino;10;3105;1\n"
      "2026-09;Sorriso;Itaituba;100;1201;5\n"
      "2026-09;Campo Verde;Santos;30;2304;2\n"
      "2026-09;Porto Velho;Itacoatiara;12;2710;1\n"
    ).encode("utf-8")

class CorredoresTeste(unittest.TestCase):
    def criar_banco(self, pasta, *, nivel="MUNICIPIO", recorte="mt_especifico"):
        banco=Path(pasta)/"antt.sqlite"
        importar(banco,tabela(),arquivo="teste.csv",recorte=recorte,nivel=nivel)
        return banco

    def test_catalogo_tipos_e_comissionamento(self):
        r=identificar_polos("Dom Aquino",nivel="MUNICIPIO")
        self.assertEqual(r[0]["id"],"MT_DOM_AQUINO_BR070")
        self.assertEqual(r[0]["situacao"],"COMISSIONAMENTO_INICIADO_2026")
        self.assertFalse(r[0]["terminal_confirmado"])
        self.assertFalse(r[0]["transferencia_modal_confirmada"])
        self.assertEqual(identificar_polos("NOVA RONDONOPOLIS",nivel="MUNICIPIO"),[])
        self.assertEqual(identificar_polos("MT - Itiquira",nivel="MUNICIPIO")[0]["modal_destino"],"FERROVIARIO")

    def test_ranking_fluxos_e_produtos_com_limite(self):
        with tempfile.TemporaryDirectory() as d:
            banco=self.criar_banco(d)
            data=consultar_corredores(banco,recorte="mt_especifico",competencia="2026-09",limite=20)
            self.assertEqual(data["estado"],"RECORTE_IMPORTADO_NAO_HOMOLOGADO")
            self.assertEqual(data["corredores_relevantes"],7)
            self.assertEqual(data["resumo_polos"][0]["polo"]["id"],"PA_MIRITITUBA_HIDRO")
            self.assertEqual(data["resumo_polos"][0]["toneladas_no_recorte"],"100")
            self.assertFalse(data["resumo_polos"][0]["transbordo_confirmado"])
            self.assertEqual(data["resumo_polos"][0]["principais_origens"][0]["origem"],"Sorriso")
            top=data["corredores"][0]
            self.assertEqual(top["polo"]["id"],"PA_MIRITITUBA_HIDRO")
            self.assertEqual(top["toneladas_no_recorte"],"100")
            self.assertEqual(top["produto"],"SOJA_EM_GRAO")
            self.assertEqual(top["polo"]["evidencia_geografica"],"MUNICIPIO_NAO_TERMINAL")
            self.assertFalse(top["polo"]["transferencia_modal_confirmada"])
            santos=[x for x in data["corredores"] if x["polo"]["id"]=="SP_SANTOS_PORTO"]
            self.assertEqual(santos[0]["produto"],"FARELO_SOJA")
            r=consultar_corredores(banco,recorte="mt_especifico",competencia="2026-09",limite=1)
            self.assertTrue(r["truncado"])
            self.assertEqual(len(r["corredores"]),1)

    def test_rgi_nao_confirma_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            banco=self.criar_banco(d,nivel="RGI")
            data=consultar_corredores(banco,recorte="mt_especifico",competencia="2026-09")
            self.assertTrue(data["corredores"])
            self.assertTrue(all(x["polo"]["evidencia_geografica"]=="REGIAO_RGI_NAO_TERMINAL"
                            for x in data["corredores"]))

    def test_versoes_e_recortes_nao_se_misturam(self):
        with tempfile.TemporaryDirectory() as d:
            banco=self.criar_banco(d)
            importar(banco,tabela().replace(b"40,5",b"80,0"),arquivo="revisado.csv",
                     recorte="mt_especifico",nivel="MUNICIPIO")
            importar(banco,tabela(),arquivo="recorte2.csv",
                     recorte="outro_universo",nivel="MUNICIPIO")
            a=consultar_corredores(banco,recorte="mt_especifico",competencia="2026-09")
            b=consultar_corredores(banco,recorte="outro_universo",competencia="2026-09")
            r1=[x for x in a["corredores"] if x["polo"]["id"]=="MT_RONDONOPOLIS_FERRO"][0]
            r2=[x for x in b["corredores"] if x["polo"]["id"]=="MT_RONDONOPOLIS_FERRO"][0]
            self.assertEqual(r1["toneladas_no_recorte"],"80.0")
            self.assertEqual(r2["toneladas_no_recorte"],"40.5")
            self.assertNotEqual(a["sha256_origem"],b["sha256_origem"])

    def test_rejeitar_escopo_e_gerar_json(self):
        with tempfile.TemporaryDirectory() as d:
            banco=self.criar_banco(d)
            with self.assertRaises(ErroCorredor):
                consultar_corredores(banco,recorte="",competencia="2026-09")
            saida=Path(d)/"corredores.json"
            status=salvar_relatorio(banco,recorte="mt_especifico",competencia="2026-09",caminho=saida)
            self.assertEqual(status["estado"],"RECORTE_IMPORTADO_NAO_HOMOLOGADO")
            data=json.loads(saida.read_text())
            self.assertTrue(data["cobertura"]["nao_somar_com_rail_ou_antaq"])
            self.assertEqual(data["corredores"][0]["natureza"],
                             "RODOVIARIO_MDFE_IMPORTADO_NAO_HOMOLOGADO")

if __name__=="__main__":
    unittest.main()
