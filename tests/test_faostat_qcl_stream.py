"""Testes end-to-end em ZIP real sintético e SQLite temporário, sem rede."""
import csv
import hashlib
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone

from nivon.faostat_qcl_stream import (
    QCL_CSV, QCL_URL, ErroQCL, executar_qcl,
    extrair_qcl, gravar_snapshot_sqlite, url_qcl_manifest,
)

NOW = "2026-10-21T22:00:00Z"
HEADER = ["Area Code","Area Code (M49)","Area","Item Code","Item",
          "Element Code","Element","Year Code","Year","Unit","Value","Flag","Note"]


def zip_teste(valor="12345", *, filename=QCL_CSV):
    data = io.StringIO()
    writer = csv.writer(data)
    writer.writerow(HEADER)
    writer.writerow(["21","'076","Brazil","236","Soybeans","5510","Production",
                     "2022","2022","t","1111","A",""])
    writer.writerow(["21","'076","Brazil","236","Soybeans","5510","Production",
                     "2023","2023","t",valor,"A",""])
    writer.writerow(["21","'076","Brazil","56","Maize","5510","Production",
                     "2023","2023","t","555","E",""])
    writer.writerow(["231","'840","United States of America","236","Soybeans",
                     "5510","Production","2023","2023","t","999","A",""])
    writer.writerow(["21","'076","Brazil","236","Soybeans","5312","Area harvested",
                     "2023","2023","ha","60000","A",""])
    out=io.BytesIO()
    with zipfile.ZipFile(out,mode="w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename,data.getvalue().encode("utf-8"))
        z.writestr("Production_Crops_Livestock_E_Flags.csv","Flag,Description\nA,Official\n")
    return out.getvalue()


def manifest():
    return {"dominios_prioritarios":[{
        "dominio":"QCL",
        "arquivo_zip_url_somente_referencia":QCL_URL,
        "data_atualizacao_dataset":"2025-12-31T00:00:00"
    }]}


def extrair(blob, *, pais="BRA",cultura="SOJA",inicio=2022,fim=2023, sha=None):
    with io.BytesIO(blob) as f:
        return extrair_qcl(f,sha256_zip=sha or hashlib.sha256(blob).hexdigest(),
                           zip_bytes=len(blob),coleta=NOW,
                           data_atualizacao_fonte="2025-12-31T00:00:00",
                           pais=pais,cultura=cultura,inicio=inicio,fim=fim)


class Resposta:
    status=200
    def __init__(self,url,blob):
        self.url=url
        self.data=io.BytesIO(blob)
        self.headers={"Content-Type":"application/zip",
                      "Content-Length":str(len(blob))}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.data.read(n)


class Abridor:
    def __init__(self,blob):self.blob=blob;self.urls=[]
    def open(self,req,timeout):
        self.urls.append(req.full_url)
        return Resposta(req.full_url,self.blob)


class TestStreamQCL(unittest.TestCase):
    def test_manifest_restringe_url_sem_chamada_nova(self):
        self.assertEqual(url_qcl_manifest(manifest()),QCL_URL)
        bad=manifest()
        bad["dominios_prioritarios"][0]["arquivo_zip_url_somente_referencia"]="https://evil.invalid/x.zip"
        with self.assertRaises(ErroQCL):url_qcl_manifest(bad)

    def test_zip_tem_filtro_e_sem_consumir_milhoes_em_memoria(self):
        result=extrair(zip_teste())
        self.assertEqual(result["selecionadas"],2)
        self.assertEqual(result["linhas_varridas"],5)
        self.assertEqual([x["ano"] for x in result["observacoes"]],[2022,2023])
        self.assertEqual([x["valor"] for x in result["observacoes"]],["1111","12345"])
        self.assertEqual(result["observacoes"][1]["unidade"],"t")
        self.assertIsNone(result["observacoes"][1]["data_publicacao"])
        self.assertFalse(result["habilitado_para_publicacao"])
        self.assertTrue(result["completo_no_arquivo"])
        self.assertEqual(extrair(zip_teste(),pais="BRA",cultura="MILHO",inicio=2023,fim=2023)["selecionadas"],1)
        self.assertEqual(extrair(zip_teste(),pais="USA",cultura="SOJA",inicio=2023,fim=2023)["selecionadas"],1)

    def test_download_explicito_and_stage_local_idempotente(self):
        blob=zip_teste()
        ab=Abridor(blob)
        with self.assertRaises(PermissionError):
            executar_qcl(manifest=manifest(),abridor=ab)
        self.assertFalse(ab.urls)
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,"faostat.db")
            first=executar_qcl(manifest=manifest(),abridor=ab,executar=True,
                               coleta=NOW,arquivo_banco=path,inicio=2022,fim=2023)
            self.assertEqual(first["persistencia"]["inseridas"],2)
            twice=executar_qcl(manifest=manifest(),abridor=ab,executar=True,
                               coleta=NOW,arquivo_banco=path,inicio=2022,fim=2023)
            self.assertEqual(twice["persistencia"]["inseridas"],0)
            self.assertEqual(twice["persistencia"]["duplicadas_ignoradas"],2)
            # Nova edição revisa uma observação sem sobrescrever o histórico.
            revised=extrair(zip_teste("12800"))
            a=gravar_snapshot_sqlite(revised,arquivo_banco=path)
            self.assertEqual(a["inseridas"],2)
            with sqlite3.connect(path) as con:
                n=con.execute("SELECT COUNT(*) FROM faostat_qcl_snapshot").fetchone()[0]
                versions=con.execute("SELECT DISTINCT valor FROM faostat_qcl_snapshot WHERE ano=2023").fetchall()
            self.assertEqual(n,4)
            self.assertEqual({x[0] for x in versions},{"12345","12800"})
        self.assertEqual(len(ab.urls),2)
        self.assertEqual(ab.urls,[QCL_URL,QCL_URL])

    def test_zip_traversal_missing_member_rejeitados(self):
        with self.assertRaises(ErroQCL):
            extrair(zip_teste(filename="../evil.csv"))
        with self.assertRaises(ErroQCL):
            extrair(zip_teste(filename="wrong.csv"))
        with self.assertRaises(ErroQCL):
            extrair(b"notzip" * 100)

    def test_dados_inconsistentes_erro_fatal(self):
        for bad in ("nan","-1","1E999"):
            with self.subTest(v=bad),self.assertRaises(ErroQCL):
                extrair(zip_teste(bad))
        with self.assertRaises(ErroQCL):
            extrair(zip_teste(),inicio=2024,fim=2024)
        with self.assertRaises(ErroQCL):
            extrair(zip_teste(),sha="not-a-real-hash")
        with self.assertRaises(ErroQCL):
            executar_qcl(manifest=manifest(),executar=True,cultura="foo")

    def test_sem_persistencia_implicita(self):
        ab=Abridor(zip_teste())
        r=executar_qcl(manifest=manifest(),executar=True,abridor=ab,
                       coleta=NOW,inicio=2023,fim=2023)
        self.assertEqual(r["selecionadas"],1)
        self.assertIsNone(r["persistencia"])
        self.assertFalse(r["validacao_operacional"])


if __name__=="__main__":
    unittest.main()
