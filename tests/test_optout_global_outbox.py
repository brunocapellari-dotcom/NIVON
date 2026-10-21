"""Regressões do opt-out global: uma edição revogada não pode ser contornada.

Tudo é offline e sintético; nenhum dado pessoal real e nenhuma rede.
"""
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.entrega_whatsapp import preparar_template
from nivon import outbox_whatsapp as outbox
from test_outbox_whatsapp import SEGREDO


class TestOptOutGlobal(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "outbox.sqlite"
        self.con = sqlite3.connect(self.path)

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def modelo(self, *, destino="5566999999999", dia="2026-10-20"):
        return preparar_template(
            destino=destino, template="nivon_briefing_diario",
            resumo="Mensagem inteiramente sintética para testes de opt-out.",
            link="https://nivon.example/briefings/" + dia,
            gerado_em=dia + "T07:00:00-03:00",
            opt_in_registrado=True, template_aprovado=True,
        )

    def registrar(self, preparado, dia):
        return outbox.registrar_edicao(
            self.con, preparado, edicao=dia, chave_destinatario=SEGREDO
        )

    def revogar(self):
        return outbox.revogar_destinatario(
            self.con, destino="5566999999999",
            chave_destinatario=SEGREDO,
            evidencia_revogacao="OPT_OUT_SINTETICO_DOC_20261021",
        )

    def test_optout_antes_de_cadastrar_impede_qualquer_edicao(self):
        self.revogar()
        with self.assertRaisesRegex(PermissionError, "opt-out"):
            self.registrar(self.modelo(), "2026-10-20")
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_envios").fetchone()[0], 0)

    def test_optout_apos_cadastrar_impede_edicao_seguinte(self):
        primeira = self.modelo()
        self.registrar(primeira, "2026-10-20")
        self.revogar()
        with self.assertRaisesRegex(PermissionError, "opt-out"):
            self.registrar(self.modelo(dia="2026-10-21"), "2026-10-21")
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_envios").fetchone()[0], 1)

    def test_bloqueio_duravel_apos_reabrir_banco_e_sem_vazar_numero(self):
        self.revogar()
        self.con.close()
        self.con = sqlite3.connect(self.path)
        with self.assertRaisesRegex(PermissionError, "opt-out"):
            self.registrar(self.modelo(dia="2026-10-22"), "2026-10-22")
        self.assertNotIn(b"5566999999999", self.path.read_bytes())
        self.assertNotIn(b"OPT_OUT_SINTETICO_DOC_20261021", self.path.read_bytes())

    def test_rotacao_de_chave_sem_migracao_nao_pode_contornar_optout(self):
        self.revogar()
        outro_segredo = b"nova_chave_sem_migracao_nao_permitida_sintetica_2026"
        novo = self.modelo(dia="2026-10-21")
        with self.assertRaisesRegex(PermissionError, "chave HMAC"):
            outbox.registrar_edicao(
                self.con, novo, edicao="2026-10-21",
                chave_destinatario=outro_segredo,
            )
        with self.assertRaisesRegex(PermissionError, "chave HMAC"):
            outbox.revogar_destinatario(
                self.con, destino="5566999999999",
                chave_destinatario=outro_segredo,
                evidencia_revogacao="OPT_OUT_COM_CHAVE_ERRADA_20261021",
            )
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM nivon_optouts_destinatario").fetchone()[0],
            1,
        )

    def test_rotacao_de_chave_bloqueada_apos_reinicializar_banco(self):
        self.revogar()
        self.con.close()
        self.con = sqlite3.connect(self.path)
        with self.assertRaisesRegex(PermissionError, "chave HMAC"):
            outbox.registrar_edicao(
                self.con, self.modelo(dia="2026-10-23"),
                edicao="2026-10-23",
                chave_destinatario=b"outra_chave_extensa_que_nao_foi_migrada_2026",
            )

    def test_optout_isola_destinatarios_e_e_idempotente(self):
        self.revogar()
        self.revogar()
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_optouts_destinatario").fetchone()[0], 1)
        outro = self.modelo(destino="5566888888888")
        r = self.registrar(outro, "2026-10-20")
        self.assertEqual(r["estado"], "PREPARADO")

    def test_autorizacao_anterior_nao_habilita_dispatch_apos_optout(self):
        # Reusa fixture de outbox já integrada para obter autorização assinada
        # num banco persistido. O próprio método de opt-out é externo ao
        # documento assinado, portanto bloqueia inclusive aprovação antiga.
        from test_outbox_whatsapp import TestOutboxWhatsApp
        fixture = TestOutboxWhatsApp(methodName="test_registro_idempotente_mesma_edicao")
        fixture.setUp()
        try:
            fixture.registrar()
            fixture.aprovar()
            outbox.revogar_destinatario(
                fixture.con, destino="5566999999999",
                chave_destinatario=SEGREDO,
                evidencia_revogacao="OPT_OUT_SINTETICO_DOC_20261021",
            )
            chamadas = []
            with self.assertRaisesRegex(PermissionError, "opt-out"):
                fixture.despachar(lambda *_: chamadas.append(True))
            self.assertEqual(chamadas, [])
            self.assertEqual(outbox.consultar_envio(
                fixture.con, fixture.modelo["idempotency_key"])["tentativas"], 0)
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
