"""Teste offline da primeira série histórica real da ANTT em BigQuery e GCS."""
import unittest
from types import SimpleNamespace

from nivon.antt_bigquery import DestinoBQ
from nivon.antt_gcp_backfill_historico import (
    verificar_anos, validar_planos, carregar_historico)
from nivon.transporte_multimodal import ErroTransporte


class FakeSDK:
    class QueryJobConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class ScalarQueryParameter:
        def __init__(self, name, typ, value):
            self.name, self.typ, self.value = name, typ, value


class FakeClientBQ:
    def __init__(self, *, divergir=None, falha_job=False):
        self.chamadas = []
        self.divergir = divergir
        self.falha_job = falha_job
    def query(self, sql, job_config):
        self.chamadas.append((sql, job_config))
        if sql == "SELECT 1 AS confirmado":
            if self.falha_job:
                raise ErroTransporte("permissao jobs ausente")
            return SimpleNamespace(result=lambda timeout: [SimpleNamespace(confirmado=1)])
        ano = [x.value for x in job_config.query_parameters if x.name == "ano"][0]
        n = 10 if ano == self.divergir else 2
        return SimpleNamespace(result=lambda timeout: [SimpleNamespace(n=n,tu="200")])


def plano(ano, **extra):
    d = {
        "estado":"PLANO_VALIDADO_READ_ONLY_SEM_CARGA",
        "ano":ano, "projeto":"nivon-data","dataset":"nivon_raw",
        "bucket":"nivon-data-raw-2026","localizacao":"southamerica-east1",
        "bigquery_tabela_existe":True, "gravacoes_realizadas":0,
        "bytes_brutos":100, "linhas_ferroviarias":2,
        "arquivo_sha256":str(ano).rjust(64,"a"),
        "competencia_maxima_publicada":f"{ano}-12",
        "toneladas_uteis_declaradas_no_arquivo":"200",
    }
    d.update(extra)
    return d


class Historico(unittest.TestCase):
    def setUp(self):
        self.dest = DestinoBQ("nivon-data","nivon_raw")
        self.bucket = "nivon-data-raw-2026"

    def test_anos_contiguos_sem_2026_ou_lote_grande(self):
        for anos in ([2026],[2005],[2022,2024],list(range(2020,2025)),
                     [2024,2024],[],[2025,2024]):
            with self.subTest(anos=anos):
                with self.assertRaises(ErroTransporte):
                    verificar_anos(anos)
        verificar_anos([2022,2023,2024,2025])

    def test_limites_antes_de_escrita(self):
        tests=[
            {"bytes_brutos":2_000_001},{"linhas_ferroviarias":15_001},
            {"bigquery_tabela_existe":False},{"localizacao":"US"},
            {"gravacoes_realizadas":1},{"competencia_maxima_publicada":"2026-01"},
            {"arquivo_sha256":"123"},
        ]
        for p in tests:
            with self.subTest(p=p):
                with self.assertRaises(ErroTransporte):
                    validar_planos([plano(2025,**p)],[2025],self.dest,self.bucket)
        with self.assertRaises(ErroTransporte):
            validar_planos([plano(2025)],[2025],self.dest,"bucket-diferente")

    def test_limites_agregados(self):
        ps=[plano(y,bytes_brutos=1_600_000) for y in [2022,2023,2024,2025]]
        with self.assertRaisesRegex(ErroTransporte, "agregado"):
            validar_planos(ps,[2022,2023,2024,2025],self.dest,self.bucket)
        ps=[plano(y,linhas_ferroviarias=11_000) for y in [2022,2023,2024,2025]]
        with self.assertRaisesRegex(ErroTransporte, "agregado"):
            validar_planos(ps,[2022,2023,2024,2025],self.dest,self.bucket)

    def test_4_anos_ordem_sha_soma_e_progresso(self):
        eventos=[]
        partial=[]
        def preparador(pasta,*,ano,destino,bucket):
            eventos.append(f"preparar{ano}")
            return plano(ano)
        def gcs(pasta,anos,bucket,**kwargs):
            eventos.append(f"gcs{anos[0]}")
            return [{"estado":"ARQUIVADO","sha256":plano(anos[0])["arquivo_sha256"]}]
        def gravador(pasta,anos,destino,**kwargs):
            eventos.append(f"bq{anos[0]}")
            self.assertFalse(kwargs["permitir_criar_tabela"])
            return [{"estado":"CARREGADO_PENDENTE_CONCILIACAO",
                     "sha256":plano(anos[0])["arquivo_sha256"]}]
        cliente=FakeClientBQ()
        r=carregar_historico(
            pasta="irrelevante",anos=[2022,2023,2024,2025],
            destino=self.dest,bucket=self.bucket,
            preparador=preparador,arquivador=gcs,gravador=gravador,
            cliente_bq=cliente,sdk=FakeSDK,
            salvar_progresso=lambda x:partial.append(
                (x["estado"],len(x["anos_conciliados"]))))
        self.assertEqual(r["estado"],"BACKFILL_HISTORICO_CONCILIADO")
        self.assertEqual([x["ano"] for x in r["anos_conciliados"]],[2022,2023,2024,2025])
        self.assertEqual(eventos[:4],[f"preparar{y}" for y in [2022,2023,2024,2025]])
        self.assertEqual(len(cliente.chamadas),5)
        self.assertEqual(partial[-1],("BACKFILL_HISTORICO_CONCILIADO",4))
        self.assertEqual(r["carga_recorrente_ativada"],False)
        self.assertEqual([x["gcs_estado"] for x in r["anos_conciliados"]],["ARQUIVADO"]*4)

    def test_falha_validacao_um_ano_bloqueia_todos_uploads(self):
        eventos=[]
        def p(pasta,*,ano,destino,bucket):
            eventos.append(("preparar",ano))
            return plano(ano, bigquery_tabela_existe=ano!=2024)
        def gcs(*a,**k):
            eventos.append(("escrita",0))
            raise AssertionError("upload proibido")
        with self.assertRaises(ErroTransporte):
            carregar_historico(pasta="x",anos=[2023,2024,2025],
                destino=self.dest,bucket=self.bucket,preparador=p,
                arquivador=gcs,cliente_bq=FakeClientBQ(),sdk=FakeSDK)
        self.assertEqual(eventos,[("preparar",2023),("preparar",2024),("preparar",2025)])

    def test_permissao_job_bloqueia_gcs(self):
        def proibido(*a,**k):
            raise AssertionError("GCS/BQ nao podem escrever")
        with self.assertRaisesRegex(ErroTransporte,"permissao"):
            carregar_historico(pasta="x",anos=[2025],destino=self.dest,
                bucket=self.bucket,preparador=lambda *a,**k:plano(2025),
                cliente_bq=FakeClientBQ(falha_job=True),sdk=FakeSDK,
                arquivador=proibido,gravador=proibido)

    def test_soma_errada_interrompe_e_salva_progresso_parcial(self):
        eventos=[]
        with self.assertRaisesRegex(ErroTransporte,"divergencia"):
            carregar_historico(pasta="x",anos=[2024,2025],destino=self.dest,bucket=self.bucket,
                preparador=lambda *a,**kw:plano(kw["ano"]),
                arquivador=lambda *a,**kw:[{"estado":"JA_ARQUIVADO","sha256":plano(a[1][0])["arquivo_sha256"]}],
                gravador=lambda *a,**kw:[{"estado":"SEM_MUDANCA","sha256":plano(a[1][0])["arquivo_sha256"]}],
                cliente_bq=FakeClientBQ(divergir=2025),sdk=FakeSDK,
                salvar_progresso=lambda x:eventos.append([i["ano"] for i in x["anos_conciliados"]]))
        self.assertEqual(eventos,[[2024]])

if __name__ == "__main__":
    unittest.main()
