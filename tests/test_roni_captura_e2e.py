"""Testa um único ciclo transporte HTTPS fake -> parser -> RAW -> DB -> cache.

Não acessa internet em CI e não substitui o teste pontual da fonte real.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest
from nivon.noaa_roni import SEASONS, ENDPOINT_OFICIAL, ErroRONI
from nivon.roni_captura_manual import capturar_roni_manual
from nivon.roni_store import abrir_arquivo_roni, panorama_local_roni, consultar_arquivo_roni


def _ascii(last_year=1952, revised=False):
    lines = ["SEAS YR ANOM"]
    for y in range(1950, last_year + 1):
        for month, name in enumerate(SEASONS, 1):
            x = -0.8 if revised and y == 1951 and month == 3 else 0.1
            lines.append(f"{name} {y} {x:.2f}")
    return ("\n".join(lines) + "\n").encode("ascii")


class Resp:
    def __init__(self, payload, *, status=200, mime="text/plain",
                 url=ENDPOINT_OFICIAL):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": mime,
                        "ETag": "W/\"roni-fixture\"",
                        "Last-Modified": "Tue, 20 Oct 2026 15:00:00 GMT"}
        self.url = url
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def geturl(self): return self.url
    def read(self, n): return self.payload[:n]


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = 0
    def open(self, request, timeout):
        self.calls += 1
        if (request.get_method() != "GET" or
                request.full_url != ENDPOINT_OFICIAL or not 1 <= timeout <= 25):
            raise AssertionError("HTTP request is not the approved NOAA RONI GET")
        return self.response


class TestCapturaManualRONIE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = abrir_arquivo_roni(self.folder / "roni.sqlite")
        self.addCleanup(self.db.close)
        self.raw = self.folder / "raw"

    def call(self, **args):
        defaults = dict(
            db=self.db, raw_dir=self.raw,
            autorizar_http=True,
            autorizacoes=frozenset({"COLETA", "ARMAZENAMENTO"}),
            evidencia_direitos="REFERENCIA_POLITICA_PUBLICA_NOAA_EXEMPLO_NAO_AUDITADO",
            transporte=Opener(Resp(_ascii())),
        )
        defaults.update(args)
        return capturar_roni_manual(**defaults)

    def test_pipeline_http_unico_guarda_raw_e_usa_cache(self):
        trans = Opener(Resp(_ascii()))
        result = self.call(transporte=trans)
        self.assertEqual(trans.calls, 1)
        self.assertEqual(result["estado_captura"],
                         "HTTPS_PUBLICO_UMA_REQUISICAO_SEM_HOMOLOGACAO")
        self.assertEqual(result["competencias_novas"], 36)
        self.assertEqual(result["resposta_sha256"],
                         hashlib.sha256(_ascii()).hexdigest())
        self.assertTrue((self.raw / (result["sha256"] + ".ascii")).is_file())
        self.assertFalse(result["homologado"])
        self.assertFalse(result["direitos_de_redistribuicao_aprovados"])
        again = self.call(transporte=trans)
        self.assertEqual(again["estado"], "CACHE_LOCAL_NENHUMA_REQUISICAO")
        self.assertEqual(again["requisições_http"], 0)
        self.assertEqual(trans.calls, 1)
        self.assertEqual(
            panorama_local_roni(self.db, raw_dir=self.raw,
                                 classe="EXTERNO_NAO_HOMOLOGADO")["total_edicoes"], 1)
        past = consultar_arquivo_roni(
            self.db, raw_dir=self.raw, classe="EXTERNO_NAO_HOMOLOGADO",
            corte_em="2026-10-19T10:00:00Z")
        self.assertEqual(past["estado"], "SEM_SNAPSHOT_CONHECIDO_ASOF")

    def test_nova_edicao_exige_revisao_explicita_e_preserva_original(self):
        old = self.call()
        trans = Opener(Resp(_ascii(1953, revised=True)))
        newest = self.call(transporte=trans, confirmar_revisao=True)
        self.assertEqual(trans.calls, 1)
        self.assertEqual(newest["estado"], "NOVA_EDICAO_COM_REVISÕES")
        self.assertEqual(newest["competencias_revisadas"], 1)
        self.assertEqual(newest["competencias_novas"], 12)
        self.assertTrue((self.raw / (old["sha256"] + ".ascii")).is_file())
        self.assertTrue((self.raw / (newest["sha256"] + ".ascii")).is_file())

    def test_sem_licenca_ou_optin_nunca_abre_rede(self):
        trans = Opener(Resp(_ascii()))
        for attrs in (
            {"autorizar_http": False},
            {"autorizacoes": frozenset({"COLETA"})},
            {"evidencia_direitos": "x"},
        ):
            with self.subTest(attrs=attrs), self.assertRaises(PermissionError):
                self.call(transporte=trans, **attrs)
        self.assertEqual(trans.calls, 0)

    def test_redirect_mime_e_http_status_sao_bloqueados(self):
        for resp in (
            Resp(_ascii(), url="https://evil.example/roni.txt"),
            Resp(_ascii(), mime="text/html"),
            Resp(_ascii(), status=302),
            Resp(_ascii() + b" " * 120001),
        ):
            with self.subTest(resp=resp.headers), self.assertRaises(ErroRONI):
                self.call(transporte=Opener(resp))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM roni_snapshots").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
