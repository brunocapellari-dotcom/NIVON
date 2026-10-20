"""Regressões pós-auditoria para frescor e corredores do briefing (sem rede)."""
import unittest

from nivon.briefing_composto import montar_briefing

AGORA = "2026-10-20T09:00:00-03:00"
FONTES = {
    "TESTE": {
        "status_direitos": "APROVADA",
        "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"],
    }
}


def indicador(secao, referencia):
    return {
        "fonte_id": "TESTE", "secao": secao, "titulo": "Indicador de teste",
        "valor": "100,00", "fonte": "Fonte sintética",
        "referencia": referencia,
    }


class TestRegressaoBriefingPosAuditoria(unittest.TestCase):
    def gerar(self, *, indicadores=None, fretes=None):
        return montar_briefing(
            noticias=[], fontes=FONTES, data=AGORA,
            indicadores=indicadores or [], fretes=fretes,
        )

    def test_cotacao_de_90_dias_nao_pode_entrar_como_atual(self):
        r = self.gerar(indicadores=[
            indicador("BOLSAS", "2026-07-22T17:00:00-03:00")])
        self.assertEqual(r["indicadores_incluidos"], 0)
        self.assertNotIn("Indicador de teste", r["texto"])
        self.assertTrue(any("indicador vencido" in e["motivo"]
                            for e in r["rejeicoes"]))

    def test_indicador_recente_com_direitos_permitido(self):
        r = self.gerar(indicadores=[
            indicador("CAMBIO", "2026-10-19T17:00:00-03:00")])
        self.assertEqual(r["indicadores_incluidos"], 1)
        self.assertIn("Indicador de teste", r["texto"])

    def test_indicador_portuario_de_2025_nao_vira_movimento_atual(self):
        r = self.gerar(indicadores=[
            indicador("PORTOS", "2025-10-20T08:00:00-03:00")])
        self.assertEqual(r["indicadores_incluidos"], 0)

    def test_sorriso_dom_aquino_aceito_com_registro_autorizado(self):
        # O contrato legado ainda é municipal: sua substituição por identidade
        # de ponto de embarque / transportadora depende da integração do módulo.
        r = self.gerar(fretes=[{
            "fonte_id": "TESTE", "origem": "Sorriso", "uf_origem": "MT",
            "destino": "Dom Aquino", "uf_destino": "MT",
            "valor_rs_t": 165.0, "referencia": AGORA,
            "tipo": "FRETE_ANUNCIADO",
        }])
        self.assertEqual(r["fretes_incluidos"], 1)
        self.assertIn("SORRISO/MT → DOM AQUINO/MT", r["texto"])
        self.assertFalse(any(e["tipo"] == "FRETE"
                             for e in r["rejeicoes"]))


if __name__ == "__main__":
    unittest.main()
