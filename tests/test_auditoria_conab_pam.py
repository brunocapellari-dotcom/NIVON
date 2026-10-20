"""Regressões offline: evidências sintéticas não legitimam modelos reais."""
import unittest

from nivon.auditoria_conab_pam import (
    ErroConciliacaoSafra, preparar_tripla_conab, confrontar_conab_pam,
)

CUT = "2026-10-20T14:00:00-03:00"
HASH = "a" * 64
SHA_PAM = "b" * 64


def meta(*, origem="CONAB", digest=HASH, comprovado=True, **trocas):
    result = dict(
        fonte_id=origem, edicao_id="SINTETICO-01", raw_sha256=digest,
        publicado_em="2025-09-01T11:00:00-03:00",
        disponivel_em="2025-09-02T10:00:00-03:00",
        coletado_em="2025-09-03T10:00:00-03:00",
        prova_disponibilidade_sha256="c" * 64 if comprovado else None,
        disponibilidade_verificada=comprovado,
    )
    result.update(trocas)
    return result


def conab_rows(*, cultura="SOJA", subtipo="TOTAL", arquivo="SojaSerieHist.xls",
               previsao=False):
    classe = ("PROJETADO_CONAB" if previsao else
              "INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO")
    return [
        dict(produto=cultura, subdivisao_safra=subtipo,
             regiao_uf="MT", safra="2024/2025", indicador=indicador,
             valor=valor, unidade=unidade, fonte="CONAB",
             arquivo=arquivo, origem_sha256=HASH,
             coletado_em="2025-09-03T10:00:00-03:00",
             classificacao=classe)
        for indicador, valor, unidade in [
            ("AREA", 1000, "HA"),
            ("PRODUTIVIDADE", 3000, "KG_HA"),
            ("PRODUCAO", 3000, "T"),
        ]
    ]


def tripla(**alteracoes):
    params = dict(linhas=conab_rows(), cultura="SOJA", subdivisao="TOTAL",
                  uf="MT", safra="2024/2025", snapshot_meta=meta(),
                  emitido_em=CUT)
    params.update(alteracoes)
    return preparar_tripla_conab(**params)


def pam():
    return dict(dataset_id="IBGE_PAM", cultura="SOJA", ano=2025,
                produto_ibge="SOJA_GRAO", uf_ibge=51,
                raw_sha256=SHA_PAM,
                area_colhida_ha="1000", producao_total_t="2900",
                municipios_no_lote=2,
                status="AGREGACAO_PARCIAL_SEM_PROVA_COBERTURA",
                municipios_reprovados_arredondamento=[])


def periodo():
    return dict(safra_conab="2024/2025", ano_pam=2025,
                metodo="CALENDARIO_REGIONAL_DOCUMENTADO",
                prova_sha256="d" * 64)


def cobertura(completa=True):
    return dict(municipios_cobertos=2,
                municipios_universo=2 if completa else 4,
                cobertura_integral_auditada=completa,
                prova_sha256="e" * 64 if completa else None)


def confronto(**overrides):
    params = dict(pacote_conab=tripla(), agregado_pam=pam(),
                  meta_pam=meta(origem="IBGE", digest=SHA_PAM),
                  ano_civil_pam=2025, conversao_temporal=periodo(),
                  cobertura_pam=cobertura(), emitido_em=CUT)
    params.update(overrides)
    return confrontar_conab_pam(**params)


class TestAuditoriaConabPam(unittest.TestCase):
    def test_tripla_conab_conservacao_sem_inventar_area_colhida(self):
        r = tripla()
        self.assertEqual(r["estado"], "TRIPLA_CONAB_ASOF_DECLARADA")
        self.assertEqual(r["producao_calculada_t"], "3000")
        self.assertEqual(r["residuo_fisico_t"], "0")
        self.assertEqual(r["area_informada_conab_ha"], "1000")
        self.assertIsNone(r["area_colhida_ha"])
        self.assertFalse(r["habilita_treino"])

    def test_confronto_descritivo_com_cobertura_declarada(self):
        result = confronto()
        self.assertEqual(result["estado"],
                         "DIFERENCA_DESCRITIVA_SEM_EQUIVALENCIA_ESTATISTICA")
        self.assertEqual(result["diferenca_producao_t"], "100")
        self.assertFalse(result["comparacao_de_acuracia"])
        self.assertFalse(result["habilita_publicacao"])
        self.assertIsNone(result["area_colhida_conab_ha"])

    def test_confronto_sem_cobertura_nao_fabrica_delta(self):
        result = confronto(cobertura_pam=cobertura(False))
        self.assertEqual(result["estado"], "NAO_COMPARAVEL_SEM_EVIDENCIAS")
        self.assertIsNone(result["diferenca_producao_t"])
        self.assertIn("COBERTURA_OU_QUALIDADE_PAM_NAO_COMPROVADA",
                      result["motivos"])

    def test_data_conab_alem_cutoff_nao_utiliza_numero(self):
        m = meta(coletado_em="2026-10-21T15:00:00-03:00")
        r = tripla(snapshot_meta=m,
                   linhas=[dict(x, coletado_em=m["coletado_em"])
                           for x in conab_rows()])
        out = confronto(pacote_conab=r)
        self.assertIn("CONAB_SEM_PROVA_ASOF", out["motivos"])
        self.assertIsNone(out["diferenca_producao_t"])

    def test_prova_de_disponibilidade_nunca_inferida(self):
        m = meta(comprovado=False)
        r = tripla(snapshot_meta=m)
        self.assertEqual(r["estado"], "TRIPLA_CONAB_SEM_PROVA_ASOF")
        self.assertIn("CONAB_SEM_PROVA_ASOF",
                      confronto(pacote_conab=r)["motivos"])

    def test_pam_sem_vintage_ou_publicacao_nao_comparavel(self):
        result = confronto(meta_pam=meta(origem="IBGE",
                                         digest=SHA_PAM, comprovado=False))
        self.assertIn("PAM_SEM_PROVA_ASOF", result["motivos"])

    def test_safra_milho_primeira_nao_pode_ser_pam_total(self):
        milho = conab_rows(cultura="MILHO", subtipo="PRIMEIRA",
                           arquivo="Milho1aSerieHist.xls")
        r = tripla(cultura="MILHO", subdivisao="PRIMEIRA", linhas=milho)
        p = pam()
        p["cultura"] = "MILHO"
        p["produto_ibge"] = "MILHO_GRAO_TOTAL"
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(pacote_conab=r, agregado_pam=p)

    def test_milho_total_pode_ser_comparado_sem_dupla_contagem(self):
        milho = conab_rows(cultura="MILHO", subtipo="TOTAL",
                           arquivo="MilhoTotalSerieHist.xls")
        r = tripla(cultura="MILHO", subdivisao="TOTAL", linhas=milho)
        p = pam()
        p["cultura"] = "MILHO"
        p["produto_ibge"] = "MILHO_GRAO_TOTAL"
        result = confronto(pacote_conab=r, agregado_pam=p)
        self.assertEqual(result["diferenca_producao_t"], "100")

    def test_classificacao_previsao_nao_eh_realizacao(self):
        r = tripla(linhas=conab_rows(previsao=True))
        self.assertEqual(r["classificacao"], "PROJETADO_CONAB")
        self.assertFalse(r["habilita_publicacao"])

    def test_producoes_mistos_ou_arquivos_de_outra_safra_bloqueados(self):
        rows = conab_rows()
        rows[1]["safra"] = "2023/2024"
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)
        rows = conab_rows()
        rows[2]["arquivo"] = "MilhoTotalSerieHist.xls"
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)
        rows = conab_rows()
        rows[1]["classificacao"] = "PROJETADO_CONAB"
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)

    def test_unidades_duplicatas_e_mistura_de_sha_bloqueados(self):
        rows = conab_rows()
        rows[1]["unidade"] = "T"
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)
        rows = conab_rows()
        rows[1]["indicador"] = "AREA"
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)
        rows = conab_rows()
        rows[1]["origem_sha256"] = "f" * 64
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)

    def test_cultura_fisica_e_uf_nao_podem_mudar(self):
        bad = pam()
        bad["produto_ibge"] = "ALGODAO_PLUMA"
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(agregado_pam=bad)
        bad = pam()
        bad["uf_ibge"] = 50
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(agregado_pam=bad)

    def test_mapeamento_de_ano_nao_eh_automatico(self):
        m = periodo()
        m["ano_pam"] = 2024
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(conversao_temporal=m)
        m = periodo()
        m["metodo"] = "ANO_SEGUINTE_INFERIDO"
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(conversao_temporal=m)

    def test_prova_cobertura_false_com_alegacao_true(self):
        m = cobertura()
        m["prova_sha256"] = None
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(cobertura_pam=m)
        m = cobertura()
        m["municipios_universo"] = 3
        with self.assertRaises(ErroConciliacaoSafra):
            confronto(cobertura_pam=m)

    def test_hash_falso_tempo_invertido_e_bool_numerico(self):
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(snapshot_meta=meta(raw_sha256="xyz"))
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(snapshot_meta=meta(
                disponivel_em="2025-08-30T10:00:00-03:00"))
        rows = conab_rows()
        rows[0]["valor"] = True
        with self.assertRaises(ErroConciliacaoSafra):
            tripla(linhas=rows)

    def test_arredondamento_divergente_aparece_no_residuo(self):
        rows = conab_rows()
        rows[2]["valor"] = 2999
        result = tripla(linhas=rows)
        self.assertEqual(result["residuo_fisico_t"], "-1")
        self.assertNotEqual(result["desvio_relativo"], "0")

    def test_pam_com_inconsistencia_de_arredondamento_nao_comparavel(self):
        p = pam()
        p["municipios_reprovados_arredondamento"] = ["5100001"]
        r = confronto(agregado_pam=p)
        self.assertIsNone(r["diferenca_producao_t"])


if __name__ == "__main__":
    unittest.main()
