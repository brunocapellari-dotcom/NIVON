"""E2E offline do registry administrativo -> autorização -> outbox -> diagnóstico.

As permissões e chaves deste arquivo são unicamente sintéticas.
Nenhuma rotina aciona WhatsApp ou serviços externos.
"""
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.registry_emissores import (
    provisionar_registro, revogar_emissor, resumo_registry, ErroRegistry,
)
from nivon.diagnostico_outbox import diagnosticar_outbox
from nivon.outbox_whatsapp import consultar_envio, ErroOutbox
from suporte_provas_outbox import (
    manifesto_teste, assinatura_administrativa, RAIZ_SINTETICA,
)


class TestRegistryE2EOffline(unittest.TestCase):
    def setUp(self):
        from test_outbox_whatsapp import TestOutboxWhatsApp
        self.f = TestOutboxWhatsApp(methodName="test_registro_idempotente_mesma_edicao")
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def _preparar(self):
        self.f.registrar()
        self.f.aprovar()

    def _revogar(self, emissor_id):
        evento = {
            "operacao": "REVOGAR", "emissor_id": emissor_id,
            "evidencia_id": "REVOGACAO_ADMINISTRATIVA_SINTETICA_2026",
        }
        return revogar_emissor(self.f.con, evento=evento,
                              assinatura=assinatura_administrativa(evento),
                              chave_raiz=RAIZ_SINTETICA)

    def test_registro_exige_admin_e_nunca_guarda_segredos(self):
        self._preparar()
        m = manifesto_teste(self.f.emissores)
        with self.assertRaisesRegex(PermissionError, "já provisionado"):
            provisionar_registro(
                self.f.con, manifesto=m,
                assinatura=assinatura_administrativa(m),
                chave_raiz=RAIZ_SINTETICA,
            )
        stats = resumo_registry(self.f.con)
        self.assertTrue(stats["apto_registry"])
        self.assertEqual(stats["ativos"], 5)
        raw = self.f.path.read_bytes()
        self.assertNotIn(RAIZ_SINTETICA, raw)
        for info in self.f.emissores.values():
            self.assertNotIn(info["chave"], raw)

    def test_signature_provisionamento_falsa_rejeitada_sem_mutar_banco(self):
        con = sqlite3.connect(":memory:")
        try:
            # Não aceitar manifesto self-signed com uma chave aleatória.
            m = {"operacao": "PROVISIONAR", "versao": 1, "emissores": []}
            with self.assertRaisesRegex(PermissionError, "assinatura"):
                provisionar_registro(
                    con, manifesto=m, assinatura="sha256=" + "0"*64,
                    chave_raiz=RAIZ_SINTETICA,
                )
            self.assertEqual(con.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='nivon_registry_root'"
            ).fetchone()[0], 0)
        finally:
            con.close()

    def test_retirar_emissor_reprova_reserva_previamente_assinada(self):
        self._preparar()
        emissor = self.f.comprovantes[2]["emissor_id"]
        resultado = self._revogar(emissor)
        self.assertEqual(resultado["estado"], "REVOGADO")
        self.assertEqual(resumo_registry(self.f.con)["ativos"], 4)
        callbacks = []
        with self.assertRaisesRegex(PermissionError, "emissor"):
            self.f.despachar(lambda *_: callbacks.append(True))
        self.assertEqual(callbacks, [])
        self.assertEqual(consultar_envio(
            self.f.con, self.f.modelo["idempotency_key"])["tentativas"], 0)
        self.f.con.close()
        self.f.con = sqlite3.connect(self.f.path)
        with self.assertRaises(PermissionError):
            self.f.despachar(lambda *_: self.fail("callback após reinício"))
        with self.assertRaisesRegex(PermissionError, "já revogado"):
            self._revogar(emissor)

    def test_revogacao_assinada_com_raiz_indevida_nao_altera_autoridade(self):
        self._preparar()
        emissor = self.f.comprovantes[1]["emissor_id"]
        evento = {
            "operacao": "REVOGAR", "emissor_id": emissor,
            "evidencia_id": "REVOGACAO_NAO_AUTORIZADA_2026",
        }
        assinatura = assinatura_administrativa(evento)
        with self.assertRaises(PermissionError):
            revogar_emissor(
                self.f.con, evento=evento, assinatura=assinatura,
                chave_raiz=b"outra_raiz_ficticia_ainda_nao_confiavel_20261022",
            )
        self.assertEqual(resumo_registry(self.f.con)["ativos"], 5)

    def test_trocar_chave_emissor_sem_admin_bloqueia(self):
        self._preparar()
        emissor = self.f.comprovantes[0]["emissor_id"]
        self.f.emissores[emissor]["chave"] = b"nova_chave_simulada_diferente_da_ancora_registrada"
        self.assertRaises(PermissionError,
                          self.f.despachar, lambda *_: self.fail("não enviar"))
        self.assertEqual(consultar_envio(
            self.f.con, self.f.modelo["idempotency_key"])["tentativas"], 0)

    def test_fluxo_completo_e_diagnostico_nao_reservam(self):
        self._preparar()
        antes = diagnosticar_outbox(self.f.con)
        self.assertEqual(antes["total"], 1)
        self.assertTrue(antes["emissores"]["apto_registry"])
        self.assertEqual(
            antes["edicoes"][0]["diagnostico"],
            "EVIDENCIAS_ESTRUTURAIS_COMPLETAS_OFFLINE")
        self.assertFalse(antes["envio_habilitado"])
        self.assertEqual(consultar_envio(
            self.f.con, self.f.modelo["idempotency_key"])["tentativas"], 0)
        # Somente callback fake, não API real, após a reserva transacional.
        chamadas = []
        def fake(_):
            chamadas.append("ficticio")
            return {"provider_message_id": "wamid.ID_FICTICIO_12345"}
        result = self.f.despachar(fake)
        self.assertEqual(result["estado"], "ACEITO_PROVEDOR")
        self.assertEqual(chamadas, ["ficticio"])
        depois = diagnosticar_outbox(self.f.con)
        self.assertIn("TENTATIVA_JA_RESERVADA_OU_FINALIZADA",
                      depois["edicoes"][0]["bloqueios"])
        self.assertFalse(depois["envio_habilitado"])
        self.assertNotIn("5566999999999", json.dumps(depois))
        self.assertNotIn("Briefing NIVON", json.dumps(depois))

    def test_diagnostico_falha_fechada_antes_de_provisionar(self):
        con = sqlite3.connect(":memory:")
        try:
            d = diagnosticar_outbox(con)
            self.assertEqual(d["estado"], "NAO_PROVISIONADA")
            self.assertFalse(d["envio_habilitado"])
            self.assertTrue(d["pendencias"])
        finally:
            con.close()

    def test_diagnostico_reconhece_optout_e_emissor_revogado(self):
        self._preparar()
        from nivon.outbox_whatsapp import revogar_destinatario
        from test_outbox_whatsapp import SEGREDO
        revogar_destinatario(
            self.f.con, destino="5566999999999",
            chave_destinatario=SEGREDO,
            evidencia_revogacao="OPT_OUT_SINTETICO_20261022",
        )
        d = diagnosticar_outbox(self.f.con)
        self.assertIn("OPT_OUT_DESTINATARIO", d["edicoes"][0]["bloqueios"])
        self._revogar(self.f.comprovantes[0]["emissor_id"])
        d = diagnosticar_outbox(self.f.con)
        self.assertIn("EMISSOR_AUSENTE_OU_REVOGADO",
                      d["edicoes"][0]["bloqueios"])

    def test_diagnostico_readonly_sqlite_persistido(self):
        self._preparar()
        con = sqlite3.connect(f"file:{self.f.path}?mode=ro", uri=True)
        try:
            d = diagnosticar_outbox(con)
            self.assertEqual(d["total"], 1)
            self.assertFalse(d["envio_habilitado"])
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
