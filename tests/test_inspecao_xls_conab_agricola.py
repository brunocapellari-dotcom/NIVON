"""Regressões da inspeção XLS CONAB; fixture do workbook é simulada.

Os bytes OLE2 utilizados não contêm um XLS real, e o decodificador é
substituído por objeto que implementa interface do xlrd. NÃO constitui
validação do layout atual oficial ou execução do xlrd em dados reais.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
from unittest import TestCase, mock

from nivon.inspecao_xls_conab_agricola import (
    inspecionar_xls_conab_capturado, ErroLeituraXLSConab,
)
from nivon.prova_raw_conab_agricola import verificar_raw_conab
from test_conab_series import LivroFalso
from test_prova_raw_conab_agricola import kwargs, FAKE_XLS, CAPTURE, URL_MILHO, html_document

CUT = "2026-10-21T10:00:00-03:00"


def manifesto(*, milho=False):
    params = kwargs()
    if milho:
        params = kwargs(cultura="MILHO", filename="MilhoTotalSerieHist.xls",
                        url=URL_MILHO)
    return verificar_raw_conab(**params)


def livro_falso():
    workbook = LivroFalso()
    # Alinha os três indicadores na fixture: 10 mil ha * 1.000 kg/ha =
    # 10 mil toneladas. Sem alegar produtividade real para nenhum estado.
    for row in (6, 7):
        for col in range(1, 22):
            workbook.abas["Produtividade"].celulas[row][col] = 1000
    workbook.release_resources = mock.Mock()
    return workbook


def invoke(*, ready=None, **edits):
    args = {
        "manifesto_raw": manifesto(), "planilha_raw": FAKE_XLS,
        "pagina_html_raw": html_document(),
        "uf": "MT", "safra": "1980/1981", "emitido_em": CUT,
    }
    args.update(edits)
    workbook = ready if ready is not None else livro_falso()
    with mock.patch("nivon.inspecao_xls_conab_agricola._abrir_livro",
                    return_value=workbook) as decode:
        return inspecionar_xls_conab_capturado(**args), decode, workbook


class TestInspecaoXLSConab(TestCase):
    def test_tripla_fisica_selecionada_e_sem_vintage(self):
        result, decode, workbook = invoke()
        self.assertEqual(result["observacoes_total_normalizadas"], 126)
        self.assertEqual(result["status"],
                         "XLS_DECODIFICADO_E_NORMALIZADO_SEM_VINTAGE_ASOF")
        self.assertEqual(Decimal(result["tripla_fisica"]["producao_calculada_t"]),
                         Decimal("10000"))
        self.assertEqual(Decimal(result["tripla_fisica"]["residuo_fisico_t"]),
                         Decimal("0"))
        self.assertIsNone(result["tripla_fisica"]["data_publicacao"])
        self.assertIsNone(result["tripla_fisica"]["area_colhida_ha"])
        self.assertFalse(result["vintage_asof_comprovada"])
        self.assertFalse(result["habilita_publicacao"])
        self.assertTrue(result["estrutura_xls_validada"])
        self.assertTrue(result["abas_xls_lidas"])
        decode.assert_called_once_with(FAKE_XLS)
        workbook.release_resources.assert_called_once_with()

    def test_milho_total_eh_recorte_especifico(self):
        result, _, _ = invoke(manifesto_raw=manifesto(milho=True),
                              pagina_html_raw=html_document(cultura="MILHO"))
        self.assertEqual((result["cultura"], result["subdivisao_safra"]),
                         ("MILHO", "TOTAL"))
        self.assertFalse(result["habilita_backtest"])

    def test_hash_troca_de_bytes_bloqueada_antes_do_parser(self):
        changed = FAKE_XLS[:-1] + b"\1"
        with self.assertRaisesRegex(ErroLeituraXLSConab, "SHA"):
            invoke(planilha_raw=changed)

    def test_tamanho_manifesto_alterado_bloqueado(self):
        m = manifesto()
        m["tamanho_xls_bytes"] += 1
        with self.assertRaisesRegex(ErroLeituraXLSConab, "tamanho"):
            invoke(manifesto_raw=m)

    def test_adulteracao_do_gate_pit_bloqueada(self):
        for field in ("estrutura_xls_validada", "vintage_asof_comprovada",
                      "habilita_backtest", "habilita_treino",
                      "habilita_publicacao"):
            with self.subTest(field=field):
                m = manifesto()
                m[field] = True
                with self.assertRaisesRegex(ErroLeituraXLSConab, "gate"):
                    invoke(manifesto_raw=m)

    def test_adulteracao_da_edicao_bloqueada(self):
        m = manifesto()
        m["snapshot_meta"]["edicao_id"] = "CONAB_2026_10_15"
        with self.assertRaisesRegex(ErroLeituraXLSConab, "edição"):
            invoke(manifesto_raw=m)

    def test_nao_aceita_uf_ou_ano_ambiguous(self):
        for changes in ({"uf": "XX"}, {"safra": "1980/81"},
                        {"safra": "1980/1983"}, {"safra": None}):
            with self.subTest(changes=changes):
                with self.assertRaises(ErroLeituraXLSConab):
                    invoke(**changes)

    def test_ausencia_da_producao_na_safra_bloqueia_tripla(self):
        livro = livro_falso()
        livro.abas["Produção"].celulas[6][1] = ""
        with self.assertRaisesRegex(ErroLeituraXLSConab, "tripla"):
            invoke(ready=livro)
        livro.release_resources.assert_called_once()

    def test_unidade_incompativel_rejeita_e_fecha_workbook(self):
        livro = livro_falso()
        livro.abas["Área"].celulas[4][0] = "Em sacas"
        with self.assertRaisesRegex(ErroLeituraXLSConab, "XLS não validado"):
            invoke(ready=livro)
        livro.release_resources.assert_called_once()

    def test_aba_extra_bloqueada(self):
        livro = livro_falso()
        livro.abas["ESCONDIDA"] = livro.abas["Área"]
        with self.assertRaisesRegex(ErroLeituraXLSConab, "abas XLS"):
            invoke(ready=livro)

    def test_limite_de_linhas_excessivo_bloqueado(self):
        livro = livro_falso()
        livro.abas["Área"].nrows = 500000
        with self.assertRaisesRegex(ErroLeituraXLSConab, "limites estruturais"):
            invoke(ready=livro)
        livro.release_resources.assert_called_once()

    def test_parser_corrompido_bloqueia_saida(self):
        with mock.patch("nivon.inspecao_xls_conab_agricola._abrir_livro",
                        side_effect=ValueError("synthetic broken OLE")):
            with self.assertRaisesRegex(ErroLeituraXLSConab, "parser XLS falhou"):
                inspecionar_xls_conab_capturado(
                    manifesto_raw=manifesto(), planilha_raw=FAKE_XLS,
                    pagina_html_raw=html_document(),
                    uf="MT", safra="1980/1981", emitido_em=CUT)

    def test_dependencia_xlrd_ausente_falha_fechada(self):
        with mock.patch("nivon.inspecao_xls_conab_agricola._abrir_livro",
                        side_effect=ErroLeituraXLSConab("xlrd ausente")):
            with self.assertRaisesRegex(ErroLeituraXLSConab, "xlrd ausente"):
                inspecionar_xls_conab_capturado(
                    manifesto_raw=manifesto(), planilha_raw=FAKE_XLS,
                    pagina_html_raw=html_document(),
                    uf="MT", safra="1980/1981", emitido_em=CUT)

    def test_coleta_original_divergente_rejeitada(self):
        m = manifesto()
        m["snapshot_meta"]["coletado_em"] = "2026-10-21T14:00:00Z"
        with self.assertRaisesRegex(ErroLeituraXLSConab, "coleta"):
            invoke(manifesto_raw=m)

    def test_html_trocado_mesmo_url_rejeita_manifesto(self):
        # Mesmo URL, mas bytes do HTML distintos dos que originaram o SHA.
        altered = html_document().replace(b"</body>", b" \n</body>")
        with self.assertRaisesRegex(ErroLeituraXLSConab, "manifesto difere"):
            invoke(pagina_html_raw=altered)

    def test_html_de_milho_com_manifesto_soja_rejeitado(self):
        with self.assertRaisesRegex(ErroLeituraXLSConab, "proveniência"):
            invoke(pagina_html_raw=html_document(cultura="MILHO"))

    def test_url_do_manifesto_alterada_nao_engana_inspecao(self):
        m = manifesto()
        m["url_documento"] = "https://www.gov.br/conab/arquivos/falso.xls"
        with self.assertRaisesRegex(ErroLeituraXLSConab, "proveniência"):
            invoke(manifesto_raw=m)

    def test_html_ausente_rejeitado_antes_do_parser(self):
        with mock.patch("nivon.inspecao_xls_conab_agricola._abrir_livro") as dec:
            with self.assertRaisesRegex(ErroLeituraXLSConab, "proveniência"):
                invoke(pagina_html_raw=b"")
            dec.assert_not_called()

    def test_nenhum_modelo_preditivo_liberado(self):
        result, _, _ = invoke()
        for key in ("habilita_backtest", "habilita_treino",
                    "habilita_publicacao", "vintage_asof_comprovada",
                    "edicao_historica_comprovada", "quantidade_realizada_comprovada"):
            self.assertIs(result[key], False)


if __name__ == "__main__":
    import unittest
    unittest.main()
