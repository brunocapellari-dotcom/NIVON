"""Fluxo integrado do backfill SIDRA com exemplos sintéticos, sem rede."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_backfill import (
    executar_backfill_quarentena, consultar_backfill_quarentena,
)
from nivon.pecuaria_sidra_quarentena import (
    _conectar, _preparar, _salvar_capturas_atomicas, recuperar_values_quarentena,
)
from test_pecuaria_sidra_quarentena import transporte_sintetico


def fake_transport(*, url, timeout, limite):
    result = transporte_sintetico(url=url, timeout=timeout, limite=limite)
    periodo=url.split("/p/")[1].split("/")[0]
    rows=json.loads(result["corpo"].decode("utf-8"))
    for row in rows[1:]:
        row["D2C"]=periodo
    result["corpo"]=json.dumps(rows,ensure_ascii=False).encode()
    return result


class TestBackfillSidra(unittest.TestCase):
    def setUp(self):
        self.t=TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.banco=Path(self.t.name)/"quarentena.sqlite"
        self.base={"periodos":["202502","202601"],
                   "direitos_confirmados":True,
                   "transporte":fake_transport}

    def executar(self,**kw):
        args=dict(self.base)
        args.update(kw)
        return executar_backfill_quarentena(**args)

    def test_preview_12_extratos_sem_escrever_ou_publicar(self):
        result=self.executar()
        self.assertEqual(result["n_requisicoes"],12)
        self.assertEqual(result["n_capturas"],12)
        self.assertEqual(result["por_periodo"]["202502"]["capturas"],6)
        self.assertEqual(result["por_periodo"]["202601"]["registros"],12)
        self.assertFalse(result["revisoes_historicas_autenticadas"])
        self.assertFalse(result["publicacao_permitida"])
        self.assertFalse(self.banco.exists())

    def test_12_extratos_em_transacao_e_replay_idempotente(self):
        r=self.executar(gravar=True,banco=self.banco)
        self.assertEqual(len(set(r["ids_capturas"])),12)
        repeat=self.executar(gravar=True,banco=self.banco)
        self.assertEqual(repeat["ids_capturas"],r["ids_capturas"])
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM valores_pecuaria_quarentena").fetchone()[0],12)
        rec=recuperar_values_quarentena(banco=self.banco,id_captura=r["ids_capturas"][0])
        self.assertEqual(rec["periodo"],"202502")
        self.assertFalse(rec["homologado"])

    def test_reconstituicao_asof_somente_apos_a_coleta(self):
        self.executar(gravar=True,banco=self.banco)
        historico=consultar_backfill_quarentena(
            banco=self.banco,especie="BOVINO",
            periodos=["202502","202601"],
            corte_asof="2026-01-01T00:00:00+00:00")
        self.assertEqual(historico["capturas_conhecidas_no_corte"],[])
        self.assertIsNone(historico["diagnostico"])
        atual=consultar_backfill_quarentena(
            banco=self.banco,especie="BOVINO",
            periodos=["202502","202601"],
            corte_asof="2026-10-24T00:00:00+00:00")
        self.assertEqual(len(atual["capturas_conhecidas_no_corte"]),4)
        self.assertEqual(len(atual["diagnostico"]["indicadores"]),4)
        self.assertFalse(atual["publicacao_historica_conhecida"])
        self.assertFalse(atual["publicacao_permitida"])

    def test_trimestre_errado_rejeitado_antes_do_banco(self):
        def periodo_incorreto(*,url,timeout,limite):
            res=fake_transport(url=url,timeout=timeout,limite=limite)
            obj=json.loads(res["corpo"])
            obj[1]["D2C"]="202602"
            res["corpo"]=json.dumps(obj,ensure_ascii=False).encode()
            return res
        with self.assertRaisesRegex(DadoInvalido,"outro trimestre"):
            self.executar(transporte=periodo_incorreto,gravar=True,banco=self.banco)
        self.assertFalse(self.banco.exists())

    def test_mutacao_semantica_dimensionais_rejeitada(self):
        def errado(*,url,timeout,limite):
            result=fake_transport(url=url,timeout=timeout,limite=limite)
            d=json.loads(result["corpo"])
            if "/t/1092/" in url:
                d[0]["D6C"]="Mês de referência temporal"
            result["corpo"]=json.dumps(d,ensure_ascii=False).encode()
            return result
        with self.assertRaisesRegex(DadoInvalido,"header"):
            self.executar(transporte=errado,gravar=True,banco=self.banco)
        self.assertFalse(self.banco.exists())

    def test_ultima_resposta_http_erro_nao_deixa_banco(self):
        contador=[0]
        def falha(*,url,timeout,limite):
            contador[0]+=1
            if contador[0]==12:
                return {"status_http":503,"content_type":"application/json",
                        "corpo":b'{"erro":true}'}
            return fake_transport(url=url,timeout=timeout,limite=limite)
        with self.assertRaisesRegex(DadoInvalido,"HTTP"):
            self.executar(transporte=falha,gravar=True,banco=self.banco)
        self.assertEqual(contador[0],12)
        self.assertFalse(self.banco.exists())

    def test_sqlite_trigger_nos_ultimos_registros_reverte_o_lote(self):
        with _conectar(self.banco,criar=True) as cx:
            cx.execute("""CREATE TRIGGER bloquear_ultimo BEFORE INSERT
                          ON valores_pecuaria_quarentena
                          WHEN NEW.periodo='202601'
                          BEGIN SELECT RAISE(ABORT,'falha_forcada'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.executar(gravar=True,banco=self.banco)
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM valores_pecuaria_quarentena").fetchone()[0],0)

    def test_ate_quatro_trimestres_sem_duplicatas(self):
        for periodos in ([],["202502"]*2,
                         ["202201","202301","202401","202501","202601"],
                         ["202613"],["199604"],["202704"]):
            with self.subTest(periodos=periodos),self.assertRaises(DadoInvalido):
                self.executar(periodos=periodos)
        p=executar_backfill_quarentena(periodos=["202501","202502","202601","202602"])
        self.assertEqual(p["n_requisicoes"],24)
        self.assertFalse(p["homologado"])

    def test_backfill_sem_direitos_nao_aciona_http(self):
        chamadas=[0]
        def transporte(*,url,timeout,limite):
            chamadas[0]+=1
            return fake_transport(url=url,timeout=timeout,limite=limite)
        with self.assertRaises(PermissionError):
            self.executar(gravar=True,banco=self.banco,
                          direitos_confirmados=False,transporte=transporte)
        self.assertEqual(chamadas[0],0)

    def test_mapa_alterado_noutro_trimestre_nao_passa(self):
        def falso(*,url,timeout,limite):
            x=fake_transport(url=url,timeout=timeout,limite=limite)
            payload=json.loads(x["corpo"])
            payload[1]["D3N"]="Número de informantes"
            x["corpo"]=json.dumps(payload,ensure_ascii=False).encode()
            return x
        with self.assertRaisesRegex(DadoInvalido,"contradiz ID"):
            self.executar(transporte=falso)

    def test_sem_rede_nao_cria_arquivos(self):
        result=executar_backfill_quarentena(periodos=["202502","202601"])
        self.assertEqual(result["status"],"PLANEJADO_SEM_REDE")
        self.assertFalse(self.banco.exists())



    def test_revisao_registrada_em_datas_diferentes_so_afeta_corte_posterior(self):
        class PrimeiraColeta(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026,10,1,10,0,tzinfo=tz)
        class SegundaColeta(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026,10,23,10,0,tzinfo=tz)
        with patch("nivon.pecuaria_sidra_quarentena.datetime", PrimeiraColeta):
            a=self.executar(banco=self.banco,gravar=True)
        def revisado(*,url,timeout,limite):
            x=fake_transport(url=url,timeout=timeout,limite=limite)
            rows=json.loads(x["corpo"])
            for row in rows[1:]:
                if row["D3C"]=="284":
                    row["V"]="115"
            x["corpo"]=json.dumps(rows,ensure_ascii=False).encode()
            return x
        with patch("nivon.pecuaria_sidra_quarentena.datetime", SegundaColeta):
            b=self.executar(banco=self.banco,gravar=True,
                            transporte=revisado)
        self.assertNotEqual(a["ids_capturas"],b["ids_capturas"])
        original=consultar_backfill_quarentena(
            banco=self.banco,especie="BOVINO",periodos=["202502"],
            corte_asof="2026-10-02T00:00:00+00:00")
        atualizado=consultar_backfill_quarentena(
            banco=self.banco,especie="BOVINO",periodos=["202502"],
            corte_asof="2026-10-24T00:00:00+00:00")
        hashes_original={x["sha256_bruto"] for x in original["capturas_conhecidas_no_corte"]}
        hashes_atual={x["sha256_bruto"] for x in atualizado["capturas_conhecidas_no_corte"]}
        self.assertEqual(len(hashes_original),2)
        self.assertEqual(len(hashes_atual),2)
        self.assertFalse(hashes_original & hashes_atual)
        self.assertFalse(original["publicacao_historica_conhecida"])
        self.assertFalse(atualizado["publicacao_permitida"])

    def test_cli_consulta_restrita_sem_rede_ou_escrita(self):
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        from nivon.pecuaria_sidra_backfill import main
        self.executar(banco=self.banco,gravar=True)
        out=StringIO()
        with redirect_stdout(out):
            rc=main(["--periodo","202502","--periodo","202601",
                     "--consultar","--banco",str(self.banco),
                     "--especie","SUINO","--corte",
                     "2026-10-24T00:00:00+00:00"])
        self.assertEqual(rc,0)
        r=json.loads(out.getvalue())
        self.assertEqual(len(r["capturas_conhecidas_no_corte"]),4)
        self.assertFalse(r["publicacao_permitida"])
        error=StringIO()
        with redirect_stderr(error):
            rc=main(["--periodo","202502","--consultar","--rede",
                     "--banco",str(self.banco),"--especie","SUINO",
                     "--corte","2026-10-24T00:00:00+00:00"])
        self.assertEqual(rc,2)
        self.assertEqual(json.loads(error.getvalue())["status"],"BLOQUEADO")

if __name__=="__main__":
    unittest.main()
