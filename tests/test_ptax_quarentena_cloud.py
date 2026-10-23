"""E2E PTAX: arquivos externos em quarentena e objetos GCS fictícios."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from nivon.ptax_quarentena_coleta import (
    ErroQuarentenaPTAX, receber_amostra_ptax, listar_amostras_ptax,
)
from nivon.ptax_google_cloud import (
    ErroExportacaoPTAX, preparar_objetos_gcs_ptax, enviar_objetos_gcs_ptax,
)
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.registro_snapshots import abrir_registro

PLANO=planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-19",fim="2026-10-20",
)[0]
RAW=(b'{"value":[{"cotacaoCompra":5.10000,"cotacaoVenda":5.20000,'
     b'"dataHoraCotacao":"2026-10-20 13:03:00",'
     b'"tipoBoletim":"Fechamento"}]}')
VAZIO=b'{"@odata.context":"x","value":[]}'


def manifesto(buf=RAW,headers=None):
    return {
        "moeda":"USD","consulta_url":PLANO["url"],
        "coletado_em":"2026-10-20T18:00:00+00:00","status_http":200,
        "cabecalhos_http":headers if headers is not None else {
            "Content-Type":"application/json; charset=utf-8",
            "Content-Length":str(len(buf)),
            "Date":"Tue, 20 Oct 2026 18:00:00 GMT",
        },
        "raw_sha256":sha256(buf).hexdigest(),
        "fonte_declarada":"BCB_PTAX",
    }


class FalsoBlob:
    def __init__(self, owner, key):
        self.owner=owner
        self.key=key
    def upload_from_string(self, data, *, content_type,
                           if_generation_match, timeout):
        assert if_generation_match == 0 and timeout == 30
        assert content_type == "application/json"
        if self.key in self.owner.files:
            raise RuntimeError("precondição GCS falhou")
        self.owner.files[self.key]=data


class FalsoBucket:
    def __init__(self):
        self.files={}
    def blob(self,key):
        return FalsoBlob(self,key)


class FalsoGCS:
    def __init__(self):
        self.destino=FalsoBucket()
    def bucket(self,nome):
        return self.destino


class TestQuarentenaPTAX(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def armazenar(self,buf=RAW,meta=None):
        return receber_amostra_ptax(
            self.db,raw=buf,manifesto=meta if meta is not None
            else manifesto(buf),
        )

    def test_fluxo_e2e_importar_validar_e_preparar_nuvem(self):
        entrada=self.armazenar()
        self.assertEqual(entrada["status"],"AMOSTRA_EXTERNA_NAO_HOMOLOGADA")
        self.assertEqual(entrada["boletins"],1)
        self.assertTrue(entrada["nova_versao"])
        self.assertFalse(entrada["aprovado_para_ledger_operacional"])
        rows=listar_amostras_ptax(self.db)
        self.assertEqual(len(rows),1)
        preparado=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=entrada["evento_sha256"],
            bucket="nivon-arquivo-autorizado",
        )
        self.assertEqual(preparado["status"],
                         "EXPORTACAO_GCS_PREPARADA_SEM_ENVIO")
        self.assertEqual(len(preparado["objetos"]),2)
        self.assertEqual(preparado["objetos"][0]["bytes"],RAW)
        self.assertFalse(preparado["upload_executado"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        with self.assertRaises(PermissionError):
            enviar_objetos_gcs_ptax(preparado)

    def test_repeticao_e_coletas_distintas(self):
        self.armazenar()
        self.assertFalse(self.armazenar()["nova_versao"])
        segunda={**manifesto(),
                 "coletado_em":"2026-10-20T18:01:00+00:00"}
        self.assertTrue(self.armazenar(meta=segunda)["nova_versao"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_quarentena_raw").fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_quarentena_eventos").fetchone()[0],2)

    def test_odata_vazio_e_uma_ausencia_de_registro(self):
        r=self.armazenar(VAZIO)
        self.assertEqual(r["validacao_json"],"SEM_COTACAO_NA_RESPOSTA")
        self.assertEqual(r["boletins"],0)
        self.assertTrue(r["vazio"])
        self.assertFalse(r["publicavel"])

    def test_html_nao_se_converte_em_odata_vazio(self):
        with self.assertRaises(ErroQuarentenaPTAX):
            self.armazenar(b"<html>no data</html>")

    def test_json_duplicado_e_nextlink_sao_recusados(self):
        for buf in (
            b'{"value":[],"value":[]}',
            b'{"value":[],"@odata.nextLink":"https://bad"}',
        ):
            with self.subTest(buf=buf),self.assertRaises(ErroQuarentenaPTAX):
                self.armazenar(buf)

    def test_cotacao_futura_e_horario_de_coleta_impossivel(self):
        futuro=RAW.replace(b"2026-10-20",b"2026-10-21")
        with self.assertRaises(ErroQuarentenaPTAX):
            self.armazenar(futuro)
        msg={**manifesto(),"coletado_em":"2026-10-20T14:00:00+00:00"}
        with self.assertRaises(ErroQuarentenaPTAX):
            self.armazenar(meta=msg)

    def test_manifesto_e_mime_corrompidos(self):
        for change in (
            {"raw_sha256":"a"*64},
            {"status_http":302},
            {"fonte_declarada":"OUTRA"},
            {"consulta_url":PLANO["url"]+"&$orderby=foo"},
            {"cabecalhos_http":{"content-type":"text/html"}},
        ):
            with self.subTest(change=change),self.assertRaises(ErroQuarentenaPTAX):
                self.armazenar(meta={**manifesto(),**change})

    def test_update_e_delete_bloqueados_por_triggers(self):
        self.armazenar()
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute(
                "UPDATE nivon_ptax_quarentena_raw SET raw=?", (b"broken",))
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM nivon_ptax_quarentena_eventos")
        self.assertEqual(len(listar_amostras_ptax(self.db)),1)

    def test_corruptela_detectada_ao_reler(self):
        self.armazenar()
        self.db.execute("DROP TRIGGER protecao_nivon_ptax_quarentena_raw_update")
        self.db.execute(
            "UPDATE nivon_ptax_quarentena_raw SET raw=?", (b"broken",))
        with self.assertRaisesRegex(ErroQuarentenaPTAX,"corrompido"):
            listar_amostras_ptax(self.db)

    def test_rollback_externo_da_ingestao(self):
        self.db.execute("SAVEPOINT teste")
        self.armazenar()
        self.db.execute("ROLLBACK TO SAVEPOINT teste")
        self.db.execute("RELEASE SAVEPOINT teste")
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='nivon_ptax_quarentena_raw'").fetchone())

    def test_upload_gcs_exige_direitos_e_orcamento(self):
        e=self.armazenar()
        p=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=e["evento_sha256"],
            bucket="nivon-arquivo",
        )
        for kw in (
            {"permitir_upload":True},
            {"permitir_upload":True,"referencia_direitos":"REVISAO_2026"},
        ):
            with self.subTest(kw=kw),self.assertRaises(PermissionError):
                enviar_objetos_gcs_ptax(p,cliente=FalsoGCS(),**kw)

    def test_gcs_mock_aplica_generation_zero(self):
        e=self.armazenar()
        p=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=e["evento_sha256"],
            bucket="nivon-arquivo",
        )
        falso=FalsoGCS()
        kw={"permitir_upload":True,
            "referencia_direitos":"ODBL_ARQUIVAMENTO_INTERNO",
            "referencia_custo":"APROVACAO_FICTICIA_CI",
            "cliente":falso}
        res=enviar_objetos_gcs_ptax(p,**kw)
        self.assertEqual(res["quantidade"],2)
        self.assertFalse(res["publicavel"])
        self.assertEqual(len(falso.destino.files),2)
        with self.assertRaisesRegex(ErroExportacaoPTAX,"incompleto"):
            enviar_objetos_gcs_ptax(p,**kw)

    def test_cli_importa_amostra_no_sqlite_local(self):
        from scripts.importar_ptax_quarentena import main
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            raw_file=base/"raw.json"
            manifest_file=base/"manifest.json"
            banco=base/"quarentena.db"
            raw_file.write_bytes(RAW)
            manifest_file.write_text(json.dumps(manifesto()),encoding="utf-8")
            r=main(["--raw",str(raw_file),"--manifesto",
                    str(manifest_file),"--banco",str(banco)])
            self.assertEqual(r["status"],"AMOSTRA_EXTERNA_NAO_HOMOLOGADA")
            with sqlite3.connect(banco) as db:
                self.assertEqual(len(listar_amostras_ptax(db)),1)

    def test_gcs_prefixo_inseguro(self):
        e=self.armazenar()
        for prefixo in ("/tmp","../fora","nivel//erro",""):
            with self.subTest(p=prefixo),self.assertRaises(ErroExportacaoPTAX):
                preparar_objetos_gcs_ptax(
                    self.db,evento_sha256=e["evento_sha256"],
                    bucket="nivon-arquivo",prefixo=prefixo,
                )


if __name__=="__main__":
    unittest.main()
