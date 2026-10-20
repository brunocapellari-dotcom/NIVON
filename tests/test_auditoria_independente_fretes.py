"""Testes independentes e adversariais: não são homologação operacional.

Estes testes expressam o contrato editorial P0. Devem FALHAR na versão
base da PR #13 até o código de produção ser corrigido. Nenhum teste faz rede.
"""
from __future__ import annotations

import unittest

from nivon.briefing_composto import montar_briefing


AGORA = "2026-10-20T09:00:00-03:00"
FONTE_AUTORIZADA = {
    "EXEMPLO": {
        "status_direitos": "APROVADA",
        "operacoes": ["LEITURA", "PUBLICACAO_DERIVADA"],
    }
}


def frete(**alteracoes):
    # Entrada totalmente fictícia para demonstrar controles, nunca cotação real.
    registro = {
        "fonte_id": "EXEMPLO",
        "origem": "Sorriso",
        "uf_origem": "MT",
        "destino": "Dom Aquino",
        "uf_destino": "MT",
        "pickup_entity_id": "FAZENDA_SINTETICA_001",
        "transportadora": "TRANSPORTADORA_SINTETICA_001",
        "valor_rs_t": 165.0,
        "referencia": "2026-10-20T08:00:00-03:00",
        "tipo": "FRETE_ANUNCIADO",
    }
    registro.update(alteracoes)
    return registro


def gerar(registro, fontes=None):
    return montar_briefing(
        noticias=[],
        fontes=fontes if fontes is not None else FONTE_AUTORIZADA,
        data=AGORA,
        indicadores=[],
        fretes=[registro],
    )


class TestAuditoriaIndependenteFretes(unittest.TestCase):
    def test_controle_publica_somente_registro_valido_e_identificado(self):
        """Caso-controle positivo para não criar bloqueio total artificial."""
        resultado = gerar(frete())
        self.assertEqual(resultado["fretes_incluidos"], 1)

    def test_p0_rejeita_frete_com_referencia_futura(self):
        resultado = gerar(frete(referencia="2026-10-21T08:00:00-03:00"))
        self.assertEqual(
            resultado["fretes_incluidos"], 0,
            "P0: referência futura não pode ser publicada como frete atual",
        )
        self.assertTrue(any(x["tipo"] == "FRETE" for x in resultado["rejeicoes"]))

    def test_p0_rejeita_frete_de_2024_em_briefing_de_2026(self):
        resultado = gerar(frete(referencia="2024-10-20T08:00:00-03:00"))
        self.assertEqual(
            resultado["fretes_incluidos"], 0,
            "P0: anúncio antigo não é cotação corrente sem política e data de validade",
        )

    def test_p0_rejeita_frete_sem_identidade_de_estabelecimento_e_transportadora(self):
        registro = frete()
        registro.pop("pickup_entity_id")
        registro.pop("transportadora")
        resultado = gerar(registro)
        self.assertEqual(
            resultado["fretes_incluidos"], 0,
            "P0: município não substitui estabelecimento e transportadora",
        )

    def test_p0_exige_direito_de_leitura_alem_de_publicacao(self):
        fontes = {
            "EXEMPLO": {
                "status_direitos": "APROVADA",
                "operacoes": ["PUBLICACAO_DERIVADA"],
            }
        }
        resultado = gerar(frete(), fontes)
        self.assertEqual(
            resultado["fretes_incluidos"], 0,
            "P0: fonte sem LEITURA não pode fornecer registros ao briefing",
        )


if __name__ == "__main__":
    unittest.main()
