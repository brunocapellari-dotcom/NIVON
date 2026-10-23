"""Prova local: inventário nunca cria recursos nem executa SQL."""
from types import SimpleNamespace
import unittest

from scripts.inventario_gcp_readonly import inventariar, ErroInventario, REGIAO


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


def ds(project, name, loc=REGIAO):
    return SimpleNamespace(project=project, dataset_id=name, location=loc)


def table(partition, fields=None):
    if fields is None:
        fields = {"data_referencia": "DATE", "data_particao": "DATE",
                  "data_coleta": "TIMESTAMP", "data_publicacao": "TIMESTAMP",
                  "reference_date": "DATE", "first_collected_at": "TIMESTAMP"}
    schema = [SimpleNamespace(name=k, field_type=v) for k, v in fields.items()]
    return SimpleNamespace(schema=schema,
                           time_partitioning=SimpleNamespace(field=partition),
                           require_partition_filter=True)


class FakeBQ:
    def __init__(self, missing=(), denied=(), wrong_region=(), wrong_table=()):
        self.datasets = []
        self.tables = []
        self.missing = missing
        self.denied = denied
        self.wrong_region = wrong_region
        self.wrong_table = wrong_table

    def get_dataset(self, ref):
        self.datasets.append(ref)
        if ref in self.missing:
            raise NotFound(ref)
        if ref in self.denied:
            raise Forbidden(ref)
        return ds(ref.split(".")[0], ref.split(".")[1],
                  "us-central1" if ref in self.wrong_region else REGIAO)

    def get_table(self, ref):
        self.tables.append(ref)
        if ref in self.missing:
            raise NotFound(ref)
        if ref in self.denied:
            raise Forbidden(ref)
        key = ref.split(".")[-1]
        partition = "data_particao" if key in ("neon_legado", "zarc_linhas_mt") else (
            "reference_date" if key == "ptax_quotes" else "data_referencia")
        if ref in self.wrong_table:
            partition = "wrong"
        return table(partition)


class FakeGCS:
    def __init__(self, region=REGIAO):
        self.calls = []
        self.region = region

    def get_bucket(self, name):
        self.calls.append(name)
        return SimpleNamespace(name=name, location=self.region)


class InventarioCloud(unittest.TestCase):
    def run_check(self, bq=None, gcs=None):
        bq = bq or FakeBQ()
        gcs = gcs or FakeGCS()
        out = inventariar(projeto="nivon-data", dataset_raw="nivon_raw",
                        bucket="nivon-data-raw-2026",
                        bq=bq, gcs=gcs, not_found=NotFound, forbidden=Forbidden)
        self.assertFalse(any("write" in s.lower() or "create" in s.lower()
                             for s in bq.datasets + bq.tables))
        self.assertEqual(out["alteracoes"], 0)
        self.assertEqual(out["consultas_sql"], 0)
        self.assertFalse(out["gravacao_validada"])
        return out

    def test_todas_tabelas_existentes_e_validas(self):
        out = self.run_check()
        self.assertEqual(out["estado"], "DESTINOS_EXISTENTES_VALIDOS")
        self.assertEqual(len(out["tabelas"]), 4)
        self.assertTrue(all(x["estado"] == "ESQUEMA_VALIDADO" for x in out["tabelas"]))

    def test_ausencia_nao_dispara_criacao(self):
        bq = FakeBQ(missing=("nivon-data.nivon_stage",))
        out = self.run_check(bq=bq)
        self.assertEqual(out["estado"], "DESTINOS_PENDENTES")
        self.assertEqual(sum(x["estado"] == "DATASET_AUSENTE" for x in out["tabelas"]), 2)

    def test_sem_acesso_nao_e_confundido_com_ausencia(self):
        bq = FakeBQ(denied=("nivon-data.nivon_core.ptax_quotes",))
        out = self.run_check(bq=bq)
        self.assertEqual(out["tabelas"][-1]["estado"], "SEM_ACESSO")

    def test_regiao_incorreta_e_falha_fechada_no_raw(self):
        with self.assertRaises(ErroInventario):
            self.run_check(gcs=FakeGCS("us-central1"))

    def test_regiao_incorreta_em_stage_nao_e_sucesso(self):
        bq = FakeBQ(wrong_region=("nivon-data.nivon_stage",))
        out = self.run_check(bq=bq)
        self.assertEqual(out["estado"], "DESTINOS_PENDENTES")
        self.assertEqual(out["tabelas"][1]["estado"], "DATASET_REGIAO_DIVERGENTE")

    def test_particao_divergente_nao_e_homologacao(self):
        bq = FakeBQ(wrong_table=("nivon-data.nivon_raw.nivon_observacoes",))
        out = self.run_check(bq=bq)
        self.assertEqual(out["tabelas"][0]["estado"], "ESQUEMA_DIVERGENTE")

    def test_bootstrap_usa_regiao_real_sem_criacao_implicita(self):
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[1]
        bootstrap = (raiz / "scripts/bootstrap_nivon_gcp.sh").read_text(encoding="utf-8")
        ddl = (raiz / "database/bigquery/nivon_neon_legado_schema.sql").read_text(encoding="utf-8")
        self.assertIn('REGION="southamerica-east1"', bootstrap)
        self.assertIn('OPTIONS(location="southamerica-east1"', ddl)
        self.assertNotIn('us-central1', bootstrap)
        self.assertNotIn('us-central1', ddl)
        self.assertIn('if [[ "${1:-}" != "--aplicar" ]]; then', bootstrap)

    def test_identificador_invalido_rejeitado_antes_da_rede(self):
        bq = FakeBQ()
        with self.assertRaises(ErroInventario):
            inventariar(projeto="INVALID", dataset_raw="nivon_raw",
                        bucket="nivon-data-raw-2026", bq=bq, gcs=FakeGCS(),
                        not_found=NotFound, forbidden=Forbidden)
        self.assertEqual(bq.datasets, [])


if __name__ == "__main__":
    unittest.main()
