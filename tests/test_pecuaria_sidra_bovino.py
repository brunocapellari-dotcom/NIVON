import unittest
from nivon.motores import DadoInvalido
from nivon.cadeias_adicionais import (
    TABELAS_SIDRA, normalizar_abate_sidra_offline, analisar_cadeia,
)

SHA = "c"*64
CONTRATO = dict(
    fonte_id="IBGE", status_fonte="APROVADA",
    operacoes_autorizadas={"LEITURA","ARMAZENAMENTO"},
    mapeamento={"uf":"UF","competencia":"PERIODO","indicador":"IND",
                "valor":"V","unidade":"UNID"},
    calendario="TRIMESTRE", classificacao="INFORMADO",
    referencia="2025-T3", publicacao="2025-12-10T10:00:00-03:00",
    coleta="2025-12-11T10:00:00-03:00", origem_sha256=SHA,
)
DADOS=[
    {"UF":"MT","PERIODO":"2025-T3","IND":"ABATE_CABECAS","V":1000,"UNID":"CABECAS"},
    {"UF":"MT","PERIODO":"2025-T3","IND":"PESO_CARCACAS_KG","V":250000,"UNID":"KG"},
]

class TestPecuariaSidraBovino(unittest.TestCase):
    def test_sidra_1092_bovino_peso_medio_carcaca(self):
        self.assertEqual(TABELAS_SIDRA["BOVINO"],"1092")
        obs=normalizar_abate_sidra_offline(DADOS,produto="BOVINO",tabela_sidra="1092",**CONTRATO)
        r=analisar_cadeia(obs)
        self.assertEqual(r["derivados"]["peso_medio_carcaca_kg_cabeca"],250)
        self.assertFalse(r["homologado"])

    def test_sidra_1093_nao_pode_substituir_1092(self):
        with self.assertRaises(DadoInvalido):
            normalizar_abate_sidra_offline(DADOS,produto="BOVINO",tabela_sidra="1093",**CONTRATO)

    def test_bovino_nao_recebe_indicador_suino(self):
        x=[dict(DADOS[0],IND="REBANHO_SUINO_CABECAS")]
        with self.assertRaises(DadoInvalido):
            normalizar_abate_sidra_offline(x,produto="BOVINO",tabela_sidra="1092",**CONTRATO)

    def test_bovino_nao_usa_tonelada_sem_conversao_explicita(self):
        x=[dict(DADOS[1],UNID="T")]
        with self.assertRaises(DadoInvalido):
            normalizar_abate_sidra_offline(x,produto="BOVINO",tabela_sidra="1092",**CONTRATO)

    def test_contagem_ausente_nao_e_zero(self):
        x=[dict(DADOS[0],V=None)]
        with self.assertRaises(DadoInvalido):
            normalizar_abate_sidra_offline(x,produto="BOVINO",tabela_sidra="1092",**CONTRATO)

if __name__=="__main__":
    unittest.main()
