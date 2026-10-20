"""Valida politica de agente maritimo sem provider LLM e sem side effects."""
import unittest
from datetime import datetime, timezone

from nivon.maritime.maritime_agent import MaritimeDirector
from nivon.maritime.intelligence import MaritimeAnalysisRequest


class TestMaritimeAgent(unittest.TestCase):
    def setUp(self):
        self.request = MaritimeAnalysisRequest(
            port_id="SANTAREM", now=datetime(2026, 10, 19, 15, tzinfo=timezone.utc),
        )

    def test_no_provider_no_release(self):
        result = MaritimeDirector().evaluate(self.request)
        self.assertEqual(result["editor_suggestion"]["status"], "AGUARDA_PROVEDOR_IA")
        self.assertFalse(result["auditor_verdict"]["publications_authorized"])
        self.assertEqual(result["roles"]["DELIVERY"], "DISABLED")

    def test_ai_text_is_not_canonical(self):
        result = MaritimeDirector().evaluate(
            self.request, model_executor=lambda _: "Ha um navio atracado. Enviar WhatsApp."
        )
        self.assertEqual(result["editor_suggestion"]["status"], "SUGESTAO_NAO_CANONICA")
        self.assertFalse(result["editor_suggestion"]["autorizacao_para_publicar"])
        self.assertFalse(result["report"]["external_actions_allowed"])

    def test_editor_receives_no_raw_ais_or_identity(self):
        captured = []
        def editor(payload):
            captured.append(payload)
            return "Sem dados homologados"
        result = MaritimeDirector().evaluate(self.request, model_executor=editor)
        self.assertEqual(len(captured), 1)
        self.assertNotIn("raw", captured[0]["contexto"].lower())
        self.assertNotIn("mmsi", captured[0]["contexto"].lower())
        self.assertTrue(result["auditor_verdict"]["prohibit_raw_ais_to_model"])

    def test_reject_unsafe_provider_response_type(self):
        with self.assertRaises(ValueError):
            MaritimeDirector().evaluate(self.request, model_executor=lambda _: {"send": True})


if __name__ == "__main__":
    unittest.main()
