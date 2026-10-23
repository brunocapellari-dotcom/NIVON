"""Coleta PTAX desligada por padrão; testes de rede sempre injetados."""
import unittest
from datetime import datetime, timezone, timedelta
from hashlib import sha256

from nivon.captura_ptax_http import (
    ErroCapturaPTAX, capturar_ptax_odata,
)
from nivon.ptax_plano import planejar_consultas_ptax

CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
PLANO=planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-19",fim="2026-10-20",
)[0]
RAW=(b'{"value":[{"cotacaoCompra":5.10000,"cotacaoVenda":5.10100,'
     b'"dataHoraCotacao":"2026-10-20 13:03:00"}]}')
TIME=datetime(2026,10,20,18,0,0,tzinfo=timezone.utc)


def fake(url):
    return (200, {"Content-Type":"application/json; charset=UTF-8",
                  "Content-Length":str(len(RAW)),
                  "Date":"Tue, 20 Oct 2026 18:00:00 GMT"}, RAW)


def coletar(**kw):
    return capturar_ptax_odata(
        PLANO,transporte=fake,relogio=lambda:TIME,**kw
    )


class TestCapturaPTAXHTTP(unittest.TestCase):
    def test_zero_rede_por_padrao(self):
        with self.assertRaisesRegex(PermissionError,"bloqueado"):
            capturar_ptax_odata(PLANO)

    def test_rede_exige_catalogo_e_direitos(self):
        with self.assertRaisesRegex(PermissionError,"catálogo"):
            capturar_ptax_odata(PLANO,permitir_rede=True)
        with self.assertRaisesRegex(PermissionError,"não habilitada"):
            capturar_ptax_odata(PLANO,permitir_rede=True,catalogo=CAT)

    def test_transporte_injetado_nao_simula_real(self):
        resp=coletar()
        self.assertEqual(resp["tipo"],"SINTETICO")
        self.assertEqual(resp["origem_execucao"],"TRANSPORTE_INJETADO_SINTETICO")
        self.assertEqual(resp["raw_bytes"],RAW)
        self.assertEqual(resp["raw_sha256"],sha256(RAW).hexdigest())
        self.assertEqual(resp["coletado_em"],TIME.isoformat())
        self.assertEqual(resp["verificacao"]["boletins"][0]["cotacao_compra_decimal"],
                         "5.10000")
        self.assertFalse(resp["publicavel"])

    def test_proibido_mix_rede_real_e_mock(self):
        with self.assertRaisesRegex(ErroCapturaPTAX,"sintético"):
            coletar(permitir_rede=True)

    def test_rejeitar_json_html_waf(self):
        def invalido(u):
            return 200,{"content-type":"text/html"},b"<html>WAF</html>"
        with self.assertRaisesRegex(ErroCapturaPTAX,"JSON"):
            capturar_ptax_odata(PLANO,transporte=invalido,relogio=lambda:TIME)

    def test_status_redirect_semaceitacao(self):
        with self.assertRaisesRegex(ErroCapturaPTAX,"não 200"):
            capturar_ptax_odata(PLANO,transporte=lambda u:
                (302,{"content-type":"application/json"},RAW),
                relogio=lambda:TIME)

    def test_content_length_incoerente(self):
        def invalido(u):
            return 200,{"content-type":"application/json","content-length":"5"},RAW
        with self.assertRaisesRegex(ErroCapturaPTAX,"Content-Length"):
            capturar_ptax_odata(PLANO,transporte=invalido,relogio=lambda:TIME)

    def test_header_duplicado_case_insensitive(self):
        def bad(u):
            return 200,{"Content-Type":"application/json",
                        "content-type":"application/json"},RAW
        with self.assertRaisesRegex(ErroCapturaPTAX,"duplicado"):
            capturar_ptax_odata(PLANO,transporte=bad,relogio=lambda:TIME)

    def test_content_encoding_recusado(self):
        def bad(u):
            return 200,{"content-type":"application/json",
                        "content-encoding":"gzip"},RAW
        with self.assertRaisesRegex(ErroCapturaPTAX,"compactada"):
            capturar_ptax_odata(PLANO,transporte=bad,relogio=lambda:TIME)

    def test_tamanho_limite_bloqueia(self):
        def big(u):
            return 200,{"content-type":"application/json"},b"x"*2000001
        with self.assertRaisesRegex(ErroCapturaPTAX,"limite"):
            capturar_ptax_odata(PLANO,transporte=big,relogio=lambda:TIME)

    def test_nao_deixa_cotacao_futura_ser_registrada(self):
        with self.assertRaisesRegex(Exception,"depois da captura"):
            capturar_ptax_odata(PLANO,transporte=fake,
                relogio=lambda:datetime(2026,10,20,15,0,0,tzinfo=timezone.utc))

    def test_relogio_sem_tz_ou_plano_alterado(self):
        with self.assertRaisesRegex(ErroCapturaPTAX,"relógio"):
            capturar_ptax_odata(PLANO,transporte=fake,
                relogio=lambda:datetime(2026,10,20,18,0,0))
        with self.assertRaisesRegex(ErroCapturaPTAX,"divergente"):
            capturar_ptax_odata({**PLANO,"inicio":"2026-10-18"},
                transporte=fake,relogio=lambda:TIME)

    def test_relogio_exato_usado_apos_recebimento(self):
        registro=coletar()
        self.assertEqual(registro["cabecalhos_http"]["date"],
                         "Tue, 20 Oct 2026 18:00:00 GMT")
        self.assertIsNone(registro["publicacao_oficial_em"])
        self.assertFalse(registro["fonte_http_certificada_independentemente"])


if __name__=="__main__":
    unittest.main()
