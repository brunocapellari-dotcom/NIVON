import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nivon.antt_gcs import arquivar_gcs, nome_objeto, plano_gcs
from nivon.transporte_multimodal import ErroTransporte

URL = ("https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/"
       "resource/c2854ec9-1cc5-4554-a1ae-96c5f37b5df6/download/producao_origem_destino_2026.csv")
RAW = b"Mes_Ano;Ferrovia;TU;TKU\n01/2026;RMO;1;99\n"


class PreconditionError(Exception):
    pass


class FakeBlob:
    def __init__(self):
        self.metadata = None
        self.saved_metadata = None
        self.content = None

    def upload_from_string(self, payload, *, content_type, if_generation_match, timeout):
        if self.content is not None:
            raise PreconditionError()
        assert if_generation_match == 0
        self.content = payload
        self.saved_metadata = dict(self.metadata)

    def reload(self, *, client):
        self.metadata = self.saved_metadata


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def exists(self, *, client):
        return True

    def blob(self, obj):
        return self.blobs.setdefault(obj, FakeBlob())


class FakeClient:
    def __init__(self):
        self.obj = FakeBucket()

    def bucket(self, name):
        assert name == "nivon-dados-antt"
        return self.obj


class TestGCS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sha = hashlib.sha256(RAW).hexdigest()
        self.sha = sha
        Path(self.tmp.name, "antt-od-2026.csv").write_bytes(RAW)
        m = {"formato": "nivon-antt-staging-v1", "anos": {"2026": {
            "sha256": sha, "status": "STAGING_NAO_HOMOLOGADO",
            "url": URL, "verificado_utc": "2026-10-23T11:00:00Z"}}}
        Path(self.tmp.name, "manifesto-antt.json").write_text(json.dumps(m))

    def tearDown(self):
        self.tmp.cleanup()

    def test_sem_rede_por_padrao(self):
        result = arquivar_gcs(self.tmp.name, [2026], "nivon-dados-antt")
        self.assertEqual(result[0]["estado"], "DRY_RUN")
        self.assertTrue(result[0]["gcs_uri"].endswith(".csv"))

    def test_idempotente_e_imutavel(self):
        fake = FakeClient()
        a = arquivar_gcs(self.tmp.name, [2026], "nivon-dados-antt",
                         habilitar_escrita=True, cliente=fake,
                         precondition_error=PreconditionError)
        self.assertEqual(a[0]["estado"], "ARQUIVADO")
        b = arquivar_gcs(self.tmp.name, [2026], "nivon-dados-antt",
                         habilitar_escrita=True, cliente=fake,
                         precondition_error=PreconditionError)
        self.assertEqual(b[0]["estado"], "JA_ARQUIVADO")
        blob = next(iter(fake.obj.blobs.values()))
        self.assertEqual(blob.content, RAW)
        self.assertEqual(blob.metadata["sha256"], self.sha)

    def test_bloquear_modificacao_e_bucket_ilegal(self):
        Path(self.tmp.name, "antt-od-2026.csv").write_bytes(b"outro")
        with self.assertRaises(ErroTransporte):
            plano_gcs(self.tmp.name, [2026], "nivon-dados-antt")
        with self.assertRaises(ErroTransporte):
            nome_objeto(2026, "SHABAD")
        with self.assertRaises(ErroTransporte):
            plano_gcs(self.tmp.name, [2026], "bucket;rm -rf")


if __name__ == "__main__":
    unittest.main()
