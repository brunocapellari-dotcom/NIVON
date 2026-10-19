import json
import unittest

from nivon.ibge_municipios import (ENDPOINT, ErroMunicipiosIBGE,
                                  normalizar_municipios_ibge, resolver_municipio)


def mun(codigo, nome, uf, *, antigo=True, novo=True):
    dado = {"id": codigo, "nome": nome}
    if antigo:
        dado["microrregiao"] = {"mesorregiao": {"UF": {"sigla": uf}}}
    if novo:
        dado["regiao-imediata"] = {"regiao-intermediaria": {"UF": {"sigla": uf}}}
    return dado


def analisar(registros, **opcoes):
    return normalizar_municipios_ibge(json.dumps(registros).encode(),
                                     coletado_em="2026-10-19T12:00:00-04:00", **opcoes)


class TestIBGEMunicipios(unittest.TestCase):
    def test_identificadores_e_datas_sem_fabricar_publicacao(self):
        r = analisar([mun(5105259, "Lucas do Rio Verde", "MT")])
        self.assertEqual(r["municipios"][0]["codigo_ibge"], "5105259")
        self.assertEqual(r["coleta"], "2026-10-19T16:00:00+00:00")
        self.assertIsNone(r["publicacao"])
        self.assertEqual(len(r["sha256_original"]), 64)

    def test_ambas_hierarquias_funcionam_independentemente(self):
        r = analisar([mun(5105259,"Lucas do Rio Verde","MT",novo=False),
                     mun(3550308,"São Paulo","SP",antigo=False)])
        self.assertEqual({x["uf"] for x in r["municipios"]}, {"MT", "SP"})

    def test_resolucao_normaliza_acentos_sem_fuzzy(self):
        r = analisar([mun(3550308, "São Paulo", "SP")])
        self.assertEqual(resolver_municipio(r["municipios"], nome="sao paulo", uf="SP")["codigo_ibge"],"3550308")
        with self.assertRaises(ErroMunicipiosIBGE):
            resolver_municipio(r["municipios"], nome="Sao Paulu", uf="SP")

    def test_nomes_iguais_ufs_diferentes_requerem_uf(self):
        r = analisar([mun(5105259,"Vila Teste","MT"),mun(3550308,"Vila Teste","SP")])
        with self.assertRaises(ErroMunicipiosIBGE):
            resolver_municipio(r["municipios"], nome="Vila Teste")
        self.assertEqual(resolver_municipio(r["municipios"],nome="Vila Teste",uf="MT")["uf"],"MT")

    def test_codigo_repetido_rejeitado(self):
        with self.assertRaises(ErroMunicipiosIBGE):
            analisar([mun(5105259,"A","MT"),mun(5105259,"B","MT")])

    def test_mesmo_nome_mesma_uf_rejeitado(self):
        with self.assertRaises(ErroMunicipiosIBGE):
            analisar([mun(5105259,"SaO Paulo","MT"),mun(5109999,"São Paulo","MT")])

    def test_hierarquias_conflitantes_rejeitadas(self):
        d=mun(5105259,"Lucas do Rio Verde","MT")
        d["microrregiao"]["mesorregiao"]["UF"]["sigla"]="SP"
        with self.assertRaises(ErroMunicipiosIBGE): analisar([d])

    def test_api_invalida_ou_rede_nao_e_iniciada(self):
        for url in ("http://servicodados.ibge.gov.br/api/v1/localidades/municipios",
                    "https://example.com/api/v1/localidades/municipios",
                    ENDPOINT+"?token=falso", "https://usuario@servicodados.ibge.gov.br/api/v1/localidades/municipios"):
            with self.assertRaises(ErroMunicipiosIBGE): analisar([mun(5105259,"A","MT")],consulta_url=url)

    def test_fusos_obrigatorios(self):
        with self.assertRaises(ErroMunicipiosIBGE):
            normalizar_municipios_ibge(b"[]",coletado_em="2026-10-19T12:00:00")

    def test_sem_schema_e_sem_municipios_rejeitados(self):
        for x in ([],{},["texto"],[{"id":10,"nome":"X"}], [mun(True,"A","MT")],
                  [mun(5105259,"A","XX")]):
            with self.assertRaises(ErroMunicipiosIBGE): analisar(x)

    def test_json_com_campos_repetidos_rejeitado(self):
        raw = b'[{"id":5105259,"id":5105259}]'
        with self.assertRaises(ErroMunicipiosIBGE):
            normalizar_municipios_ibge(raw,coletado_em="2026-10-19T12:00:00Z")

    def test_payload_grande_nao_aceito(self):
        with self.assertRaises(ErroMunicipiosIBGE):
            normalizar_municipios_ibge(b"x" * 8_000_001,coletado_em="2026-10-19T12:00:00Z")

    def test_sem_inferencia_para_vigencia_historica(self):
        r=analisar([mun(5105259,"Lucas do Rio Verde","MT")])
        self.assertIsNone(r["referencia"])
        self.assertIsNone(r["competencia"])
