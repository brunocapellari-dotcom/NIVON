"""Cenários 100% sintéticos; nenhum GET nem dado operacional do IBAMA."""
import json
import unittest

from nivon.sisfogo_roi import (
    ErroSISFOGO, conferir_lote_paginas, normalizar_pagina_roi, planejar_pagina_roi,
)

COLETA = "2026-10-21T13:40:00-04:00"


def roi(n, **campos):
    dado = {
        "id": f"497f6eca-6276-4993-bfeb-53cbbbba6f{n:02d}",
        "numeroRoi": f"ROI.TESTE.000{n}",
        "statusRoi": "FINALIZADO", "retificado": False,
        "dataHoraCriacao": "2026-09-24T12:00:00Z",
        "dataHoraUltimaAtualizacao": "2026-09-26T12:00:00Z",
        "houveCombate": True,
        "localIncendio": {
            "latitude": -12.5, "longitude": -55.5,
            "municipio": {"nomeMunicipio": "Cidade Sintética",
                          "unidadeFederativa": {"siglaUnidadeFederativa": "MT"},
                          "isAmazoniaLegal": True},
            "bioma": {"nomeBioma": "Cerrado"},
        },
        "datasIncendio": {
            "dataInicioIncendio": "2026-09-24T10:00:00Z",
            "dataDeteccaoIncendio": "2026-09-24T11:00:00Z",
            "dataExtincaoIncendio": "2026-09-25T10:00:00Z",
        },
        "combateRecursosHumanos": [{"dataReferencia": "2026-09-24",
                                   "qtdCombatentesTotal": 8}],
        "frentesCombate": [{"id": f"497f6eca-6276-4993-bfeb-53cbbbba6f{n:02d}"}],
        "meiosLocomocaoCombateIncendioDiario": [],
        "informacoesPosIncendio": {
            "estimativaAreaQueimada": 200.5,
            "vegetacoesAtingidas": [{"vegetacao": "Pastagem cultivada"}],
        },
    }
    dado.update(campos)
    return dado


def pagina(itens, *, page=1, size=2, total=None, paginas=None):
    total = len(itens) if total is None else total
    paginas = (total + size - 1) // size if paginas is None else paginas
    return {"pagina": page, "tamanhoPagina": size, "totalItens": total,
            "totalPaginas": paginas, "itens": itens}


def analisar(p, *, page=1, size=2):
    return normalizar_pagina_roi(json.dumps(p).encode(), page=page, size=size,
                                coletado_em=COLETA)


class TestSISFOGOROI(unittest.TestCase):
    def test_url_paginada_1_based_e_limite_oficial(self):
        self.assertEqual(
            planejar_pagina_roi(page=1, size=2),
            "https://sisfogo.sistema.gov.br/api/v1/roi/publico?page=1&size=2",
        )
        for p, s in ((0, 10), (1, 0), (1, 501), (True, 5), (1, False)):
            with self.subTest(p=p, s=s), self.assertRaises(ErroSISFOGO):
                planejar_pagina_roi(page=p, size=s)

    def test_roi_finalizado_preserva_identidade_tempos_e_area_estimada(self):
        x = analisar(pagina([roi(1)]))["itens"][0]
        self.assertEqual(x["roi_id"], roi(1)["id"])
        self.assertEqual(x["competencia"], "2026-09")
        self.assertEqual(x["referencia"], "2026-09-24T10:00:00+00:00")
        self.assertIsNone(x["publicacao"])
        self.assertEqual(x["coleta"], "2026-10-21T17:40:00+00:00")
        self.assertEqual(x["area_queimada_estimada_ha"], "200.5")
        self.assertEqual(x["quantidade_dias_recursos_registrados"], 1)
        self.assertEqual(x["codigo_ibge"], None)
        self.assertFalse(x["apto_publicacao"])
        self.assertEqual(x["uf"], "MT")

    def test_roi_retificado_preserva_data_da_ultima_atualizacao(self):
        x = analisar(pagina([roi(1, retificado=True,
                                   dataHoraUltimaAtualizacao="2026-10-20T15:00:00Z")]))["itens"][0]
        self.assertTrue(x["retificado"])
        self.assertEqual(x["ultima_atualizacao_em_utc"], "2026-10-20T15:00:00+00:00")

    def test_sem_combate_nao_inventa_equipes_ou_recursos(self):
        zero = roi(1, houveCombate=False, combateRecursosHumanos=None,
                   meiosLocomocaoCombateIncendioDiario=None)
        x = analisar(pagina([zero]))["itens"][0]
        self.assertFalse(x["houve_combate"])
        self.assertEqual(x["quantidade_dias_recursos_registrados"], 0)

    def test_sem_inicio_fogo_nao_inventa_referencia(self):
        x = analisar(pagina([roi(1, datasIncendio={})]))["itens"][0]
        self.assertIsNone(x["competencia"])
        self.assertIsNone(x["referencia"])

    def test_recusa_roi_em_andamento(self):
        with self.assertRaises(ErroSISFOGO):
            analisar(pagina([roi(1, statusRoi="EM_ANDAMENTO")]))

    def test_recusa_coordenada_invalida_e_booleans_falsos(self):
        for dado in (
            roi(1, retificado="true"),
            roi(1, houveCombate=1),
            roi(1, localIncendio={"latitude": 91.1, "longitude": -55.5}),
            roi(1, localIncendio={"latitude": 0.0}),
            roi(1, localIncendio={"latitude": 0.0, "longitude": float("nan")}),
            roi(1, informacoesPosIncendio={"estimativaAreaQueimada": -1}),
            roi(1, informacoesPosIncendio={"estimativaAreaQueimada": 0,
                                         "vegetacoesAtingidas": ["texto"]}),
            roi(1, dataHoraCriacao="2026-09-24T12:00:00"),
            roi(1, dataHoraUltimaAtualizacao="2026-09-20T12:00:00Z"),
        ):
            with self.subTest(dado=dado), self.assertRaises(ErroSISFOGO):
                analisar(pagina([dado]))

    def test_falso_zero_da_documentacao_nao_e_resposta_real(self):
        with self.assertRaises(ErroSISFOGO):
            analisar({"pagina": 0, "tamanhoPagina": 0, "totalItens": 0,
                     "totalPaginas": 0, "itens": [roi(1)]})

    def test_paginacao_inconsistente_ou_vazia_rejeitada(self):
        casos = [
            pagina([roi(1)], page=2, total=1, paginas=1),
            pagina([], total=3, paginas=2),
            pagina([roi(1), roi(1)]),
            pagina([roi(1)], total=3, paginas=2),
            pagina([roi(1)], total=0, paginas=0),
            pagina([roi(1)], total=2, paginas=1),
        ]
        for p in casos:
            with self.subTest(p=p), self.assertRaises(ErroSISFOGO):
                analisar(p)

    def test_lote_multi_pagina_sem_somar_dobrado(self):
        a = analisar(pagina([roi(1), roi(2)], total=3, paginas=2))
        b = analisar(pagina([roi(3)], page=2, total=3, paginas=2), page=2)
        resumo = conferir_lote_paginas([a, b])
        self.assertEqual(resumo["total_registros"], 3)
        self.assertFalse(resumo["coleta_atomica_remota_comprovada"])

    def test_rejeita_repeticao_entre_paginas_e_total_deslocado(self):
        a = analisar(pagina([roi(1), roi(2)], total=3, paginas=2))
        b = analisar(pagina([roi(2)], page=2, total=3, paginas=2), page=2)
        with self.assertRaises(ErroSISFOGO):
            conferir_lote_paginas([a, b])
        with self.assertRaises(ErroSISFOGO):
            conferir_lote_paginas([a])

    def test_sem_ocorrencias_nao_equivale_zero_incendios_no_brasil(self):
        out = analisar(pagina([], size=2, total=0, paginas=0))
        resumo = conferir_lote_paginas([out])
        self.assertEqual(resumo["total_registros"], 0)
        self.assertFalse(resumo["apto_publicacao"])

    def test_rejeita_json_chave_duplicada_payload_gigante(self):
        for raw in (b'{"pagina":1,"pagina":1}',
                    b"[]",
                    b"x" * 8_000_001):
            with self.subTest(raw=raw[:20]), self.assertRaises(ErroSISFOGO):
                normalizar_pagina_roi(raw, page=1, size=2, coletado_em=COLETA)

    def test_nao_inferir_conclusao_operacional_do_status_da_api(self):
        out = analisar(pagina([roi(1)]))
        self.assertEqual(out["estado"], "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO")
        self.assertFalse(out["apto_publicacao"])


if __name__ == "__main__":
    unittest.main()
