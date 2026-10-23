import unittest
from types import SimpleNamespace

from nivon.antt_bigquery import DestinoBQ
from nivon.antt_gcp_auditoria_historica import BASELINE, auditar_base, consultar
from nivon.transporte_multimodal import ErroTransporte


def linhas():
    return [SimpleNamespace(ano=a,registros=n,tu=str(t),versoes_sha=1,
                            ultima_competencia="2026-08" if a==2026 else f"{a}-12")
            for a,n,t in BASELINE]


class SDK:
    class QueryJobConfig:
        def __init__(self,**kwargs): self.__dict__.update(kwargs)


class Cliente:
    def __init__(self,rows):
        self.rows=rows
        self.sql=None
        self.conf=None
    def query(self,sql,job_config):
        self.sql=sql
        self.conf=job_config
        return SimpleNamespace(
            total_bytes_processed=12345,
            result=lambda timeout:self.rows)


class HistoricoBQ(unittest.TestCase):
    def setUp(self):
        self.d=DestinoBQ("nivon-data","nivon_raw")

    def test_soma_real_e_21_anos(self):
        r=auditar_base(linhas(),destino=self.d)
        self.assertEqual(r["estado"],"AUDITORIA_HISTORICO_BQ_2006_2026_APROVADA")
        self.assertEqual(r["anos"],21)
        self.assertEqual(r["registros_origem_destino_acumulados"],174850)
        self.assertEqual(r["toneladas_uteis_ferroviarias_acumuladas"],"9952668869")
        self.assertTrue(r["ano_2026_parcial"])
        self.assertFalse(r["volumes_rodoviarios_ou_transbordos_comprovados"])

    def test_ano_ausente_proibido(self):
        with self.assertRaisesRegex(ErroTransporte,"incompleta"):
            auditar_base(linhas()[:-1],destino=self.d)

    def test_registros_ou_tu_divergentes_proibidos(self):
        for key,valor in (("registros",1),("tu","999"),("versoes_sha",2),
                          ("ultima_competencia","2026-12")):
            l=linhas()
            setattr(l[-1],key,valor)
            with self.subTest(key=key):
                with self.assertRaises(ErroTransporte):
                    auditar_base(l,destino=self.d)

    def test_nao_mistura_projetos(self):
        with self.assertRaises(ErroTransporte):
            auditar_base(linhas(),destino=DestinoBQ("outro-projeto-123","nivon_raw"))

    def test_sql_limitado_apenas_leitura(self):
        client=Cliente(linhas())
        r=consultar(destino=self.d,cliente=client,sdk=SDK)
        self.assertEqual(r["bytes_processados_job"],12345)
        self.assertEqual(client.conf.maximum_bytes_billed,250_000_000)
        self.assertIn("FROM \`nivon-data.nivon_raw.vw_antt_ferrovia_od_atual\`",client.sql)
        self.assertTrue(client.sql.startswith("SELECT ano"))
        self.assertIn("COUNT(DISTINCT arquivo_sha256)",client.sql)

if __name__=="__main__":
    unittest.main()
