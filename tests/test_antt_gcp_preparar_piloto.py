"""Teste do plano read-only de carga real ANTT no GCP, sem credenciais."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nivon.antt_bigquery import DestinoBQ, _FIELDS
from nivon.antt_gcp_preparar_piloto import preparar_piloto
from nivon.transporte_multimodal import ErroTransporte

CSV = (
    "Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;"
    "Estacao_Destino;UF_Destino;TU;TKU\n"
    "02_26;RMO;Soja;Rondonopolis;MT;Santos;SP;33.420;28.774.620\n"
).encode()
URL = (
    "https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/"
    "resource/c2854ec9-1cc5-4554-a1ae-96c5f37b5df6/download/"
    "producao_origem_destino_2026.csv"
)


def preparar_staging(pasta):
    sha = hashlib.sha256(CSV).hexdigest()
    (pasta / "antt-od-2026.csv").write_bytes(CSV)
    (pasta / "manifesto-antt.json").write_text(json.dumps({
        "formato": "nivon-antt-staging-v1",
        "anos": {"2026": {
            "status": "STAGING_NAO_HOMOLOGADO", "url": URL,
            "verificado_utc": "2026-10-23T12:00:00Z",
            "competencia_maxima": "2026-02", "registros": 1,
            "sha256": sha,
        }},
    }), encoding="utf-8")
    return sha


class Missing(Exception):
    pass


class ClienteBQ:
    def __init__(self, *, existe=False, regiao="southamerica-east1"):
        self.existe = existe
        self.regiao = regiao
        self.acessos = []
    def get_dataset(self, key):
        self.acessos.append(("get_dataset", key))
        return SimpleNamespace(location=self.regiao, project="nivon-data", dataset_id="nivon_raw")
    def get_table(self, key):
        self.acessos.append(("get_table", key))
        if not self.existe:
            raise Missing()
        schema = [SimpleNamespace(name=k, field_type=v) for k,v in _FIELDS.items()]
        return SimpleNamespace(schema=schema, time_partitioning=SimpleNamespace(field="data_referencia"))
    def __getattr__(self, n):
        raise AssertionError("operação inesperada no BigQuery: " + n)


class ClienteGCS:
    def __init__(self, *, existe=False, sha=None, regiao="southamerica-east1"):
        self.existe = existe
        self.sha = sha
        self.regiao = regiao
        self.acessos = []
    def get_bucket(self, key):
        self.acessos.append(("get_bucket", key))
        return self
    @property
    def location(self): return self.regiao
    @property
    def name(self): return "nivon-data-raw-2026"
    def get_blob(self, key):
        self.acessos.append(("get_blob", key))
        if not self.existe: return None
        return SimpleNamespace(metadata={"sha256": self.sha})
    def __getattr__(self, n):
        raise AssertionError("operação inesperada no GCS: " + n)


class TestPreparo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.pasta = Path(self.td.name)
        self.sha = preparar_staging(self.pasta)
        self.destino = DestinoBQ("nivon-data", "nivon_raw")
        self.bucket = "nivon-data-raw-2026"

    def tearDown(self):
        self.td.cleanup()

    def executar(self, bq=None, gcs=None):
        return preparar_piloto(
            self.pasta, ano=2026, destino=self.destino, bucket=self.bucket,
            cliente_bq=bq or ClienteBQ(), cliente_gcs=gcs or ClienteGCS(),
            tipo_not_found=Missing)

    def test_novo_dataset_existente_tabela_ausente(self):
        bq, gcs = ClienteBQ(), ClienteGCS()
        r = self.executar(bq, gcs)
        self.assertEqual(r["estado"], "PLANO_VALIDADO_READ_ONLY_SEM_CARGA")
        self.assertTrue(r["bigquery_bootstrap_necessario"])
        self.assertFalse(r["bigquery_tabela_existe"])
        self.assertFalse(r["gcs_objeto_ja_arquivado"])
        self.assertEqual(r["linhas_ferroviarias"], 1)
        self.assertEqual(r["arquivo_sha256"], self.sha)
        self.assertEqual(r["toneladas_uteis_declaradas_no_arquivo"], "33420")
        self.assertEqual(r["gravacoes_realizadas"], 0)
        self.assertEqual(r["jobs_bigquery_criados"], 0)
        self.assertEqual(len(bq.acessos), 2)
        self.assertEqual(len(gcs.acessos), 2)

    def test_repeticao_objeto_e_tabela_ja_existentes(self):
        r = self.executar(ClienteBQ(existe=True), ClienteGCS(existe=True, sha=self.sha))
        self.assertTrue(r["gcs_objeto_ja_arquivado"])
        self.assertFalse(r["bigquery_bootstrap_necessario"])
        self.assertEqual(r["localizacao"], "southamerica-east1")

    def test_fonte_violada_bloqueia_antes_de_api(self):
        (self.pasta / "antt-od-2026.csv").write_bytes(CSV + b"ALTERADO")
        bq = ClienteBQ()
        with self.assertRaises(ErroTransporte):
            self.executar(bq, ClienteGCS())
        self.assertEqual(bq.acessos, [])

    def test_regiao_incompatibilidade_bloqueada(self):
        with self.assertRaisesRegex(ErroTransporte, "regioes"):
            self.executar(ClienteBQ(regiao="US"), ClienteGCS())

    def test_objeto_existente_sha_errado_bloqueia(self):
        with self.assertRaisesRegex(ErroTransporte, "conflitante"):
            self.executar(ClienteBQ(), ClienteGCS(existe=True, sha="0" * 64))

    def test_teto_de_bytes_impede_inspecao_cloud(self):
        bq = ClienteBQ()
        with patch("nivon.antt_gcp_preparar_piloto.MAX_BYTES_PILOTO", 10):
            with self.assertRaisesRegex(ErroTransporte, "limite"):
                self.executar(bq, ClienteGCS())
        self.assertEqual(bq.acessos, [])

    def test_credenciais_nao_sao_recebidas_com_apenas_um_cliente(self):
        with self.assertRaisesRegex(ErroTransporte, "dois clientes"):
            preparar_piloto(self.pasta, ano=2026, destino=self.destino,
                           bucket=self.bucket, cliente_bq=ClienteBQ())


if __name__ == "__main__":
    unittest.main()
