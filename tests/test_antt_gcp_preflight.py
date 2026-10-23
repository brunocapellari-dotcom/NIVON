import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from nivon.antt_bigquery import DestinoBQ, _FIELDS, main as bigquery_main
from nivon.antt_gcp_preflight import verificar_tabela_antt


class NotFound(Exception):
    pass


class FakeBQ:
    def __init__(self, table=None, view=None):
        self.table = table
        self.view = view
        self.calls = []

    def get_dataset(self, ref):
        self.calls.append(("get_dataset", ref))
        return object()

    def get_table(self, ref):
        self.calls.append(("get_table", ref))
        if ref.endswith("vw_antt_ferrovia_od_atual") and self.view is not None:
            return self.view
        if ref.endswith("antt_ferrovia_od_snapshots") and self.table is not None:
            return self.table
        raise NotFound("nao localizado")


def table(*, missing=(), partition="data_referencia", cluster=True):
    schema = [SimpleNamespace(name=n, field_type=t)
              for n,t in _FIELDS.items() if n not in missing]
    return SimpleNamespace(schema=schema,
        time_partitioning=SimpleNamespace(field=partition,type_="MONTH"),
        clustering_fields=["ferrovia","mercadoria","uf_origem","uf_destino"] if cluster else [],
        num_rows=10)


class TestPreflightCloud(unittest.TestCase):
    projeto = "nivon-data"
    dataset = "nivon_raw"

    def test_tabela_ausente_nao_gera_query_ou_criacao(self):
        cli=FakeBQ()
        r=verificar_tabela_antt(projeto=self.projeto,dataset=self.dataset,cliente=cli)
        self.assertEqual(r["estado"], "TABELA_ANTT_AUSENTE")
        self.assertTrue(r["bootstrap_necessario"])
        self.assertFalse(r["job_bigquery_criado"])
        self.assertEqual([x[0] for x in cli.calls],
                         ["get_dataset","get_table"])

    def test_tabela_valida_view_ausente_sem_scan(self):
        cli=FakeBQ(table=table())
        r=verificar_tabela_antt(projeto=self.projeto,dataset=self.dataset,cliente=cli)
        self.assertEqual(r["estado"],"TABELA_ANTT_OK_VIEW_AUSENTE_OU_DIVERGENTE")
        self.assertTrue(r["tabela_pronta_para_carga"])
        self.assertFalse(r["carga_antt_comprovada"])
        self.assertEqual(len(cli.calls),3)

    def test_esquema_invalido_bloqueia(self):
        cli=FakeBQ(table=table(missing=("tku_raw",),cluster=False))
        r=verificar_tabela_antt(projeto=self.projeto,dataset=self.dataset,cliente=cli)
        self.assertEqual(r["estado"],"ESQUEMA_ANTT_DIVERGENTE")
        self.assertEqual(r["campos_divergentes"],["tku_raw"])
        self.assertFalse(r["tabela_pronta_para_carga"])
        self.assertFalse(r["cluster_confirmado"])

    def test_tabela_e_view_metadados_prontos_sem_carga_comprovada(self):
        d=DestinoBQ(self.projeto,self.dataset)
        v=SimpleNamespace(table_type="VIEW",view_query="SELECT * FROM "+chr(96)+d.tabela_completa+chr(96))
        cli=FakeBQ(table=table(),view=v)
        r=verificar_tabela_antt(projeto=self.projeto,dataset=self.dataset,cliente=cli)
        self.assertEqual(r["estado"],"METADADOS_ANTT_OK_SEM_PROVA_DE_CARGA")
        self.assertTrue(r["view_atual_verificada"])
        self.assertFalse(r["permissao_escrita_comprovada"])

    def test_comando_bigquery_tem_flag_de_bootstrap(self):
        from nivon import antt_bigquery
        fake=lambda *args,**kwargs:[{"estado":"DRY_RUN"}]
        with patch.object(antt_bigquery, "gravar_bigquery", side_effect=fake) as call, \
             patch("sys.argv",["cmd","--staging","/tmp/vazio",
                                "--anos","2026","--projeto","nivon-data",
                                "--dataset","nivon_raw"]),redirect_stdout(io.StringIO()):
            self.assertEqual(bigquery_main(),0)
            self.assertFalse(call.call_args.kwargs["permitir_criar_tabela"])
        with patch.object(antt_bigquery, "gravar_bigquery", side_effect=fake) as call, \
             patch("sys.argv",["cmd","--staging","/tmp/vazio",
                                "--anos","2026","--projeto","nivon-data",
                                "--dataset","nivon_raw","--permitir-criar-tabela"]),redirect_stdout(io.StringIO()):
            self.assertEqual(bigquery_main(),0)
            self.assertTrue(call.call_args.kwargs["permitir_criar_tabela"])


if __name__ == "__main__":
    unittest.main()
