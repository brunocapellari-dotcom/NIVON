import unittest
from nivon.entrega_whatsapp import (
    preparar_template, enviar_cloud_api, ErroEnvio,
)


class TestCanalWhatsApp(unittest.TestCase):
    def preparar(self, **changes):
        p=dict(destino="5566999999999",template="nivon_briefing_diario",
               resumo="O Nivon reuniu as principais mudanças do agronegócio.",
               link="https://nivon.example/briefings/2026-10-19",
               gerado_em="2026-10-19T07:00:00-03:00",
               opt_in_registrado=True,template_aprovado=True)
        p.update(changes)
        return preparar_template(**p)

    def test_idempotencia_mesmo_briefing(self):
        a=self.preparar()
        b=self.preparar()
        self.assertEqual(a["idempotency_key"],b["idempotency_key"])
        self.assertEqual(a["estado"],"PREPARADO_NAO_ENVIADO")

    def test_sem_optin_nao_cria(self):
        with self.assertRaises(ErroEnvio):
            self.preparar(opt_in_registrado=False)

    def test_sem_template_aprovado_nao_cria(self):
        with self.assertRaises(ErroEnvio):
            self.preparar(template_aprovado=False)

    def test_envio_nao_autorizado_nao_chama_rede(self):
        def forbidden(*args,**kwargs):
            raise AssertionError("rede não deve ser chamada")
        with self.assertRaises(PermissionError):
            enviar_cloud_api(self.preparar(),phone_number_id="1234567890",
                             abridor=forbidden)

    def test_url_http_nao_aceita(self):
        with self.assertRaises(ErroEnvio):
            self.preparar(link="http://localhost/briefing")

    def test_data_sem_timezone_nao_aceita(self):
        with self.assertRaises(ValueError):
            self.preparar(gerado_em="2026-10-19T07:00:00")


if __name__=="__main__":
    unittest.main()
