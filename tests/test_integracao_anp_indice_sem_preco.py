"""Fronteira de prova ANP: monitor de índice não é observação de preço.

Integração sintética entre os módulos da PR #8 e da PR #26, sem internet.
"""
import unittest

from nivon.anp_monitor_atualizacao import auditar_publicacoes_anp
from nivon.anp_diesel_briefing import montar_indicadores_diesel, ErroDieselBriefing

AGORA = "2026-10-20T16:00:00-03:00"
COLETA = "2026-10-20T15:00:00-03:00"
INDICE_HTML = (
    '<html><body><h1>ANP levantamento de preços semanais</h1>'
    '<a href="/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/'
    'precos/arquivos-lpc/2026/resumo_semanal_lpc_2026-10-11_2026-10-17.xlsx/view">'
    'Resumo semanal por município, diesel e gasolina</a>'
    '<p>Preços por município em XLSX.</p></body></html>'
).encode("utf-8")


class TestFronteiraANPIndiceEPreco(unittest.TestCase):
    def monitor(self):
        return auditar_publicacoes_anp(
            INDICE_HTML,
            indice_coletado_em=COLETA, gerado_em=AGORA,
        )

    def test_nova_semana_nao_prova_novo_preco(self):
        observacao = self.monitor()
        self.assertEqual(observacao["ultima_semana_linkada"]["semana_fim"], "2026-10-17")
        self.assertFalse(observacao["coleta_preco_executada"])
        self.assertFalse(observacao["publicacao_autorizada"])
        self.assertEqual(observacao["natureza"], "METADADOS_DE_INDICE_NAO_PRECOS")
        self.assertNotIn("observacoes", observacao)
        self.assertNotIn("preco_medio_revenda_rs_l", str(observacao))

    def test_indice_nao_pode_virar_indicador_publicado_mesmo_com_flags_sinteticas(self):
        monitor = self.monitor()
        with self.assertRaisesRegex(ErroDieselBriefing, "resumo não é"):
            montar_indicadores_diesel(
                monitor, gerado_em=AGORA, publicado_em=COLETA,
                dataset={"id": "ANP_PRECO_REVENDA_DIESEL",
                         "enabled": True, "collection_authorized": True,
                         "commercial_redistribution_authorized": True},
                direitos={"status": "APROVADA",
                          "evidencia_id": "DIREITOS_SINTETICOS_NAO_REAIS",
                          "layout_real_sha256": monitor["indice_sha256"],
                          "operacoes": ["LEITURA", "COLETA", "ARMAZENAMENTO",
                                        "PUBLICACAO_DERIVADA"]},
                layout_homologado=True,
            )

    def test_alteracao_html_nao_equivale_nova_semana(self):
        atual = self.monitor()
        alterado = auditar_publicacoes_anp(
            INDICE_HTML.replace(b"<p>", b"<p class='novo'>"),
            indice_coletado_em=COLETA, gerado_em=AGORA,
            indice_anterior_sha256=atual["indice_sha256"],
            semanas_anteriormente_observadas=frozenset({"2026-10-17"}),
        )
        self.assertEqual(alterado["novas_competencias_observadas"], [])
        self.assertIn("HTML_ALTERADO_SEM_NOVA_SEMANA_VERIFICADA", alterado["alertas"])
        self.assertFalse(alterado["publicacao_autorizada"])


if __name__ == "__main__":
    unittest.main()
