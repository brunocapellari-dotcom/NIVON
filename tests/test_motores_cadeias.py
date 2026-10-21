import unittest

from nivon.motores import DadoInvalido
from nivon.motores_cadeias import (
    simular_atr_cana, paridade_gergelim, margem_proteina, peso_medio_carcaca,
    intensidade_exportacao_carne, cenario_anual, backtest_anual, classificar_risco,
)


class TestMotoresCadeias(unittest.TestCase):
    def test_atr_nao_soma_litros_e_toneladas(self):
        v=simular_atr_cana(cana_moida_t=1000,atr_kg_t=130,
            fracao_acucar=.6,fracao_etanol=.4,fonte_parametros="hipotese documentada")
        self.assertEqual(v["atr_total_kg"],130000)
        self.assertEqual(v["atr_alocado_acucar_kg"],78000)
        self.assertNotIn("acucar_t",v)

    def test_mix_nao_fecha_rejeitado(self):
        with self.assertRaises(DadoInvalido):
            simular_atr_cana(cana_moida_t=1000,atr_kg_t=130,
                fracao_acucar=.6,fracao_etanol=.6,fonte_parametros="teste")

    def test_gergelim_paridade_nao_preco_produtor(self):
        v=paridade_gergelim(fob_usd_t=1500,cambio_rs_usd=5,
            frete_rs_t=400,porto_rs_t=150,outros_rs_t=100,
            fonte_fob="fixture",fonte_cambio="fixture")
        self.assertEqual(v["paridade_liquida_rs_t"],6850)
        self.assertEqual(v["classificacao"],"CENARIO_PARIDADE_EXPORTACAO")

    def test_paridade_cambio_ausente_bloqueia(self):
        with self.assertRaises(DadoInvalido):
            paridade_gergelim(fob_usd_t=1500,cambio_rs_usd=None,
                frete_rs_t=0,porto_rs_t=0,outros_rs_t=0,
                fonte_fob="fixture",fonte_cambio="fixture")

    def test_margem_frango_e_suino_milho_farelo(self):
        for especie in ("FRANGO","SUINO"):
            x=margem_proteina(especie=especie,preco_vivo_rs_kg=8,
                conversao_racao_kg_kg_ganho=2,fracoes_ingredientes={"MILHO":.65,"FARELO_SOJA":.35},
                precos_ingredientes_rs_t={"MILHO":1000,"FARELO_SOJA":2000},
                outros_custos_rs_kg_ganho=1,fonte_parametros="formulacao hipotetica")
            self.assertAlmostEqual(x["custo_racao_rs_t"],1350)
            self.assertAlmostEqual(x["margem_contribuicao_rs_kg_ganho"],4.3)
            self.assertEqual(x["classificacao"],"SIMULACAO_MARGEM_NAO_OBSERVADA")

    def test_formulacao_incompleta_ou_soma_errada(self):
        args=dict(especie="FRANGO",preco_vivo_rs_kg=8,
                conversao_racao_kg_kg_ganho=2,
                fracoes_ingredientes={"MILHO":.9},precos_ingredientes_rs_t={"MILHO":900},
                outros_custos_rs_kg_ganho=1,fonte_parametros="teste")
        with self.assertRaises(DadoInvalido):
            margem_proteina(**args)
        with self.assertRaises(DadoInvalido):
            margem_proteina(**dict(args,fracoes_ingredientes={"MILHO":1},
                                  precos_ingredientes_rs_t={"FARELO":900}))

    def test_abate_carcaca_com_cabecas_inteiras(self):
        self.assertEqual(peso_medio_carcaca(especie="SUINO",cabecas=100,
            peso_carcacas_kg=9000)["peso_medio_kg_cabeca"],90)
        with self.assertRaises(DadoInvalido):
            peso_medio_carcaca(especie="FRANGO",cabecas=1.5,peso_carcacas_kg=3)

    def test_exportacao_requires_equivalente_carcaca(self):
        with self.assertRaises(DadoInvalido):
            intensidade_exportacao_carne(especie="FRANGO",
                exportacao_carcaca_equiv_t=100,producao_carcaca_equiv_t=400,
                fonte_conversao="",calendario="ANO_CIVIL",competencia="2025")
        x=intensidade_exportacao_carne(especie="FRANGO",
                exportacao_carcaca_equiv_t=100,producao_carcaca_equiv_t=400,
                fonte_conversao="metodologia externa autorizada",calendario="ANO_CIVIL",competencia="2025")
        self.assertEqual(x["razao_exportacao_producao"],.25)

    def test_cenario_nao_é_previsao_validada(self):
        h={y:100+(y-2015)*10 for y in range(2015,2026)}
        for c in ("CANA","GERGELIM","FRANGO","SUINO"):
            z=cenario_anual(produto=c,historico=h,janela=3,horizonte=2)
            self.assertFalse(z["validado_com_dados_reais"])
            y=backtest_anual(produto=c,historico=h,janela=3)
            self.assertFalse(y["pode_promover_modelo"])

    def test_evento_risco_sem_probabilidade_inventada(self):
        v=classificar_risco(produto="FRANGO",fator="SANITARIO",
             evidencia="ALERTA_NAO_CONFIRMADO",fonte_id="MAPA",
             publicado_em="2026-10-19T12:00:00-04:00",competencia="2026-10")
        self.assertIsNone(v["probabilidade"])
        with self.assertRaises(DadoInvalido):
            classificar_risco(produto="GERGELIM",fator="SANITARIO",
             evidencia="CONFIRMADO",fonte_id="MAPA",
             publicado_em="2026-10-19T12:00:00-04:00",competencia="2026-10")


if __name__=="__main__":
    unittest.main()
