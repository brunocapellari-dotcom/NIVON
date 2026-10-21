import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from nivon.conab_armazens import (LayoutArmazens, ErroArmazens,
    agregar_capacidade_local, inspecionar_cabecalho_local)

LAYOUT = LayoutArmazens(";", "utf-8-sig", "ID_TESTE", "UF", "MUNICIPIO",
                        "CAPACIDADE_T", "t", ",", ".")
IBGE = [{"codigo_ibge":"5105259","nome":"Lucas do Rio Verde","uf":"MT"},
        {"codigo_ibge":"5107925","nome":"Sorriso","uf":"MT"}]


class TestConabArmazens(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.arq=Path(t.name)/"armazens_sinteticos.txt"

    def linha(self, **valores):
        d={"ID_TESTE":"registro-ficticio-1","UF":"MT","MUNICIPIO":"Lucas do Rio Verde",
           "CAPACIDADE_T":"12.500,50","CNPJ_EXEMPLO":"DADO-PRIVADO-SINTETICO"}
        d.update(valores)
        return ";".join(d[x] for x in ("ID_TESTE","UF","MUNICIPIO","CAPACIDADE_T","CNPJ_EXEMPLO"))

    def escrever(self, *linhas):
        self.arq.write_text(
            "ID_TESTE;UF;MUNICIPIO;CAPACIDADE_T;CNPJ_EXEMPLO\n"+"\n".join(linhas)+"\n",
            encoding="utf-8")

    def analisar(self,**kw):
        return agregar_capacidade_local(self.arq,LAYOUT,coletado_em="2026-10-19T12:00:00-04:00",**kw)

    def test_total_municipal_e_sem_dados_pessoais(self):
        self.escrever(self.linha(),self.linha(ID_TESTE="registro-ficticio-2",CAPACIDADE_T="500,00"))
        r=self.analisar(municipios_ibge=IBGE)
        self.assertEqual(r["linhas_validas"],2)
        self.assertEqual(r["agregados"][0]["codigo_ibge"],"5105259")
        self.assertEqual(r["agregados"][0]["capacidade_estatica_t"],13000.5)
        self.assertEqual(r["agregados"][0]["armazens_distintos"],2)
        j=json.dumps(r)
        self.assertNotIn("DADO-PRIVADO-SINTETICO",j)
        self.assertNotIn("registro-ficticio",j)
        self.assertIn("NAO_ESTOQUE",j)

    def test_municipios_separados(self):
        self.escrever(self.linha(), self.linha(ID_TESTE="2",MUNICIPIO="Sorriso",CAPACIDADE_T="50,00"))
        self.assertEqual(self.analisar()["municipios"],2)

    def test_sem_ibge_codigo_fica_nulo(self):
        self.escrever(self.linha())
        self.assertIsNone(self.analisar()["agregados"][0]["codigo_ibge"])

    def test_ibge_desconhecido_nao_vira_id(self):
        self.escrever(self.linha(MUNICIPIO="Cidade Ficticia"))
        with self.assertRaises(ErroArmazens): self.analisar(municipios_ibge=IBGE)

    def test_nao_soma_duas_vezes_mesma_unidade(self):
        self.escrever(self.linha(),self.linha())
        with self.assertRaises(ErroArmazens): self.analisar()

    def test_layout_nao_comprovado_falha(self):
        self.escrever(self.linha())
        with self.assertRaises(ErroArmazens):
            agregar_capacidade_local(self.arq,replace(LAYOUT,coluna_capacidade="CAPACIDADE_DESCONHECIDA"),
                                     coletado_em="2026-10-19T12:00:00Z")

    def test_local_sem_links_ou_download(self):
        self.escrever(self.linha())
        link=self.arq.parent/"atalho.txt"
        link.symlink_to(self.arq)
        with self.assertRaises(ErroArmazens):inspecionar_cabecalho_local(link)
        with self.assertRaises(ErroArmazens):
            agregar_capacidade_local(link,LAYOUT,coletado_em="2026-10-19T12:00:00Z")

    def test_sep_decimal_invalidos(self):
        self.escrever(self.linha())
        for lay in (replace(LAYOUT,decimal=",",milhar=","),
                    replace(LAYOUT,unidade_capacidade="m3"),
                    replace(LAYOUT,separador=":")):
            with self.assertRaises(ErroArmazens):
                agregar_capacidade_local(self.arq,lay,coletado_em="2026-10-19T12:00:00Z")

    def test_decimal_malformado_e_nulo_bloqueados(self):
        for v in ("1,000.50","","-10","1.00.000,00","0"):
            self.escrever(self.linha(CAPACIDADE_T=v))
            with self.assertRaises(ErroArmazens):self.analisar()

    def test_unidade_kg_converte_para_tonelada(self):
        self.escrever(self.linha(CAPACIDADE_T="2500,00"))
        r=agregar_capacidade_local(self.arq,replace(LAYOUT,unidade_capacidade="kg"),
                                  coletado_em="2026-10-19T12:00:00Z")
        self.assertEqual(r["capacidade_total_t"],2.5)

    def test_quatro_datas_sem_inventar(self):
        self.escrever(self.linha())
        r=self.analisar()
        self.assertIsNone(r["publicacao"])
        self.assertIsNone(r["referencia"])
        self.assertEqual(r["coleta"],"2026-10-19T16:00:00+00:00")
        with self.assertRaises(ErroArmazens):
            self.analisar(publicacao="2026-10-20")

    def test_codigos_oficiais_divergentes(self):
        self.escrever(self.linha(CODIGO_IBGE="5107925"))
        # coluna não existe: schema falha fechado em vez de inferir alias
        with self.assertRaises(ErroArmazens):
            agregar_capacidade_local(self.arq,replace(LAYOUT,coluna_codigo_ibge="CODIGO_IBGE"),
                                     coletado_em="2026-10-19T12:00:00Z",municipios_ibge=IBGE)

    def test_inspecao_so_metadados(self):
        self.escrever(self.linha())
        resultado=inspecionar_cabecalho_local(self.arq)
        self.assertEqual(resultado["colunas_por_separador"]["ponto_e_virgula"],5)
        self.assertTrue(resultado["colunas_nao_expostas_por_privacidade"])
        self.assertNotIn("DADO-PRIVADO",json.dumps(resultado))
        self.assertEqual(len(resultado["sha256_amostra"]),64)
