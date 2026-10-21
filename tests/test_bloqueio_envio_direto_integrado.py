"""Regressões adversariais do limite entre preparação e envio.

Não executar rede: mock registra chamadas indevidas do caminho legado.
O envio real exige outbox/autorizações independentes, não apenas flags.
"""
import unittest

from nivon.briefing_composto import (
    DireitoEntrega, ErroBriefing, montar_briefing, solicitar_entrega,
)
from nivon.agentes_nivon import CoordenadorNivon

GERACAO = "2026-10-20T09:00:00-03:00"
APROVADO = DireitoEntrega(
    destinatario_consentiu=True,
    canal_autorizado=True,
    custos_aprovados=True,
    template_aprovado=True,
)


def exemplar():
    return montar_briefing(
        noticias=[], fontes={}, data=GERACAO, indicadores=[], fretes=[],
    )


class TestNenhumEnvioDiretoSemOutbox(unittest.TestCase):
    def test_flags_positivas_nao_perfuram_outbox(self):
        chamadas = []
        resultado = solicitar_entrega(
            exemplar(), APROVADO,
            remetente=lambda *args: chamadas.append(args) or {"id": "SIMULADO"},
        )
        self.assertEqual(resultado["status"], "BLOQUEADO_ENVIO_DIRETO_SEM_OUTBOX")
        self.assertFalse(resultado["envio_realizado"])
        self.assertEqual(chamadas, [])

    def test_auditor_mock_positivo_nao_autoriza_dispatch(self):
        chamadas = []
        coordenador = CoordenadorNivon(auditor=lambda edicao: True)
        r = coordenador.executar(
            noticias=[], fontes={}, data=GERACAO, indicadores=[],
            direito_entrega=APROVADO,
            remetente=lambda *args: chamadas.append(args) or {"id": "SIMULADO"},
        )
        self.assertEqual(r["entrega"]["status"], "BLOQUEADO_ENVIO_DIRETO_SEM_OUTBOX")
        self.assertEqual(chamadas, [])

    def test_hash_desatualizado_rejeitado_antes_de_qualquer_envio(self):
        briefing = exemplar()
        briefing["texto"] += "\nAtualização sem revisão"
        chamadas = []
        with self.assertRaisesRegex(ErroBriefing, "integridade"):
            solicitar_entrega(
                briefing, APROVADO,
                remetente=lambda *args: chamadas.append(args) or {"id": "SIMULADO"},
            )
        self.assertEqual(chamadas, [])

    def test_sem_autorizacao_continua_bloqueado(self):
        chamadas = []
        r = solicitar_entrega(
            exemplar(), DireitoEntrega(),
            remetente=lambda *args: chamadas.append(args),
        )
        self.assertEqual(r["status"], "BLOQUEADO_ENTREGA")
        self.assertFalse(r["envio_realizado"])
        self.assertEqual(chamadas, [])


if __name__ == "__main__":
    unittest.main()
