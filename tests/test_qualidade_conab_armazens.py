import copy
import hashlib
import unittest
from nivon.qualidade_conab_armazens import ErroQualidadeArmazens, verificar_consistencia_armazens

def dados():
    return {
      "dataset_id":"CONAB_ARMAZENS_CAPACIDADE","fonte_id":"CONAB",
      "sha256_original":hashlib.sha256(b"sintetico").hexdigest(),
      "bytes":900,"linhas_validas":3,"municipios":2,
      "agregados":[
        {"uf":"MT","municipio_normalizado":"LUCAS DO RIO VERDE",
         "codigo_ibge":"5105259","armazens_distintos":2,
         "capacidade_estatica_t":150.5,"unidade":"t",
         "natureza":"CAPACIDADE_CADASTRADA_NAO_ESTOQUE"},
        {"uf":"MT","municipio_normalizado":"SORRISO",
         "codigo_ibge":"5107925","armazens_distintos":1,
         "capacidade_estatica_t":200.0,"unidade":"t",
         "natureza":"CAPACIDADE_CADASTRADA_NAO_ESTOQUE"},
      ],"capacidade_total_t":350.5,"coleta":"2026-10-19T16:00:00+00:00",
      "referencia":None,"publicacao":None,
      "status":"AGREGACAO_LOCAL_SEM_HOMOLOGACAO_DE_LAYOUT_DIREITOS_OU_PUBLICACAO",
      "alerta":"Sem estoque disponível",
    }

class TestQualidadeConab(unittest.TestCase):
    def test_agregado_consistente_nao_homologa_publicacao(self):
        r=verificar_consistencia_armazens(dados(),exigir_ibge=True)
        self.assertEqual((r["municipios"],r["armazens"],r["total_t"]),(2,3,350.5))
        self.assertFalse(r["liberado_para_publicacao"])
        self.assertFalse(r["referencia_oficial_homologada"])
    def test_total_de_referencia_exige_correspondencia(self):
        self.assertTrue(verificar_consistencia_armazens(dados(),
                  total_referencia_informado_t=350.5)["total_de_referencia_informado_confere"])
        with self.assertRaises(ErroQualidadeArmazens):
            verificar_consistencia_armazens(dados(),total_referencia_informado_t=400)
    def test_linhas_repetidas_ou_perdidas_nao_passam(self):
        d=dados()
        d["linhas_validas"]=4
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
    def test_soma_municipal_divergente_nao_passam(self):
        d=dados()
        d["capacidade_total_t"]=351.5
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
    def test_municipio_duplicado_nao_passa(self):
        d=dados()
        d["agregados"][1]["municipio_normalizado"]="LUCAS DO RIO VERDE"
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
    def test_codigo_ibge_duplicado_ou_nao_resolvido(self):
        d=dados()
        d["agregados"][1]["codigo_ibge"]="5105259"
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
        d=dados()
        d["agregados"][1]["codigo_ibge"]=None
        r=verificar_consistencia_armazens(d)
        self.assertEqual(r["codigo_ibge_sem_resolucao"],1)
        with self.assertRaises(ErroQualidadeArmazens):
            verificar_consistencia_armazens(d,exigir_ibge=True)
    def test_valor_negativo_nan_bool_rejeitados(self):
        for valor in (-1,float("nan"),True):
            d=dados()
            d["agregados"][0]["capacidade_estatica_t"]=valor
            with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
    def test_pii_ou_campo_novo_bloqueado(self):
        d=dados()
        d["agregados"][0]["cnpj"] = "FICTICIO_PRIVADO"
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
        d=dados()
        d["empresa"] = "FICTICIO_PRIVADO"
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
    def test_unidade_e_natureza_nao_podem_mudar(self):
        for campo,val in (("unidade","kg"),("natureza","ESTOQUE")):
            d=dados()
            d["agregados"][0][campo]=val
            with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
    def test_limite_aleatorio_nao_passa(self):
        with self.assertRaises(ErroQualidadeArmazens):
            verificar_consistencia_armazens(dados(),tolerancia_t=100)
    def test_capacidade_e_hash_proveniencia(self):
        d=dados()
        d["sha256_original"]="a"
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
        d=dados()
        d["bytes"]=120_000_001
        with self.assertRaises(ErroQualidadeArmazens):verificar_consistencia_armazens(d)
