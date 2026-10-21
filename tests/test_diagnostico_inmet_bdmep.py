"""Falhas reais simuladas do BDMEP: somente categorias estáticas sem segredo."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from nivon.inmet_bdmep import (
    ErroBDMEP, ErroBDMEPDiagnostico, receber_bdmep,
)
from nivon.acessos_smoke_privado import executar


URL = "https://bdmep.inmet.gov.br/$2a$10$" + "A" * 53 + ".zip"


class Transport:
    def __init__(self, *, code=None, failure=None, payload=b""):
        self.code, self.failure, self.payload = code, failure, payload

    def open(self, request, timeout):
        if self.code is not None:
            # A exceção upstream inclui o URL sensível: nunca serializá-la.
            raise HTTPError(request.full_url, self.code, request.full_url, {}, None)
        if self.failure is not None:
            raise URLError(self.failure)
        return Resposta(self.payload)


class Resposta:
    status = 200

    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.stream.read(size)


class TestBDMEPDiagnosticoSeguro(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dest = Path(temp.name)

    def _executar(self, transport):
        return receber_bdmep(pasta_privada=self.dest, habilitar_rede=True,
                             url=URL, transporte=transport)

    def test_http_codes_retorna_somente_categoria_sanitizada(self):
        cases = {
            301: "REDIRECIONAMENTO_BDMEP_BLOQUEADO",
            302: "REDIRECIONAMENTO_BDMEP_BLOQUEADO",
            403: "ACESSO_BDMEP_RECUSADO",
            404: "RECURSO_BDMEP_NAO_ENCONTRADO",
            410: "RECURSO_BDMEP_NAO_ENCONTRADO",
            429: "LIMITE_BDMEP_ATINGIDO",
            503: "SERVICO_BDMEP_INDISPONIVEL",
            418: "RESPOSTA_HTTP_BDMEP_INESPERADA",
        }
        for code, expected in cases.items():
            with self.subTest(http=code):
                with self.assertRaises(ErroBDMEPDiagnostico) as c:
                    self._executar(Transport(code=code))
                self.assertEqual(c.exception.codigo, expected)
                self.assertNotIn(URL, str(c.exception))
                self.assertNotIn("$2a$", str(c.exception))
                self.assertFalse(list(self.dest.iterdir()))

    def test_falha_transporte_nao_imprime_host_ou_url(self):
        with self.assertRaises(ErroBDMEPDiagnostico) as c:
            self._executar(Transport(failure=URL))
        self.assertEqual(c.exception.codigo, "TRANSPORTE_BDMEP_NAO_VALIDADO")
        self.assertNotIn(URL, str(c.exception))
        self.assertFalse(list(self.dest.iterdir()))

    def test_200_nao_e_zip_nao_publica_nem_preserva_arquivo(self):
        with self.assertRaises(ErroBDMEPDiagnostico) as c:
            self._executar(Transport(payload=b"<html>not a zip</html>"))
        self.assertEqual(c.exception.codigo, "ZIP_BDMEP_REJEITADO")
        self.assertFalse(list(self.dest.iterdir()))

    def test_smoke_usa_codigo_sem_exportar_url_ou_exception(self):
        with (patch.dict(os.environ, {
            "NIVON_INMET_BDMEP_URL": URL,
            "NIVON_INMET_DIRETORIO_PRIVADO": str(self.dest),
        }), patch("nivon.inmet_bdmep.receber_bdmep",
                  side_effect=ErroBDMEPDiagnostico("ACESSO_BDMEP_RECUSADO"))):
            r = executar("inmet", habilitar_rede=True)
        self.assertEqual(r["estado"], "ACESSO_BDMEP_RECUSADO")
        self.assertFalse(r["homologado"])
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["coleta_agendada"])
        self.assertNotIn(URL, json.dumps(r))

    def test_nao_tenta_rede_por_padrao(self):
        with patch("nivon.inmet_bdmep.receber_bdmep",
                   side_effect=AssertionError("rede tentada")):
            r = executar("inmet")
        self.assertEqual(r["estado"], "REDE_DESATIVADA")

    def test_recusa_categoria_nao_allowlisted(self):
        with self.assertRaises(ValueError):
            ErroBDMEPDiagnostico(URL)
        self.assertTrue(issubclass(ErroBDMEPDiagnostico, ErroBDMEP))


if __name__ == "__main__":
    unittest.main()
