import tempfile
import unittest
from datetime import date,datetime,timezone
from hashlib import sha256
from pathlib import Path

from nivon.ivo_duckdb_adapter import (
    ErroParquet, carregar_asof_parquet, CONSULTA
)

UTC=timezone.utc


def dt(y,m,d):
    return datetime(y,m,d,12,tzinfo=UTC)


def linha(valor=10.,publicacao="2026-02-04",coleta="2026-02-05T12:00:00+00:00"):
    return ("CONAB","PRODUCAO","SOJA","MT","t","2026-01","MENSAL",
            "2026-01-01",publicacao,coleta,valor,"OBSERVADO","primeira")


class TestIVODuckDB(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/"historico.parquet").write_bytes(b"fake-fixture" * 200)
        self.calls=[]

    def fake(self,query,args):
        self.calls.append((query,args))
        return [linha()]

    def consultar(self,**kw):
        args=dict(
            diretorio=self.root,arquivo="historico.parquet",
            fonte="CONAB",variavel="PRODUCAO",produto="SOJA",
            regiao="MT",unidade="t",
            corte_publicacao=date(2026,2,10),corte_coleta=dt(2026,2,10),
            acesso_autorizado=True,executor=self.fake)
        args.update(kw)
        return carregar_asof_parquet(**args)

    def test_consulta_parametrizada_e_visao_asof(self):
        res=self.consultar()
        self.assertEqual(res["linhas_asof"],1)
        self.assertEqual(res["observacoes"][0].valor,10.)
        self.assertFalse(res["origem_validada_automaticamente"])
        self.assertEqual(res["arquivo_sha256"],
            sha256((self.root/"historico.parquet").read_bytes()).hexdigest())
        self.assertEqual(self.calls[0][0],CONSULTA)
        self.assertEqual(self.calls[0][1][-1],5001)

    def test_publicacao_apos_corte_excluida(self):
        res=self.consultar(corte_publicacao=date(2026,2,1))
        self.assertEqual(res["linhas_asof"],0)

    def test_coleta_apos_corte_excluida(self):
        res=self.consultar(corte_coleta=dt(2026,2,4))
        self.assertEqual(res["linhas_asof"],0)

    def test_autorizacao_necessaria(self):
        with self.assertRaises(PermissionError):
            self.consultar(acesso_autorizado=False)
        self.assertFalse(self.calls)

    def test_path_traversal_rejeitado(self):
        with self.assertRaises(ErroParquet):
            self.consultar(arquivo="../historico.parquet")

    def test_symlink_rejeitado(self):
        (self.root/"alias.parquet").symlink_to(self.root/"historico.parquet")
        with self.assertRaises(ErroParquet):
            self.consultar(arquivo="alias.parquet")

    def test_sql_nao_recebe_filtro_como_literal(self):
        res=self.consultar(fonte="CONAB' OR 1=1 --", executor=lambda sql,args:[])
        self.assertEqual(res["linhas_asof"],0)
        self.assertNotIn("OR 1=1", self.calls[0][0] if self.calls else CONSULTA)

    def test_tipo_ou_escopo_invalido_rejeitado(self):
        with self.assertRaises(ErroParquet):
            self.consultar(executor=lambda sql,args:[linha()[:-1]])
        with self.assertRaises(ErroParquet):
            self.consultar(executor=lambda sql,args:[
                ("IMEA",)+linha()[1:]])

    def test_estouro_linhas_bloqueado(self):
        with self.assertRaises(ErroParquet):
            self.consultar(max_linhas=1,executor=lambda sql,args:[linha(),linha()])

    def test_tempo_sem_fuso_bloqueado(self):
        with self.assertRaises(ErroParquet):
            self.consultar(corte_coleta=datetime(2026,2,10))

    def test_arquivo_nao_parquet_bloqueado(self):
        (self.root/"outro.csv").write_text("nao")
        with self.assertRaises(ErroParquet):
            self.consultar(arquivo="outro.csv")


if __name__=="__main__":
    unittest.main()
