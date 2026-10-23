"""Regressões do inventário de páginas oficiais CONAB.

Datas são metadados exibidos pelo portal em 21/10/2026, não RAW arquivado.
Testes de lógica temporal usam também dados alterados propositalmente.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from nivon.conab_levantamentos_candidatos import (
    auditar_candidatos_levantamentos_conab,
    ErroCatalogoLevantamentosConab,
)

CONFIG = (Path(__file__).resolve().parents[1] /
          "config/conab_levantamentos_candidatos.v1.json")
DIA_CORTE = "2026-10-21T19:30:00Z"


def registros():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def auditar(rows=None, cutoff=DIA_CORTE):
    return auditar_candidatos_levantamentos_conab(
        registros=registros() if rows is None else rows, instante_decisao=cutoff,
    )


class TestLevantamentosConabCandidatos(unittest.TestCase):
    def test_quatro_páginas_oficiais_sem_numeros_e_sem_backtest(self):
        out = auditar()
        self.assertEqual(out["total"], 4)
        self.assertEqual(out["fonte_id"], "CONAB")
        self.assertFalse(out["evidencia_raw_confirmada"])
        self.assertFalse(out["habilita_publicacao"])
        self.assertRegex(out["sha256_catalogo_curado_nao_raw"], r"^[0-9a-f]{64}$")
        for entry in out["candidatos"]:
            self.assertEqual(entry["estado_no_corte"],
                             "SOMENTE_METADADOS_ATUAIS_SEM_RAW_HISTORICO")
            self.assertIsNone(entry["prova_raw_sha256"])
            self.assertFalse(entry["disponibilidade_historica_verificada"])
            self.assertFalse(entry["pode_extrair_numero_historico"])
            self.assertFalse(entry["habilita_treino"])
            self.assertFalse(entry["habilita_backtest"])

    def test_pagina_de_2023_revisada_em_2025_nao_prova_cutoff_2023(self):
        rows = [registros()[0]]
        out = auditar(rows, "2023-12-20T12:00:00Z")
        self.assertEqual(out["candidatos"][0]["estado_no_corte"],
                         "PAGINA_PORTAL_MODIFICADA_APOS_CORTE")
        self.assertTrue(out["candidatos"][0]["revisao_portal_posterior_publicacao"])

    def test_pagina_de_2025_revisada_depois_do_levantamento(self):
        out = auditar([registros()[2]], "2025-04-10T16:00:00Z")
        self.assertEqual(out["candidatos"][0]["estado_no_corte"],
                         "PAGINA_PORTAL_MODIFICADA_APOS_CORTE")
        self.assertFalse(out["candidatos"][0]["habilita_backtest"])

    def test_cutoff_anterior_ao_primeiro_levantamento_2026(self):
        out = auditar([registros()[-1]], "2026-10-14T12:00:00Z")
        self.assertEqual(out["candidatos"][0]["estado_no_corte"],
                         "PUBLICACAO_PORTAL_POSTERIOR_AO_CORTE")

    def test_atualizado_pode_ser_anterior_a_publicacao(self):
        out = auditar([registros()[-1]], "2026-10-21T12:00:00Z")
        item = out["candidatos"][0]
        self.assertFalse(item["revisao_portal_posterior_publicacao"])
        self.assertFalse(item["disponibilidade_historica_verificada"])

    def test_nao_promove_vintage_mesmo_para_data_anterior_a_corte(self):
        out = auditar([registros()[0]], "2026-10-21T12:00:00Z")
        entry = out["candidatos"][0]
        self.assertEqual(entry["estado_no_corte"],
                         "SOMENTE_METADADOS_ATUAIS_SEM_RAW_HISTORICO")
        self.assertFalse(entry["pode_extrair_numero_historico"])

    def test_duplicidade_de_safra_e_numero_bloqueada(self):
        rows = registros()
        with self.assertRaisesRegex(ErroCatalogoLevantamentosConab, "duplicada"):
            auditar([rows[0], deepcopy(rows[0])])

    def test_falsificacao_de_dominios_e_slugs_bloqueada(self):
        for url in (
            "https://evil.example/conab/boletins/3o-levantamento-safra-2023-24",
            "https://www.gov.br.evil.example/conab/boletim",
            "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-graos/boletim-da-safra-de-graos/3o-levantamento-safra-2024-25",
            registros()[0]["pagina_url"]+"?inject=1",
            registros()[0]["pagina_url"]+"/arquivo.pdf",
        ):
            with self.subTest(url=url):
                item=deepcopy(registros()[0])
                item["pagina_url"]=url
                with self.assertRaisesRegex(ErroCatalogoLevantamentosConab, "URL"):
                    auditar([item])

    def test_safra_ano_incoerente_e_levantamento_booleano(self):
        item=deepcopy(registros()[0])
        item["safra"]="2023/25"
        with self.assertRaisesRegex(ErroCatalogoLevantamentosConab, "safra"):
            auditar([item])
        item=deepcopy(registros()[0])
        item["numero_levantamento"]=True
        with self.assertRaisesRegex(ErroCatalogoLevantamentosConab, "número"):
            auditar([item])

    def test_timestamp_sem_fuso_falha_fechada(self):
        for field in ("publicado_portal_em","atualizado_portal_em"):
            item=deepcopy(registros()[0])
            item[field]="2025-01-24T12:45:00"
            with self.subTest(field=field):
                with self.assertRaises(ErroCatalogoLevantamentosConab):
                    auditar([item])

    def test_consulta_anterior_ao_carimbo_portal_bloqueada(self):
        item=deepcopy(registros()[-1])
        item["inspecionado_dia"]="2026-10-14"
        with self.assertRaisesRegex(ErroCatalogoLevantamentosConab, "posteriores"):
            auditar([item])

    def test_campos_desconhecidos_rejeitados(self):
        item=deepcopy(registros()[0])
        item["raw_verificado"]=True
        with self.assertRaisesRegex(ErroCatalogoLevantamentosConab, "campos"):
            auditar([item])

    def test_lista_vazia_e_excessiva(self):
        with self.assertRaises(ErroCatalogoLevantamentosConab):
            auditar([])
        with self.assertRaises(ErroCatalogoLevantamentosConab):
            auditar([registros()[0]]*151)

    def test_revisoes_por_diferentes_fusos_sao_comparaveis(self):
        item=deepcopy(registros()[0])
        item["atualizado_portal_em"]="2025-01-24T15:45:00Z"
        out=auditar([item],"2024-01-01T00:00:00Z")
        self.assertEqual(out["candidatos"][0]["estado_no_corte"],
                         "PAGINA_PORTAL_MODIFICADA_APOS_CORTE")

    def test_ordem_nao_altera_estado_da_edicao(self):
        items=registros()
        a=auditar(items)
        b=auditar(list(reversed(items)))
        self.assertEqual(
            [(x["safra"],x["numero_levantamento"],x["estado_no_corte"])
             for x in a["candidatos"]],
            [(x["safra"],x["numero_levantamento"],x["estado_no_corte"])
             for x in b["candidatos"]],
        )
        self.assertFalse(a["habilita_publicacao"])


if __name__ == "__main__":
    unittest.main()
