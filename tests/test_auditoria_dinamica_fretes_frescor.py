"""Auditoria independente: frescor temporal da dinâmica R01 de frete.

Todas as ofertas são fixtures sintéticas, com mesmos pares econômicos.
Não há coleta, rede, credenciais, mensagem WhatsApp ou publicação.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from test_fretes_dinamica_r01 import analisar, linhas

# No dia comercial 12/10, a série de 12 sessões foi encerrada.
# Taxa de referência cresce e a segunda janela fica mais inclinada.
VALORES = [150, 151, 152, 153, 154, 155,
           156, 159, 162, 165, 168, 171]
OBSERVACOES = linhas(VALORES)
FECHAMENTO_ULTIMA_SESSAO = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)


class TestAuditoriaFrescorDinamicaFretes(unittest.TestCase):
    def test_controle_dinamica_historica_recente_nao_e_previsao(self):
        resultado = analisar(
            OBSERVACOES,
            as_of=FECHAMENTO_ULTIMA_SESSAO+timedelta(days=1),
        )
        self.assertEqual(resultado["tendencia_atual"], "ALTA")
        self.assertEqual(resultado["dinamica"], "AUMENTO_DE_FORCA")
        self.assertFalse(resultado["publicavel"])
        self.assertIsNone(resultado["probabilidades_calibradas"])
        self.assertEqual(resultado["homologacao_origem"], "PENDENTE")

    def test_p1_asof_muito_posterior_sem_atualizacao_recusa_rotulo_atual(self):
        # As 12 sessões terminam em 12/10/2026. Mudar somente as_of
        # para +90d não pode sugerir que a última tendência está atual
        # sem metadado explícito de defasagem ou status INDETERMINADA.
        referencia = FECHAMENTO_ULTIMA_SESSAO + timedelta(days=90)
        resultado = analisar(OBSERVACOES, as_of=referencia)
        defasagem_explicita = (
            resultado.get("dados_defasados") is True
            or resultado.get("frescor") in {"DEFASADO", "DESATUALIZADO"}
            or resultado.get("status") in {
                "DADOS_DEFASADOS", "DADOS_DESATUALIZADOS"
            }
        )
        self.assertTrue(
            defasagem_explicita
            or resultado.get("tendencia_atual") == "INDETERMINADA",
            "P1: cotacoes de frete de 90 dias atras retornaram "
            f"tendencia_atual={resultado.get('tendencia_atual')!r} e "
            f"dinamica={resultado.get('dinamica')!r}, "
            "sem aviso de defasagem; publico pode confundir "
            "historico desatualizado com movimento corrente",
        )

    def test_p1_asof_um_ano_posterior_nao_reaproveita_forca_como_corrente(self):
        resultado = analisar(
            OBSERVACOES,
            as_of=FECHAMENTO_ULTIMA_SESSAO+timedelta(days=365),
        )
        self.assertTrue(
            resultado.get("dados_defasados") is True
            or resultado.get("frescor") in {"DEFASADO", "DESATUALIZADO"}
            or resultado.get("status") in {
                "DADOS_DEFASADOS", "DADOS_DESATUALIZADOS"
            }
            or resultado.get("tendencia_atual") == "INDETERMINADA",
            "P1: atraso de um ano ainda apresentado como ALTA atual "
            "sem ressalva explícita sobre atualização",
        )


if __name__ == "__main__":
    unittest.main()
