import json
import unittest
from nivon.sidra_pam import planejar_pam_1612,normalizar_pam_1612,ErroSIDRAPAM
def plano():
    return planejar_pam_1612(municipio_ibge="5107925",ano=2025,
                             codigo_produto_c81="2692",codigo_variavel="109")
def retorno(valor):
    cab={"D1C":"Município (Código)","D2C":"Ano (Código)",
         "D3C":"Variável (Código)","D4C":"Produto (Código)",
         "V":"Valor","MN":"Unidade de Medida"}
    dado={"D1C":"5107925","D2C":"2025","D3C":"109","D4C":"2692",
          "V":valor,"MN":"Toneladas"}
    return json.dumps([cab,dado]).encode()
def tratar(payload,**kwargs):
    return normalizar_pam_1612(payload,plano=kwargs.pop("plano",plano()),
                               coletado_em="2026-10-19T12:00:00Z")

class TestSIDRAPAM(unittest.TestCase):
    def test_gera_url_tabela_municipal_oficial(self):
        p=plano()
        self.assertEqual(p["url"],"https://apisidra.ibge.gov.br/values/t/1612/n6/5107925/v/109/p/2025/c81/2692/h/y/f/a")
        self.assertIn("PAM_ANUAL",p["natureza"])
    def test_unidade_original_e_datas_sem_inventar(self):
        r=tratar(retorno("1500"))
        self.assertEqual(r["observacoes"][0]["valor"],1500)
        self.assertEqual(r["observacoes"][0]["unidade_original"],"Toneladas")
        self.assertIsNone(r["publicacao"])
    def test_zero_absoluto_diferente_de_arredondado(self):
        a=tratar(retorno("-"))["observacoes"][0]
        b=tratar(retorno("0"))["observacoes"][0]
        self.assertEqual(a["estado_valor"],"ZERO_ABSOLUTO")
        self.assertEqual(b["estado_valor"],"ZERO_ARREDONDADO")
    def test_marcadores_sigilo_e_ausencia_sao_nulos(self):
        for marker in ("X","..","..."):
            x=tratar(retorno(marker))["observacoes"][0]
            self.assertIsNone(x["valor"])
    def test_municipio_alterado_rejeitado(self):
        raw=retorno("1").replace(b"5107925",b"5105259")
        with self.assertRaises(ErroSIDRAPAM):tratar(raw)
    def test_nao_inferir_produto_sem_codigo(self):
        with self.assertRaises(ErroSIDRAPAM):
            planejar_pam_1612(municipio_ibge="5107925",ano=2025,
                              codigo_produto_c81="GERGELIM",codigo_variavel="109")
    def test_sem_planos_invalidos(self):
        for m in ("abc","51079","https://evil.example"):
            with self.assertRaises(ErroSIDRAPAM):
                planejar_pam_1612(municipio_ibge=m,ano=2025,
                                  codigo_produto_c81="2692",codigo_variavel="109")
    def test_ano_invalidado(self):
        with self.assertRaises(ErroSIDRAPAM):
            planejar_pam_1612(municipio_ibge="5107925",ano=True,
                              codigo_produto_c81="2692",codigo_variavel="109")
    def test_duplicidade_rejeitada(self):
        payload=json.loads(retorno("1"))
        payload.append(dict(payload[1]))
        with self.assertRaises(ErroSIDRAPAM):tratar(json.dumps(payload).encode())
    def test_plano_alterado_rejeitado(self):
        p=plano()
        p["url"]="https://evil.example"
        with self.assertRaises(ErroSIDRAPAM):tratar(retorno("1"),plano=p)
    def test_valor_negativo_nao_permitido(self):
        with self.assertRaises(ErroSIDRAPAM):tratar(retorno("-1"))
    def test_resposta_vazia_nao_e_zero(self):
        with self.assertRaises(ErroSIDRAPAM):tratar(b"[]")
