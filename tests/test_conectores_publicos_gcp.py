"""E2E mocked source API -> existing normalizer -> RAW and SQLite."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.conectores_publicos_gcp import coletar, preparar_consulta, ErroConectorNuvem


class Response:
    status=200
    def __init__(self,url,obj,mime="application/json"):
        self.url=url
        self.raw=json.dumps(obj).encode("utf-8")
        self.headers={"Content-Type":mime}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.raw[:n]


class Opener:
    def __init__(self,response):
        self.response=response
        self.calls=0
    def open(self,request,timeout):
        self.calls+=1
        return self.response


OPS=frozenset({"COLETA","ARMAZENAMENTO"})
AT=datetime(2026,10,23,15,0,0,tzinfo=timezone.utc)


class TestConectoresPublicosGCP(unittest.TestCase):
    def test_bcb_real_adapter_synthetic_http_e_replay(self):
        p=preparar_consulta("BCB_PTAX",inicio="2026-10-19",fim="2026-10-23",moeda="USD")
        resposta={"value":[{"cotacaoCompra":5.1,"cotacaoVenda":5.2,
                             "dataHoraCotacao":"2026-10-19 13:00:00",
                             "tipoBoletim":"Fechamento"}]}
        abridor=Opener(Response(p["url"],resposta))
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(fonte="BCB_PTAX",plano=p,banco=Path(d)/"fontes_reais.sqlite",
                     raw_dir=Path(d)/"raw",autorizacoes=OPS,executar=True,
                     abridor=abridor,instante=AT)
            a=coletar(**cfg)
            b=coletar(**cfg)
            self.assertEqual((a["registros"],a["novos"],b["novos"]),(1,1,0))
            self.assertEqual(abridor.calls,2)
            with sqlite3.connect(cfg["banco"]) as db:
                obs=db.execute("SELECT dataset_id,valor,referencia,competencia,natureza FROM observacoes").fetchone()
            self.assertEqual(obs,("BCB_PTAX","5.2","2026-10-19","2026-10","INFORMADO"))

    def test_ibge_pam_sem_tratar_suprimido_como_zero(self):
        p=preparar_consulta("IBGE_PAM",municipio_ibge="5107925",ano=2024,
                           codigo_produto_c81="40124",codigo_variavel="214")
        head={"D1C":"Município (Código)","D2C":"Variável (Código)",
              "D3C":"Ano (Código)",
              "D4C":"Produto das lavouras temporárias (Código)","V":"Valor","MN":"Unidade"}
        row={"D1C":"5107925","D2C":"214","D3C":"2024","D4C":"40124",
             "V":"X","MN":"Toneladas"}
        with tempfile.TemporaryDirectory() as d:
            res=coletar(fonte="IBGE_PAM",plano=p,banco=Path(d)/"fontes_reais.sqlite",
                       raw_dir=Path(d)/"raw",autorizacoes=OPS,executar=True,
                       abridor=Opener(Response(p["url"],[head,row])),instante=AT)
            self.assertEqual(res["registros"],1)
            with sqlite3.connect(Path(d)/"fontes_reais.sqlite") as db:
                obs=db.execute("SELECT valor,referencia,campos_json FROM observacoes").fetchone()
            self.assertIsNone(obs[0])
            self.assertEqual(obs[1],"2024-01-01")
            self.assertIn("SUPRIMIDO_SIGILO",obs[2])

    def test_nao_executa_sem_direitos_e_plano_alterado(self):
        p=preparar_consulta("BCB_PTAX",inicio="2026-10-19",fim="2026-10-23")
        with tempfile.TemporaryDirectory() as d:
            kw=dict(fonte="BCB_PTAX",plano=p,banco=Path(d)/"db",
                    raw_dir=Path(d)/"raw",executar=True)
            op=Opener(Response(p["url"],{"value":[]}))
            with self.assertRaises(PermissionError):
                coletar(**kw,abridor=op,instante=AT)
            self.assertEqual(op.calls,0)
            q={**p,"url":"https://example.org/replay"}
            with self.assertRaises(ErroConectorNuvem):
                coletar(**dict(kw,plano=q),autorizacoes=OPS,abridor=op,instante=AT)
            self.assertEqual(op.calls,0)

    def test_impossivel_gerar_template_generico_para_fontes_legadas(self):
        with self.assertRaises(ErroConectorNuvem):
            preparar_consulta("FONTES_680_HISTORICAS",inicio="2026-10-01",fim="2026-10-10")


if __name__=="__main__":
    unittest.main()
