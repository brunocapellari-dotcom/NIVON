"""Regressão sintética — motores das 15 cadeias e 8 frentes transversais.

Nenhum teste baixa dados reais ou valida capacidade preditiva.
"""
import unittest

from nivon.motores import DadoInvalido
from nivon.motores_agro_estrategicos import (
    safra_comercializacao, referencia_futuros_graos, esmagamento_soja,
    milho_safras_demanda, algodao_beneficiamento, boi_rendimento_carcaca,
    relacao_troca_bezerro, referencia_acucar_ice, paridade_importacao_trigo,
    sorgo_substituicao_racao, paridade_fertilizante, paridade_diesel,
    simulacao_etanol_ddg,
)
from nivon.motores_meteo_hidro import (
    chuva_anomalia,graus_dia,balanco_hidrico_solo,janela_chuva_operacao,
    anomalia_nivel_rio,anomalia_vazao,folga_calado_hipotetica,
)
from nivon.motores_integracao_estrategica import (
    pressao_armazenagem,demanda_fertilizante_cenario,custo_frete_rodoviario,
    comparacao_intermodal,pressao_portuaria,comercio_exterior_recorte,
    sensibilidade_macro,evento_geopolitico,margem_processamento,
)


class TestAgroEspecializado(unittest.TestCase):
    def test_soja_safra_e_comercializacao(self):
        r=safra_comercializacao(produto="SOJA",area_ha=1000,producao_t=3600,
                area_colhida_ha=600,volume_vendido_t=1800,fonte="fixture")
        self.assertEqual(r["produtividade_kg_ha"],3600)
        self.assertEqual(r["percentual_producao_comercializada"],50)
        self.assertEqual(r["percentual_area_colhida"],60)

    def test_comercializacao_nao_pode_superar_producao(self):
        with self.assertRaises(DadoInvalido):
            safra_comercializacao(produto="SOJA",area_ha=10,producao_t=50,
                area_colhida_ha=9,volume_vendido_t=51,fonte="fixture")

    def test_cbot_converte_unidades_por_produto(self):
        soja=referencia_futuros_graos(produto="SOJA",usd_por_bushel=10,
             cambio_rs_usd=5,ajuste_base_usd_t=0,frete_mais_custos_rs_t=0,fonte="fixture")
        milho=referencia_futuros_graos(produto="MILHO",usd_por_bushel=10,
             cambio_rs_usd=5,ajuste_base_usd_t=0,frete_mais_custos_rs_t=0,fonte="fixture")
        self.assertGreater(milho["benchmark_rs_t"],soja["benchmark_rs_t"])
        self.assertAlmostEqual(soja["benchmark_rs_saca_60kg"],soja["benchmark_rs_t"]*.06)

    def test_cbot_nao_extrapola_commodities(self):
        with self.assertRaises(DadoInvalido):
            referencia_futuros_graos(produto="TRIGO",usd_por_bushel=10,
                cambio_rs_usd=5,ajuste_base_usd_t=0,frete_mais_custos_rs_t=0,fonte="fixture")

    def test_soja_balanco_massa(self):
        r=esmagamento_soja(soja_t=1000,rendimento_farelo=.77,
            rendimento_oleo=.19,rendimento_outros_e_perdas=.04,fonte="fixture")
        self.assertEqual(r["farelo_t"],770)
        self.assertAlmostEqual(sum(r[k] for k in ("farelo_t","oleo_t","outros_e_perdas_t")),1000)
        with self.assertRaises(DadoInvalido):
            esmagamento_soja(soja_t=1000,rendimento_farelo=.8,
                rendimento_oleo=.3,rendimento_outros_e_perdas=0,fonte="fixture")

    def test_milho_tres_safras_sem_somar_total_duas_vezes(self):
        r=milho_safras_demanda(primeira_t=100,segunda_t=500,terceira_t=50,
            total_oficial_t=650,consumo_interno_total_t=300,
            consumo_racao_parcela_t=150,consumo_industrial_parcela_t=100,fonte="fixture")
        self.assertEqual(r["producao_soma_safras_t"],650)
        self.assertEqual(r["outros_usos_t"],50)
        with self.assertRaises(DadoInvalido):
            milho_safras_demanda(primeira_t=100,segunda_t=500,terceira_t=50,
                total_oficial_t=650,consumo_interno_total_t=300,
                consumo_racao_parcela_t=250,consumo_industrial_parcela_t=100,fonte="fixture")

    def test_algodao_nao_mistura_pluma_com_caroco(self):
        x=algodao_beneficiamento(algodao_em_caroco_t=1000,
            fracao_pluma=.4,fracao_caroco=.52,fracao_residuos_perdas=.08,fonte="fixture")
        self.assertEqual(x["pluma_t"],400)
        self.assertEqual(x["caroco_semente_t"],520)

    def test_boi_arroba_de_carcaca(self):
        x=boi_rendimento_carcaca(cabecas_abatidas=100,peso_vivo_medio_kg=500,
            rendimento_carcaca=.52,preco_rs_arroba=300,fonte="fixture")
        self.assertAlmostEqual(x["peso_carcaca_estimado_kg_cabeca"],260)
        self.assertAlmostEqual(x["carcaca_total_estimada_t"],26)
        self.assertAlmostEqual(x["arrobas_carcaca_cabeca"],260/15)
        with self.assertRaises(DadoInvalido):
            boi_rendimento_carcaca(cabecas_abatidas=10.5,peso_vivo_medio_kg=500,
                rendimento_carcaca=.52,preco_rs_arroba=300,fonte="fixture")

    def test_bezerro_relacao_de_troca_bruta(self):
        x=relacao_troca_bezerro(preco_bezerro_rs_cabeca=2500,
            preco_boi_rs_arroba=300,peso_carcaca_boi_kg=250,fonte="fixture")
        self.assertAlmostEqual(x["bezerros_por_valor_bruto_boi"],2)

    def test_acucar_lb_t_ice_nao_fob(self):
        x=referencia_acucar_ice(centavos_usd_libra=20,cambio_rs_usd=5,
            basis_usd_t=0,custos_rs_t=0,fonte="fixture")
        self.assertAlmostEqual(x["ice_referencia_usd_t"],440.924524,places=5)

    def test_trigo_paridade_importacao(self):
        x=paridade_importacao_trigo(fob_usd_t=200,frete_maritimo_usd_t=30,
            seguro_usd_t=2,cambio_rs_usd=5,tributos_rs_t=100,
            porto_e_frete_interno_rs_t=50,fonte="fixture")
        self.assertEqual(x["cif_usd_t"],232)
        self.assertEqual(x["custo_posto_destino_rs_t"],1310)

    def test_sorgo_substituicao_nao_nutricao_automatica(self):
        x=sorgo_substituicao_racao(milho_substituido_t=1000,preco_milho_rs_t=1000,
            preco_sorgo_rs_t=850,fracao_substituivel_validada=.4,fonte="fixture")
        self.assertEqual(x["economia_insumos_rs"],60000)
        with self.assertRaises(DadoInvalido):
            sorgo_substituicao_racao(milho_substituido_t=1000,preco_milho_rs_t=1000,
                preco_sorgo_rs_t=850,fracao_substituivel_validada=1.5,fonte="fixture")

    def test_fertilizantes_quatro_classes_e_cif(self):
        for p in ("UREIA","MAP","DAP","KCL"):
            x=paridade_fertilizante(produto=p,fob_usd_t=300,frete_usd_t=50,
                seguro_usd_t=5,cambio_rs_usd=5,tributos_rs_t=100,
                porto_rs_t=30,frete_interno_rs_t=120,fonte="fixture")
            self.assertEqual(x["custo_importado_posto_rs_t"],2025)

    def test_diesel_a_vs_b_sem_brent_direto(self):
        x=paridade_diesel(diesel_a_usd_t=800,cambio_rs_usd=5,
            densidade_diesel_a_kg_l=.84,custos_diesel_a_rs_l=0,
            preco_biodiesel_rs_l=5,fracao_biodiesel=.15,
            tributos_margens_b_rs_l=1,preco_observado_diesel_b_rs_l=6,fonte="fixture")
        self.assertAlmostEqual(x["referencia_diesel_a_rs_l"],3.36)
        self.assertAlmostEqual(x["referencia_diesel_b_rs_l"],4.606)
        self.assertAlmostEqual(x["diferenca_observado_menos_referencia_rs_l"],1.394)
        with self.assertRaises(DadoInvalido):
            paridade_diesel(diesel_a_usd_t=800,cambio_rs_usd=5,
                densidade_diesel_a_kg_l=840,custos_diesel_a_rs_l=0,
                preco_biodiesel_rs_l=5,fracao_biodiesel=.15,
                tributos_margens_b_rs_l=1,preco_observado_diesel_b_rs_l=6,fonte="fixture")

    def test_etanol_ddg_coeficientes_nao_fisica(self):
        x=simulacao_etanol_ddg(milho_processado_t=1000,litros_etanol_por_t=440,
            ddg_kg_por_t=331,oleo_l_por_t=20.4,fonte_coeficientes="hipotese")
        self.assertEqual(x["etanol_l"],440000)
        self.assertEqual(x["ddg_kg"],331000)
        self.assertIn("NAO_BALANCO_FISICO",x["classificacao"])


class TestMeteoHidro(unittest.TestCase):
    def test_chuva_desvio_nao_spi(self):
        x=chuva_anomalia(chuva_observada_mm=80,normal_periodo_mm=100,
            periodo="2026-10",estacao_fonte="INMET fixture")
        self.assertAlmostEqual(x["anomalia_percentual"],-20)
        self.assertIn("NAO_SPI",x["classificacao"])

    def test_normal_chuva_zero_bloqueada(self):
        with self.assertRaises(DadoInvalido):
            chuva_anomalia(chuva_observada_mm=0,normal_periodo_mm=0,
                periodo="2026-10",estacao_fonte="fixture")

    def test_graus_dia_de_estacao(self):
        x=graus_dia(temperaturas_diarias=[
            {"data":"2026-10-17","tmin_c":20,"tmax_c":30},
            {"data":"2026-10-18","tmin_c":20,"tmax_c":32},
        ],temperatura_base_c=10,temperatura_teto_c=30,fonte="fixture")
        self.assertAlmostEqual(x["graus_dia_acumulados_c_dia"],31)
        with self.assertRaises(DadoInvalido):
            graus_dia(temperaturas_diarias=[
                {"data":"2026-10-17","tmin_c":30,"tmax_c":10}],
                temperatura_base_c=10,fonte="fixture")

    def test_solo_conserva_agua_e_deficit(self):
        x=balanco_hidrico_solo(dias=[
            {"data":"2026-10-17","chuva_mm":10,"eto_mm":5,"kc":1},
            {"data":"2026-10-18","chuva_mm":0,"eto_mm":30,"kc":1},
        ],capacidade_agua_mm=20,agua_inicial_mm=10,
          fonte_eto="fixture",fonte_precipitacao="fixture")
        self.assertEqual(x["agua_final_mm"],0)
        self.assertEqual(x["deficit_acumulado_mm"],15)
        with self.assertRaises(DadoInvalido):
            balanco_hidrico_solo(dias=[
                {"data":"2026-10-17","chuva_mm":10,"eto_mm":5,"kc":1},
                {"data":"2026-10-19","chuva_mm":0,"eto_mm":30,"kc":1}],
              capacidade_agua_mm=20,agua_inicial_mm=10,
              fonte_eto="fixture",fonte_precipitacao="fixture")

    def test_chuva_operacao_nao_prova_rodovia(self):
        x=janela_chuva_operacao(previsoes_mm_por_dia=[0,20,40],
                limiar_diario_mm=25,fonte_previsao="modelo",
                emitida_em="2026-10-19T08:00:00-04:00")
        self.assertEqual(x["dias_acima_do_limiar"],1)
        self.assertEqual(x["chuva_prevista_acumulada_mm"],60)

    def test_cota_rio_nao_vira_calado(self):
        x=anomalia_nivel_rio(estacao_id="ANA-1",cota_atual_cm=-30,
                cota_referencia_mesma_epoca_cm=20,fonte_cota="fixture",
                mes_referencia="2026-10")
        self.assertEqual(x["diferenca_cota_cm"],-50)
        self.assertNotIn("calado",x)
        y=anomalia_vazao(vazao_observada_m3_s=500,normal_mes_m3_s=1000,
                estacao_id="ANA-1",fonte="fixture")
        self.assertEqual(y["anomalia_percentual"],-50)

    def test_calado_somente_triangulacao_geometrica(self):
        x=folga_calado_hipotetica(profundidade_canal_m=3,
            calado_embarcacao_m=2.5,folga_minima_abaixo_quilha_m=.6,
            fonte_sondagem="fixture",referencia_vertical="datum_fixture")
        self.assertTrue(x["profundidade_insuficiente_na_hipotese"])
        self.assertIn("SEM_AUTORIZACAO",x["classificacao"])


class TestInteligenciaTransversal(unittest.TestCase):
    def test_armazenagem_pressao_nao_estoque(self):
        x=pressao_armazenagem(producao_pico_t=200,capacidade_estatica_t=100,
            fonte="CONAB fixture")
        self.assertIsNone(x["ocupacao_real_calculada"])
        self.assertEqual(x["razao_producao_capacidade"],2)

    def test_demanda_fertilizante_nao_consumo_real(self):
        x=demanda_fertilizante_cenario(area_ha=1000,dose_kg_ha=250,
            fracao_area_atendida=.5,fonte_recomendacao="hipotese")
        self.assertEqual(x["demanda_formulada_estimativa_t"],125)

    def test_frete_anunciado_nao_negociado(self):
        x=custo_frete_rodoviario(distancia_km=500,custo_variavel_rs_km=3,
            custos_fixos_viagem_rs=400,pedagios_rs=100,
            carga_util_t=40,frete_anunciado_rs_t=60,fonte="fixture")
        self.assertEqual(x["custo_viagem_rs"],2000)
        self.assertEqual(x["receita_potencial_anunciada_rs"],2400)
        self.assertEqual(x["saldo_teorico_rs"],400)

    def test_intermodal_requer_capacidade_verificada(self):
        d=dict(rodoviario_rs_t=200,ferroviario_rs_t=100,
                transbordos_rs_t=25,trecho_complementar_rs_t=50,
                restricoes_verificadas=True,fonte="fixture")
        x=comparacao_intermodal(**d)
        self.assertEqual(x["diferenca_intermodal_menos_rodoviario_rs_t"],-25)
        with self.assertRaises(DadoInvalido):
            comparacao_intermodal(**dict(d,restricoes_verificadas=False))

    def test_porto_programado_nao_realizado(self):
        x=pressao_portuaria(volume_programado_t=20000,
            capacidade_diaria_t=5000,toneladas_embarcadas_confirmadas_t=0,
            fonte="fixture")
        self.assertEqual(x["dias_teoricos_para_programacao"],4)
        self.assertEqual(x["volume_confirmado_embarcado_t"],0)

    def test_comex_fob_cif_separados(self):
        x=comercio_exterior_recorte(exportacao_kg=1000,exportacao_fob_usd=2000,
            importacao_kg=2000,importacao_cif_usd=6000,
            periodo_ncm_uf_verificado=True,fonte="fixture")
        self.assertEqual(x["saldo_fisico_t"],-1)
        self.assertEqual(x["valor_unitario_fob_exportacao_usd_t"],2000)
        self.assertEqual(x["valor_unitario_cif_importacao_usd_t"],3000)

    def test_macro_elasticidade_nao_causal(self):
        x=sensibilidade_macro(preco_base_rs_t=1000,choque_cambio_fracao=.1,
            choque_preco_internacional_fracao=.2,elasticidade_cambio=1,
            elasticidade_preco=.5,fonte_calibracao="hipótese de teste")
        self.assertAlmostEqual(x["preco_cenario_rs_t"],1200)
        self.assertIn("CENARIO",x["classificacao"])

    def test_evento_geopolitico_sem_probabilidade(self):
        x=evento_geopolitico(evento_id="FIXTURE-1",fator="SANCAO",
            cadeias_afetadas=["DIESEL","FERTILIZANTES"],
            tipo_evidencia="RELATO",fonte_id="fonte teste",
            publicacao="2026-10-19T09:00:00-04:00",
            impactos_hipoteticos=["CUSTO_IMPORTACAO"])
        self.assertIsNone(x["probabilidade"])
        with self.assertRaises(DadoInvalido):
            evento_geopolitico(evento_id="FIXTURE-1",fator="GUERRA",
                cadeias_afetadas=["SOJA"],tipo_evidencia="RELATO",
                fonte_id="fonte teste",publicacao="2026-10-19",
                impactos_hipoteticos=[])

    def test_industria_balanco_e_margem(self):
        x=margem_processamento(materia_prima_t=100,
            custo_materia_prima_rs_t=1000,produtos_saida=["FARELO","OLEO"],
            receita_precos_rs_t={"FARELO":1400,"OLEO":5000},
            rendimentos_t_por_t={"FARELO":.78,"OLEO":.19},
            despesas_outros_rs=1000,fonte_parametros="fixture")
        self.assertAlmostEqual(x["residuo_perdas_t"],3)
        self.assertGreater(x["margem_contribuicao_rs"],0)
        with self.assertRaises(DadoInvalido):
            margem_processamento(materia_prima_t=100,
                custo_materia_prima_rs_t=1000,produtos_saida=["FARELO","OLEO"],
                receita_precos_rs_t={"FARELO":1400,"OLEO":5000},
                rendimentos_t_por_t={"FARELO":.9,"OLEO":.2},
                despesas_outros_rs=1000,fonte_parametros="fixture")


if __name__=="__main__":
    unittest.main()
