import unittest

from nivon.inteligencia_agricola_safras import (
    ErroCenarioSafra, estimar_oferta_remanescente, SEGMENTOS,
)


HASH = "a" * 64
IDENTIDADE = dict(cultura="SOJA", segmento="SOJA",
                  produto_fisico="SOJA_GRAO", regiao_ibge="51")


def atual(**overrides):
    row = dict(IDENTIDADE, area_alvo_colheita_ha="100",
               area_colhida_ha="10", producao_colhida_t="10",
               publicado_em="2026-10-19T10:00:00-03:00",
               disponivel_em="2026-10-19T11:00:00-03:00",
               coletado_em="2026-10-20T11:00:00-03:00",
               fonte_id="SINTETICO", edicao_id="FAKE-2026", raw_sha256=HASH)
    row.update(overrides)
    return row


def historico():
    series = []
    for ix, ano in enumerate(range(2018, 2023), 1):
        series.append(dict(
            IDENTIDADE, ano_safra=ano, area_colhida_ha="100",
            producao_t=str(ix * 100),
            publicado_em=f"{ano + 1}-06-01T10:00:00-03:00",
            disponivel_em=f"{ano + 1}-06-02T10:00:00-03:00",
            coletado_em=f"{ano + 1}-06-03T10:00:00-03:00",
            fonte_id="SINTETICO", edicao_id=f"FAKE-{ano}",
            raw_sha256=HASH,
        ))
    return series


def rodar(*,obs=None, hist=None, **overrides):
    kwargs = dict(IDENTIDADE, ano_safra=2026,
                  emitido_em="2026-10-20T12:00:00-03:00",
                  observacao_atual=atual() if obs is None else obs,
                  historico=historico() if hist is None else hist)
    kwargs.update(overrides)
    return estimar_oferta_remanescente(**kwargs)


class TestInteligenciaAgricola(unittest.TestCase):
    def test_cobertura_sete_culturas(self):
        self.assertEqual(set(SEGMENTOS),
                         {"SOJA", "MILHO", "ALGODAO", "TRIGO",
                          "SORGO", "CANA", "GERGELIM"})

    def test_conservacao_area_producao_e_unidades(self):
        result = rodar()
        self.assertEqual(result["area_remanescente_ha"], "90")
        self.assertEqual(result["producao_colhida_t"], "10")
        self.assertEqual(result["cenarios"]["Q50"]["rendimento_area_remanescente_kg_ha"],
                         "3000.0")
        self.assertEqual(result["cenarios"]["Q50"]["producao_final_condicional_t"],
                         "280.0")
        self.assertEqual(result["cenarios"]["Q10"]["producao_final_condicional_t"],
                         "136.00")
        self.assertEqual(result["cenarios"]["Q90"]["producao_final_condicional_t"],
                         "424.00")
        self.assertFalse(result["habilita_previsao"])
        self.assertFalse(result["habilita_publicacao"])

    def test_safra_100_pct_colhida_eh_observada_sem_projecao_adicional(self):
        r = rodar(obs=atual(area_colhida_ha="100", producao_colhida_t="250"))
        for cenario in r["cenarios"].values():
            self.assertEqual(float(cenario["producao_final_condicional_t"]), 250.)
            self.assertEqual(float(cenario["producao_ainda_nao_colhida_cenario_t"]), 0.)

    def test_sem_colheita_nao_inventa_rendimento_atual(self):
        r = rodar(obs=atual(area_colhida_ha="0", producao_colhida_t="0"))
        self.assertIsNone(r["rendimento_area_colhida_kg_ha"])
        self.assertEqual(float(r["cenarios"]["Q50"]["producao_final_condicional_t"]), 300.)

    def test_historia_posterior_ao_cutoff_reduz_cobertura(self):
        rows = historico()
        rows[-1]["publicado_em"] = "2026-10-21T12:00:00Z"
        rows[-1]["disponivel_em"] = "2026-10-21T13:00:00Z"
        rows[-1]["coletado_em"] = "2026-10-22T12:00:00Z"
        r = rodar(hist=rows)
        self.assertEqual(r["estado"], "HISTORICO_ASOF_INSUFICIENTE")
        self.assertIsNone(r["cenarios"])
        self.assertEqual(r["safras_elegiveis"], 4)

    def test_bloqueia_dados_atuais_ainda_nao_publicados(self):
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(publicado_em="2026-10-21T10:00:00Z",
                           disponivel_em="2026-10-21T10:00:00Z",
                           coletado_em="2026-10-21T10:00:00Z"))

    def test_bloqueia_ausencia_fuso_ou_cronologia_invalida(self):
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(coletado_em="2026-10-20T11:00:00"))
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(disponivel_em="2026-10-17T11:00:00-03:00"))

    def test_bloqueia_mistura_de_milho_safras(self):
        obs = atual(cultura="MILHO", segmento="MILHO_2",
                    produto_fisico="MILHO_GRAO")
        rows = [dict(r, cultura="MILHO", segmento="MILHO_2",
                     produto_fisico="MILHO_GRAO") for r in historico()]
        rows[0]["segmento"] = "MILHO_TOTAL"
        with self.assertRaises(ErroCenarioSafra):
            rodar(cultura="MILHO", segmento="MILHO_2",
                  produto_fisico="MILHO_GRAO", obs=obs, hist=rows)

    def test_bloqueia_algodao_caroco_vs_pluma(self):
        obs = atual(cultura="ALGODAO", segmento="ALGODAO",
                    produto_fisico="ALGODAO_EM_CAROCO")
        rows = [dict(r, cultura="ALGODAO", segmento="ALGODAO",
                     produto_fisico="ALGODAO_PLUMA") for r in historico()]
        with self.assertRaises(ErroCenarioSafra):
            rodar(cultura="ALGODAO", segmento="ALGODAO",
                  produto_fisico="ALGODAO_EM_CAROCO", obs=obs, hist=rows)

    def test_cana_nao_usa_area_plantada_como_colhida(self):
        obs = atual(cultura="CANA", segmento="CANA",
                    produto_fisico="CANA_COLMOS")
        rows = [dict(r, cultura="CANA", segmento="CANA",
                     produto_fisico="CANA_COLMOS") for r in historico()]
        r = rodar(cultura="CANA", segmento="CANA",
                  produto_fisico="CANA_COLMOS", obs=obs, hist=rows)
        self.assertEqual(r["area_remanescente_ha"], "90")

    def test_rejeita_area_e_producao_impossiveis(self):
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(area_colhida_ha="101"))
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(area_colhida_ha="0", producao_colhida_t="1"))
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(area_colhida_ha="10", producao_colhida_t="500"))

    def test_gergelim_sem_historico_nao_gera_previsao(self):
        obs = atual(cultura="GERGELIM", segmento="GERGELIM",
                    produto_fisico="GERGELIM_SEMENTE")
        rows = [dict(historico()[-1], cultura="GERGELIM",
                     segmento="GERGELIM", produto_fisico="GERGELIM_SEMENTE")]
        result = rodar(cultura="GERGELIM", segmento="GERGELIM",
                      produto_fisico="GERGELIM_SEMENTE", obs=obs, hist=rows)
        self.assertEqual(result["estado"], "HISTORICO_ASOF_INSUFICIENTE")
        self.assertIsNone(result["cenarios"])

    def test_temporal_duplicatas_hash_regiao_e_valores_nan(self):
        rows = historico()
        with self.assertRaises(ErroCenarioSafra):
            rodar(hist=rows + [dict(rows[0])])
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(raw_sha256="sem-prova"))
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(regiao_ibge="50"))
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(producao_colhida_t="NaN"))

    def test_ano_futuro_sem_escopo_e_booleanos_rejeitados(self):
        rows = historico()
        rows[0]["ano_safra"] = 2026
        with self.assertRaises(ErroCenarioSafra):
            rodar(hist=rows)
        with self.assertRaises(ErroCenarioSafra):
            rodar(obs=atual(area_colhida_ha=True))
        with self.assertRaises(ErroCenarioSafra):
            rodar(segmento="MILHO_2")


if __name__ == "__main__":
    unittest.main()
