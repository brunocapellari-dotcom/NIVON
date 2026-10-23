import tempfile
import unittest

from nivon.antt_gcp_pipeline import executar_pipeline
from nivon.transporte_multimodal import ErroTransporte


class TestPipeline(unittest.TestCase):
    def test_dry_run_nao_toca_rede(self):
        calls = []
        def proibido(*args, **kwargs):
            calls.append(kwargs)
            raise AssertionError("chamada nao autorizada")
        result = executar_pipeline(pasta="/tmp/sem-dados", anos=[2025, 2026],
                                  projeto="nivon-dados-123", dataset="transporte",
                                  bucket="nivon-antt", coletor=proibido,
                                  arquivador=proibido, publicador=proibido)
        self.assertEqual(result["estado"], "PLANO_SEM_EXECUCAO")
        self.assertEqual(calls, [])

    def test_execucao_ordem_coleta_arquivo_banco(self):
        ordem = []
        def coleta(**kwargs):
            ordem.append("coleta")
            return [{"ano": 2026, "estado": "STAGING_NAO_HOMOLOGADO"}]
        def gcs(*args, **kwargs):
            ordem.append("gcs")
            return [{"ano": 2026, "estado": "JA_ARQUIVADO"}]
        def bq(*args, **kwargs):
            ordem.append("bigquery")
            self.assertFalse(kwargs["permitir_criar_tabela"])
            return [{"ano": 2026, "estado": "SEM_MUDANCA"}]
        r = executar_pipeline(pasta="/tmp/gerenciado", anos=[2026],
                             projeto="nivon-dados-123", dataset="transporte",
                             bucket="nivon-antt", habilitar_live=True,
                             coletor=coleta, arquivador=gcs, publicador=bq)
        self.assertEqual(ordem, ["coleta", "gcs", "bigquery"])
        self.assertEqual(r["estado"], "GCP_CARREGADO_NAO_HOMOLOGADO")

    def test_bootstrap_so_transmitido_quando_autorizado(self):
        seen=[]
        def coleta(**kwargs):
            return [{"estado":"STAGING_NAO_HOMOLOGADO"}]
        def gcs(*args, **kwargs):
            return [{"estado":"ARQUIVADO"}]
        def bq(*args, **kwargs):
            seen.append(kwargs.get("permitir_criar_tabela"))
            return [{"estado":"SEM_MUDANCA"}]
        executar_pipeline(pasta="/tmp/lab", anos=[2026],
                        projeto="nivon-dados-123",dataset="transporte",
                        bucket="bucket-nivon",habilitar_live=True,
                        permitir_criar_tabela=True,
                        coletor=coleta,arquivador=gcs,publicador=bq)
        self.assertEqual(seen,[True])

    def test_bloqueio_gcs_impede_escrita_no_banco(self):
        ordem = []
        def coleta(**kwargs):
            ordem.append("coleta")
            return [{}]
        def gcs(*args, **kwargs):
            ordem.append("gcs")
            return [{"estado": "FALHA"}]
        def bq(*args, **kwargs):
            ordem.append("bigquery")
            return []
        with self.assertRaises(ErroTransporte):
            executar_pipeline(pasta="/tmp/gerenciado", anos=[2026],
                             projeto="nivon-dados-123", dataset="transporte",
                             bucket="nivon-antt", habilitar_live=True,
                             coletor=coleta, arquivador=gcs, publicador=bq)
        self.assertEqual(ordem, ["coleta", "gcs"])


if __name__ == "__main__":
    unittest.main()
