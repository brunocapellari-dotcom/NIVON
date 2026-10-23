import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from nivon.antt_bigquery import DestinoBQ, montar_lote, gravar_bigquery, sql_view
from nivon.transporte_multimodal import ErroTransporte

URL = ("https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/"
       "resource/c2854ec9-1cc5-4554-a1ae-96c5f37b5df6/download/producao_origem_destino_2026.csv")
CSV = ("Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;Estacao_Destino;"
       "UF_Destino;TU;TKU\n02_26;RMO;Soja;Rondonopolis;MT;Santos;SP;33.420;28.774.620\n").encode()


def staging(path):
    Path(path, "antt-od-2026.csv").write_bytes(CSV)
    meta = {"formato": "nivon-antt-staging-v1", "anos": {
        "2026": {"url": URL, "revision_id": "r1",
                 "verificado_utc": "2026-10-23T03:33:22Z",
                 "status": "STAGING_NAO_HOMOLOGADO",
                 "sha256": hashlib.sha256(CSV).hexdigest(),
                 "registros": 1, "competencia_maxima": "2026-02"}}}
    Path(path, "manifesto-antt.json").write_text(json.dumps(meta))


class FakeSDK:
    class NotFound(Exception): pass
    class SchemaField:
        def __init__(self, name, field_type):
            self.name, self.field_type = name, field_type
    class Table:
        def __init__(self, table_id, schema):
            self.table_id, self.schema = table_id, schema
            self.time_partitioning = None
            self.clustering_fields = []
    class TimePartitioning:
        def __init__(self, type_, field):
            self.type_, self.field = type_, field
    class TimePartitioningType:
        MONTH = "MONTH"
    class ScalarQueryParameter:
        def __init__(self, name, typ, value):
            self.name, self.typ, self.value = name, typ, value
    class QueryJobConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class LoadJobConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class SourceFormat:
        NEWLINE_DELIMITED_JSON = "NEWLINE_DELIMITED_JSON"
    class WriteDisposition:
        WRITE_APPEND = "WRITE_APPEND"


class FakeClient:
    def __init__(self):
        self.table = None
        self.records = []
        self.jobs = []
        self.views = []
        self.dataset = "nivon-dados-123.transporte"

    def get_dataset(self, key):
        if key != self.dataset:
            raise ValueError("outro dataset")
        return object()

    def get_table(self, ref):
        if self.table is None:
            raise FakeSDK.NotFound()
        return self.table

    def create_table(self, table):
        self.table = table
        return table

    def query(self, sql, job_config=None):
        if sql.startswith("CREATE OR REPLACE VIEW"):
            self.views.append(sql)
            return SimpleNamespace(result=lambda: [])
        assert "WHERE ano=@ano AND arquivo_sha256=@sha" in sql
        params = {p.name: p.value for p in job_config.query_parameters}
        count = sum(x["ano"] == params["ano"] and x["arquivo_sha256"] == params["sha"]
                    for x in self.records)
        return SimpleNamespace(result=lambda: [SimpleNamespace(n=count)])

    def load_table_from_json(self, rows, ref, job_config, job_id):
        self.records.extend(rows)
        self.jobs.append(job_id)
        return SimpleNamespace(job_id=job_id, errors=None, result=lambda timeout: None)


class TestBigQuery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        staging(self.tmp.name)
        self.dest = DestinoBQ("nivon-dados-123", "transporte")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_zero_rede(self):
        resumo = gravar_bigquery(self.tmp.name, [2026], self.dest)
        self.assertEqual(resumo[0]["estado"], "DRY_RUN")
        self.assertEqual(resumo[0]["toneladas_uteis"], "33420")

    def test_schema_proveniencia_e_soma_tku(self):
        rows, meta = montar_lote(self.tmp.name, 2026)
        self.assertEqual(meta["tku_raw"], "28774620")
        self.assertEqual(rows[0]["data_referencia"], "2026-02-01")
        self.assertEqual(rows[0]["data_publicacao"], None)
        self.assertEqual(rows[0]["unidade_tku_confirmada"], False)
        self.assertEqual(len(rows[0]["linha_id"]), 64)
        self.assertEqual(rows[0]["natureza_tu"], "OBSERVADO_DECLARADO")

    def test_idempotencia_e_view_versao(self):
        client = FakeClient()
        first = gravar_bigquery(self.tmp.name, [2026], self.dest,
                               habilitar_escrita=True, permitir_criar_tabela=True,
                               cliente=client, sdk=FakeSDK)
        self.assertEqual(first[0]["estado"], "CARREGADO_PENDENTE_CONCILIACAO")
        self.assertEqual(len(client.records), 1)
        self.assertEqual(len(client.jobs), 1)
        second = gravar_bigquery(self.tmp.name, [2026], self.dest,
                                habilitar_escrita=True, cliente=client, sdk=FakeSDK)
        self.assertEqual(second[0]["estado"], "SEM_MUDANCA")
        self.assertEqual(len(client.records), 1)
        self.assertEqual(len(client.jobs), 1)
        self.assertEqual(client.table.time_partitioning.field, "data_referencia")
        self.assertIn("QUALIFY ROW_NUMBER()", client.views[0])

    def test_tabela_nova_exige_bootstrap_aprovado(self):
        client=FakeClient()
        with self.assertRaisesRegex(ErroTransporte, "bootstrap explicito"):
            gravar_bigquery(self.tmp.name, [2026], self.dest,
                           habilitar_escrita=True, cliente=client, sdk=FakeSDK)
        self.assertIsNone(client.table)
        self.assertEqual(client.records, [])

    def test_manifesto_violado_bloqueia(self):
        Path(self.tmp.name, "antt-od-2026.csv").write_bytes(CSV + b"X")
        with self.assertRaises(ErroTransporte):
            montar_lote(self.tmp.name, 2026)

    def test_identificadores_nao_escapam_sql(self):
        with self.assertRaises(ErroTransporte):
            DestinoBQ("nivon-dados-123", "public; DROP TABLE usuarios")
        with self.assertRaises(ErroTransporte):
            DestinoBQ("https://example.com", "transporte")
        self.assertIn(self.dest.tabela_completa, sql_view(self.dest))


if __name__ == "__main__":
    unittest.main()
