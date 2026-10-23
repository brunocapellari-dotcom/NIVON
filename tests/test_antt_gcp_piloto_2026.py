"""Bateria de bloqueios da primeira escrita anual ANTT (sem Google Cloud)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from nivon.antt_bigquery import DestinoBQ
from nivon.antt_gcp_piloto_2026 import carregar_uma_vez, conferir_limites_plano
from nivon.transporte_multimodal import ErroTransporte


def plano(**kwargs):
    r = {
        "estado":"PLANO_VALIDADO_READ_ONLY_SEM_CARGA",
        "projeto":"nivon-data","dataset":"nivon_raw",
        "bucket":"nivon-data-raw-2026","localizacao":"southamerica-east1",
        "ano":2026,"competencia_maxima_publicada":"2026-08",
        "gravacoes_realizadas":0,"bytes_brutos":393698,
        "linhas_ferroviarias":5081,"arquivo_sha256":"d"*64,
        "toneladas_uteis_declaradas_no_arquivo":"353466337",
    }
    r.update(kwargs)
    return r


class SDK:
    class QueryJobConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class ScalarQueryParameter:
        def __init__(self, name, typ, value):
            self.name, self.typ, self.value = name, typ, value


class Job:
    def __init__(self, rows):
        self.rows=rows
    def result(self,timeout):
        return self.rows


class BQ:
    def __init__(self, *, discrepancia=False, falta_job=False):
        self.calls=[]
        self.discrepancia=discrepancia
        self.falta_job=falta_job
    def query(self,sql,job_config):
        self.calls.append((sql,job_config))
        if sql.startswith("SELECT 1"):
            if self.falta_job:
                raise ErroTransporte("sem permissao de jobs")
            return Job([SimpleNamespace(confirmado=1)])
        return Job([SimpleNamespace(n=5080 if self.discrepancia else 5081,
                                    tu="353466337")])


class TestPiloto(unittest.TestCase):
    def setUp(self):
        self.destino=DestinoBQ("nivon-data","nivon_raw")
        self.bucket="nivon-data-raw-2026"

    def test_limites_de_tamanho_e_ano(self):
        for changed in ({"bytes_brutos":2_000_001}, {"linhas_ferroviarias":10_001},
                        {"ano":2025},{"bucket":"outro"},{"localizacao":"US"},
                        {"gravacoes_realizadas":1},{"arquivo_sha256":""}):
            with self.subTest(changed=changed):
                with self.assertRaises(ErroTransporte):
                    conferir_limites_plano(plano(**changed),destino=self.destino,bucket=self.bucket)

    def test_carrega_uma_vez_e_concilia_sem_outros_anos(self):
        called=[]
        def preparar(*args,**kwargs):
            called.append("preparar")
            return plano()
        def gcs(*args,**kwargs):
            called.append("gcs")
            self.assertEqual(args[1],[2026])
            return [{"estado":"ARQUIVADO","sha256":"d"*64}]
        def bq(*args,**kwargs):
            called.append("bq")
            self.assertEqual(args[1],[2026])
            self.assertTrue(kwargs["permitir_criar_tabela"])
            return [{"estado":"CARREGADO_PENDENTE_CONCILIACAO","sha256":"d"*64}]
        client=BQ()
        res=carregar_uma_vez(pasta="/tmp/staging",destino=self.destino,bucket=self.bucket,
                            cliente_bq=client,sdk=SDK,
                            preparador=preparar,arquivador=gcs,gravador=bq)
        self.assertEqual(called,["preparar","gcs","bq"])
        self.assertEqual(res["estado"],"ANTT_2026_GCS_BIGQUERY_CONCILIADO")
        self.assertEqual(res["linhas_confirmadas"],5081)
        self.assertFalse(res["carga_continua_ativada"])
        self.assertFalse(res["outros_anos_carregados_pelo_piloto"])
        self.assertEqual(client.calls[0][1].maximum_bytes_billed,0)
        self.assertEqual(client.calls[1][1].maximum_bytes_billed,50_000_000)

    def test_se_falhar_jobs_nao_upload_gcs(self):
        chamadas=[]
        def gcs(*args,**kwargs):
            chamadas.append("escrita")
            raise AssertionError("GCS nao pode ser tocado")
        with self.assertRaises(ErroTransporte):
            carregar_uma_vez(pasta="/tmp/staging",destino=self.destino,bucket=self.bucket,
                             cliente_bq=BQ(falta_job=True),sdk=SDK,
                             preparador=lambda *a,**k:plano(),arquivador=gcs)
        self.assertEqual(chamadas,[])

    def test_plano_invalido_nao_cria_job(self):
        cliente=BQ()
        with self.assertRaises(ErroTransporte):
            carregar_uma_vez(pasta="/tmp/staging",destino=self.destino,bucket=self.bucket,
                             cliente_bq=cliente,sdk=SDK,
                             preparador=lambda *a,**k:plano(bytes_brutos=50_000_000))
        self.assertEqual(cliente.calls,[])

    def test_falha_na_reconciliacao_interrompe_status_de_sucesso(self):
        with self.assertRaisesRegex(ErroTransporte,"reconciliacao"):
            carregar_uma_vez(pasta="/tmp/staging",destino=self.destino,bucket=self.bucket,
                             cliente_bq=BQ(discrepancia=True),sdk=SDK,
                             preparador=lambda *a,**k:plano(),
                             arquivador=lambda *a,**k:[{"estado":"JA_ARQUIVADO","sha256":"d"*64}],
                             gravador=lambda *a,**k:[{"estado":"SEM_MUDANCA","sha256":"d"*64}])

if __name__ == "__main__":
    unittest.main()
