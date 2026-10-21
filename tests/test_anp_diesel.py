import json
import unittest
from datetime import date
from nivon.anp_diesel import CAMPOS, ErroANP, resumo_diesel_municipal, semana_calendario

def linha(**alteracoes):
    d={
        "Regiao - Sigla":"CO","Estado - Sigla":"MT","Municipio":"CIDADE SINTETICA",
        "Revenda":"NOME_SINTETICO_QUE_NAO_PODE_SAIR","CNPJ da Revenda":"ID_FICTICIO",
        "Nome da Rua":"ENDERECO_FICTICIO","Numero Rua":"0","Complemento":"",
        "Bairro":"BAIRRO_FICTICIO","Cep":"00000000","Produto":"DIESEL S10",
        "Data da Coleta":"10/09/2026","Valor de Venda":"6,50",
        "Valor de Compra":"","Unidade de Medida":"R$ / litro","Bandeira":"BRANCA",
    }
    d.update(alteracoes)
    return ";".join(d[k] for k in CAMPOS)+"\n"

def fonte(*linhas):
    return (";".join(CAMPOS)+"\n"+"".join(linhas)).encode("utf-8-sig")

class TestANPDiesel(unittest.TestCase):
    def test_media_municipal_simples(self):
        r=resumo_diesel_municipal(fonte(
            linha(**{"Valor de Venda":"6,40"}),
            linha(**{"Valor de Venda":"6,80"})), mes_esperado="2026-09")
        self.assertEqual(r["grupos_municipio_semana"],1)
        self.assertEqual(r["series"][0]["postos_observacoes"],2)
        self.assertEqual(r["series"][0]["preco_medio_revenda_rs_l"],6.6)

    def test_diesel_e_s10_separados(self):
        r=resumo_diesel_municipal(fonte(
            linha(**{"Produto":"DIESEL","Valor de Venda":"6,20"}),
            linha(**{"Produto":"DIESEL S10","Valor de Venda":"6,80"})),mes_esperado="2026-09")
        self.assertEqual({x["produto"] for x in r["series"]},{"DIESEL","DIESEL S10"})

    def test_semana_inferida_nao_oficial(self):
        inicio,fim=semana_calendario(date(2026,9,10))
        self.assertEqual(inicio.weekday(),6)
        self.assertEqual((fim-inicio).days,6)
        r=resumo_diesel_municipal(fonte(linha()),mes_esperado="2026-09")
        self.assertIn("INFERIDA",r["semana_origem"])

    def test_sem_qualquer_identificador_de_posto(self):
        s=json.dumps(resumo_diesel_municipal(fonte(linha()),mes_esperado="2026-09"))
        for proibido in ("NOME_SINTETICO_QUE_NAO_PODE_SAIR","ID_FICTICIO","ENDERECO_FICTICIO"):
            self.assertNotIn(proibido,s)

    def test_gnv_nao_contamina_diesel(self):
        r=resumo_diesel_municipal(fonte(
            linha(**{"Produto":"GNV","Valor de Venda":"4,50"}),linha()),mes_esperado="2026-09")
        self.assertEqual(r["totais"]["linhas_outros_produtos"],1)

    def test_preco_nulo_rejeitado(self):
        with self.assertRaises(ErroANP):
            resumo_diesel_municipal(fonte(linha(**{"Valor de Venda":""})),mes_esperado="2026-09")

    def test_formato_numerico_ingles_rejeitado(self):
        with self.assertRaises(ErroANP):
            resumo_diesel_municipal(fonte(linha(**{"Valor de Venda":"6.80"})),mes_esperado="2026-09")

    def test_data_fora_mes_rejeitada(self):
        with self.assertRaises(ErroANP):
            resumo_diesel_municipal(fonte(linha(**{"Data da Coleta":"31/08/2026"})),mes_esperado="2026-09")

    def test_unidade_diferente_rejeita(self):
        with self.assertRaises(ErroANP):
            resumo_diesel_municipal(fonte(linha(**{"Unidade de Medida":"R$/m3"})),mes_esperado="2026-09")

    def test_schema_incompleto_rejeita(self):
        with self.assertRaises(ErroANP):
            resumo_diesel_municipal(b"Municipio;Produto\nX;DIESEL S10\n",mes_esperado="2026-09")

    def test_sem_diesel_falha(self):
        with self.assertRaises(ErroANP):
            resumo_diesel_municipal(fonte(linha(**{"Produto":"GNV"})),mes_esperado="2026-09")

    def test_uf_diferente_separa_localidade(self):
        r=resumo_diesel_municipal(fonte(
            linha(**{"Estado - Sigla":"MT"}),
            linha(**{"Estado - Sigla":"GO"})),mes_esperado="2026-09")
        self.assertEqual(r["grupos_municipio_semana"],2)

    def test_maximo_e_minimo(self):
        r=resumo_diesel_municipal(fonte(
            linha(**{"Valor de Venda":"6,99"}),
            linha(**{"Valor de Venda":"7,19"})),mes_esperado="2026-09")
        self.assertEqual(r["series"][0]["preco_minimo_revenda_rs_l"],6.99)
        self.assertEqual(r["series"][0]["preco_maximo_revenda_rs_l"],7.19)

if __name__=="__main__":
    unittest.main()
