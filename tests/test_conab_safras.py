"""Testes offline: séries CONAB não são preços físicos nem origem IBGE."""
import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from nivon.conab_safras import (
    DadosConabNaoHomologados,parametros,numero_nao_negativo,
    checar_meta,validar_linhas,
)


def safra(**kwargs):
    return dict({
        "fonte":"conab","produto":"soja","safra":"2026/27","uf":"MT",
        "area_plantada":12940.2,"area_colhida":None,
        "produtividade":3540.0,"producao":45808.5,
        "levantamento":1,"data_publicacao":"2026-10-15",
    },**kwargs)


class TestConabSafra(unittest.TestCase):
    def setUp(self):
        self.kw={"produto":"soja","safra":"2026/27","uf":"MT",
                 "levantamento":1,
                 "coletado_em":datetime(2026,10,21,tzinfo=timezone.utc)}

    def test_validacao_sem_imputar_area_colhida(self):
        result=validar_linhas([safra()],**self.kw)
        self.assertEqual(result["quantidade_validas"],1)
        row=result["validas"][0]
        self.assertEqual(row["area_colhida_mil_ha"],None)
        self.assertEqual(row["area_plantada_mil_ha"],"12940.2")
        self.assertEqual(row["natureza"],"PROJETADO")
        self.assertIsNone(row["data_referencia"])
        self.assertEqual(row["data_publicacao"],"2026-10-15")
        self.assertEqual(row["competencia"],"2026/27")

    def test_nao_confunde_levantamento_ou_produto(self):
        for r in (safra(levantamento=2),safra(produto="milho"),
                  safra(uf="PR"),safra(safra="2025/26")):
            with self.subTest(row=r):
                out=validar_linhas([r],**self.kw)
                self.assertEqual(out["quantidade_validas"],0)

    def test_nunca_inventa_data_de_cotacao_diaria(self):
        row=validar_linhas([safra()],**self.kw)["validas"][0]
        self.assertIsNone(row["data_referencia"])
        self.assertNotEqual(row["data_publicacao"],row["competencia"])

    def test_nao_aceita_fallback_ibge(self):
        for meta in (
            SimpleNamespace(source="ibge",selected_source="ibge"),
            SimpleNamespace(source="conab",selected_source="ibge"),
            SimpleNamespace(source="conab",data_sources=["conab","ibge"]),
            None,
        ):
            with self.subTest(meta=meta),self.assertRaises(DadosConabNaoHomologados):
                checar_meta(meta)

    def test_aceita_meta_conab(self):
        res=checar_meta(SimpleNamespace(source="conab",data_sources=["conab"],
                                        source_details={"publicacao":{"levantamento":1}},
                                        schema_version="2.0"))
        self.assertEqual(res["fonte"],"conab")

    def test_ausencia_nao_e_zero(self):
        row=safra(area_plantada=None)
        out=validar_linhas([row],**self.kw)
        self.assertIsNone(out["validas"][0]["area_plantada_mil_ha"])
        self.assertEqual(numero_nao_negativo(0,"producao"),"0")
        nan=validar_linhas([safra(area_colhida=float("nan"),
                                  area_plantada=float("nan"))],**self.kw)
        self.assertEqual(nan["quantidade_validas"],1)
        self.assertIsNone(nan["validas"][0]["area_plantada_mil_ha"])
        self.assertIsNone(nan["validas"][0]["area_colhida_mil_ha"])

    def test_rejeita_negativo_nan_inf_e_booleano(self):
        for val in (-1,"NaN","Infinity",float("inf"),True,"erro"):
            with self.subTest(val=val),self.assertRaises(DadosConabNaoHomologados):
                numero_nao_negativo(val,"producao")

    def test_nao_aceita_area_colhida_imputada(self):
        result=validar_linhas([safra(area_colhida=100.1)],**self.kw)
        self.assertEqual(result["quantidade_validas"],0)

    def test_data_de_publicacao_indisponivel_requer_rota_especifica(self):
        result=validar_linhas([safra(data_publicacao=None)],**self.kw)
        self.assertEqual(result["quantidade_validas"],0)

    def test_parametros_estritos_para_evitar_downloads_fora_do_piloto(self):
        for vals in (
            ("cafe","2026/27","MT",1),
            ("soja","2026/28","MT",1),
            ("soja","2026/27","BR",1),
            ("soja","2026/27","MT",13),
            ("soja","2026/27","MT",True),
        ):
            with self.subTest(vals=vals),self.assertRaises(ValueError):
                parametros(*vals)

    def test_sem_linhas_gera_falha_explicita(self):
        with self.assertRaises(DadosConabNaoHomologados):
            validar_linhas([],**self.kw)

if __name__=="__main__":
    unittest.main()
