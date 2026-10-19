import unittest
from dataclasses import replace
from nivon.cadeias_adicionais import (
    UNIDADES, TABELAS_SIDRA, ObservacaoCadeia,
    normalizar_linhas_offline, normalizar_abate_sidra_offline, analisar_cadeia,
)
from nivon.motores import DadoInvalido

SHA="f"*64
COL={"uf":"UF","competencia":"PERIODO","indicador":"IND","valor":"V","unidade":"UNID"}
BASE=dict(fonte_id="IBGE",status_fonte="APROVADA",
          operacoes_autorizadas={"LEITURA","ARMAZENAMENTO"},mapeamento=COL,
          calendario="TRIMESTRE",classificacao="INFORMADO",
          referencia="2026-T1",publicacao="2026-04-01T10:00:00-03:00",
          coleta="2026-04-02T10:00:00-03:00",origem_sha256=SHA)


def rows(produto, valores,periodo="2026-T1"):
    return [{"UF":"MT","PERIODO":periodo,"IND":k,"V":v,
             "UNID":UNIDADES[produto][k]} for k,v in valores]


class TestCadeiasAdicionais(unittest.TestCase):
    def test_sidra_frango_suino_separados(self):
        for p,t in TABELAS_SIDRA.items():
            x=normalizar_abate_sidra_offline(
                rows(p,[("ABATE_CABECAS",100),("PESO_CARCACAS_KG",230)]),
                produto=p,tabela_sidra=t,**BASE)
            self.assertEqual(analisar_cadeia(x)["derivados"]["peso_medio_carcaca_kg_cabeca"],2.3)
            self.assertFalse(analisar_cadeia(x)["homologado"])

    def test_sidra_tabela_trocada_bloqueada(self):
        with self.assertRaises(DadoInvalido):
            normalizar_abate_sidra_offline(
                rows("FRANGO",[("ABATE_CABECAS",100)]),
                produto="FRANGO",tabela_sidra="1093",**BASE)

    def test_sidra_calendario_errado_bloqueado(self):
        with self.assertRaises(DadoInvalido):
            normalizar_abate_sidra_offline(
                rows("SUINO",[("ABATE_CABECAS",100)]),
                produto="SUINO",tabela_sidra="1093",
                **dict(BASE,calendario="ANO_CIVIL"))

    def test_sem_direito_de_coleta_ou_armazenamento(self):
        dados=rows("FRANGO",[("ABATE_CABECAS",100)])
        for cfg in (dict(BASE,status_fonte="PENDENTE"),
                    dict(BASE,operacoes_autorizadas={"LEITURA"})):
            with self.assertRaises(PermissionError):
                normalizar_linhas_offline(dados,produto="FRANGO",**cfg)

    def test_nulo_valor_string_e_nan_bloqueados(self):
        for invalido in (None,"100",float("nan"),float("inf"),True,-10):
            dados=rows("FRANGO",[("ABATE_CABECAS",invalido)])
            with self.assertRaises(DadoInvalido):
                normalizar_linhas_offline(dados,produto="FRANGO",**BASE)

    def test_unidade_carcaca_nao_pode_ser_tonelada(self):
        dados=rows("SUINO",[("PESO_CARCACAS_KG",12000)])
        dados[0]["UNID"]="T"
        with self.assertRaises(DadoInvalido):
            normalizar_linhas_offline(dados,produto="SUINO",**BASE)

    def test_frango_nao_pode_receber_rebanho_suino(self):
        dados=rows("SUINO",[("REBANHO_SUINO_CABECAS",100)])
        with self.assertRaises(DadoInvalido):
            normalizar_linhas_offline(dados,produto="FRANGO",**BASE)

    def test_duplicata_e_linhas_vazias_bloqueadas(self):
        dados=rows("FRANGO",[("ABATE_CABECAS",100)])
        with self.assertRaises(DadoInvalido):
            normalizar_linhas_offline(dados*2,produto="FRANGO",**BASE)
        with self.assertRaises(DadoInvalido):
            normalizar_linhas_offline([],produto="FRANGO",**BASE)

    def test_bloqueia_data_publicacao_futura(self):
        with self.assertRaises(DadoInvalido):
            normalizar_linhas_offline(rows("FRANGO",[("ABATE_CABECAS",100)]),
                produto="FRANGO",**dict(BASE,publicacao="2026-04-04T00:00:00Z"))

    def test_vintages_mistos_bloqueados(self):
        x=normalizar_linhas_offline(
            rows("FRANGO",[("ABATE_CABECAS",100),("PESO_CARCACAS_KG",230)]),
            produto="FRANGO",**BASE)
        with self.assertRaises(DadoInvalido):
            analisar_cadeia([x[0],replace(x[1],origem_sha256="a"*64)])

    def test_gergelim_produtividade_conciliada(self):
        v=[("AREA_HA",500),("PRODUCAO_GERGELIM_T",350),("PRODUTIVIDADE_KG_HA",700)]
        dados=normalizar_linhas_offline(rows("GERGELIM",v,"2025/2026"),
               produto="GERGELIM",**dict(BASE,calendario="SAFRA"))
        z=analisar_cadeia(dados)["derivados"]
        self.assertEqual(z["produtividade_calculada_kg_ha"],700)
        self.assertTrue(z["produtividade_conciliada_2pct"])

    def test_gergelim_fob_nao_preco_fazenda(self):
        v=[("EXPORTACAO_GERGELIM_T",100),("EXPORTACAO_FOB_USD",100000)]
        dados=normalizar_linhas_offline(rows("GERGELIM",v,"2026-04"),
               produto="GERGELIM",**dict(BASE,calendario="MES"))
        z=analisar_cadeia(dados)["derivados"]
        self.assertEqual(z["valor_fob_medio_usd_t"],1000)
        self.assertTrue(z["preco_fob_nao_preco_fazenda"])

    def test_cana_mix_unidades_separadas(self):
        v=[("PRODUCAO_CANA_T",1000),("MOAGEM_CANA_T",900),
           ("ACUCAR_T",80),("ETANOL_CANA_ANIDRO_L",60000)]
        dados=normalizar_linhas_offline(rows("CANA",v,"2025/2026"),
               produto="CANA",**dict(BASE,calendario="SAFRA"))
        z=analisar_cadeia(dados)["derivados"]
        self.assertEqual(z["moagem_producao_indicativa"],.9)
        self.assertNotIn("balanco_fisico",z)


if __name__=="__main__":
    unittest.main()
