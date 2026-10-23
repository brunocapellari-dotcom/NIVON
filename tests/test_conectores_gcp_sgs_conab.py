"""E2E sintetico de conectores CONAB SICARM e BCB SGS11 no mesmo bridge GCP."""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone

from nivon.coletor_conab_sicarm_gcp import (
    CONAB_SICARM,OPERACOES, baixar_txt_conab, preparar_agregado,
    executar_conab_cloud, ErroConabCloud,
)
from nivon.conectores_publicos_gcp import coletar_selic_diaria
from nivon.bcb_sgs_selic import URL_PONTUAL
from scripts.coletar_sgs_google_cloud import executar_sgs


class FakeResp:
    def __init__(self,data,url,mime):
        self.status=200
        self.data=data
        self.url=url
        self.headers={"Content-Type":mime}
    def geturl(self):return self.url
    def read(self,n):return self.data[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class FakeOpener:
    def __init__(self,data,url,mime):
        self.data=data
        self.url=url
        self.mime=mime
    def open(self,req,timeout):
        return FakeResp(self.data,self.url,self.mime)

class FakeBlob:
    def __init__(self):
        self.data=None
        self.metadata={}
        self.size=0
    def exists(self):return self.data is not None
    def reload(self):pass
    def upload_from_filename(self,file,content_type,if_generation_match,timeout):
        assert if_generation_match == 0
        self.data=Path(file).read_bytes()
        self.size=len(self.data)

class FakeBucket:
    def __init__(self):self.items={}
    def exists(self):return True
    def blob(self,obj):
        return self.items.setdefault(obj,FakeBlob())

class FakeStorage:
    def __init__(self):self.buckets={}
    def bucket(self,b):
        return self.buckets.setdefault(b,FakeBucket())

def sicarm_raw():
    head=("identificacao_armazem;dsc_especie_armazem;dsc_tipo_armazem;"
          "dsc_tipo_entidade;dsc_tipo_pessoa;nom_municipio;cod_ibge;uf;"
          "qtd_capacidade_estatica(t);qtd_capacidade_expedicao(t);"
          "qtd_capacidade_recepcao(t);latitude;longitude;"
          "nome_armazenador;endereco;email\n")
    row="SYN-01;GRANEL;SILO;PJ;PJ;Sorriso;5107925;MT;100,50;0;0;;;EMPRESA_SECRETA;RUA_SECRETA;EMAIL_SECRETO\n"
    return (head+row).encode("cp1252")

SGS=b'[{"data":"22/10/2026","valor":"0,055"}]'


class TestPipelineExtraGCP(unittest.TestCase):
    def test_coleta_sgs_pipeline_cloud_realistic_e2e(self):
        with tempfile.TemporaryDirectory() as directory:
            raw=FakeOpener(SGS,URL_PONTUAL,"application/json")
            store=FakeStorage()
            export=[]
            def loader(*,arquivo,project_id,dataset_id,executar):
                linhas=[json.loads(x) for x in Path(arquivo).read_text().splitlines()]
                export.extend(linhas)
                self.assertEqual(project_id,"nivon-data")
                self.assertTrue(executar)
                return {"executado":True,"linhas":len(linhas)}
            out=executar_sgs(
                base=Path(directory),project_id="nivon-data",
                dataset_id="nivon_staging",bucket="nivon-private-bucket",
                autorizacoes=OPERACOES,evidencia="Autorização de teste explícita",
                executar=True,abridor=raw,storage_client=store,
                bq_loader=loader,instante=datetime(2026,10,23,12,tzinfo=timezone.utc))
            self.assertEqual(out["coleta"]["registros"],1)
            self.assertTrue(out["bigquery_executado"])
            self.assertEqual(export[0]["dataset_id"],"BCB_SGS_TAXA_SELIC_DIARIA")
            self.assertEqual(export[0]["natureza"],"INFORMADO")
            self.assertEqual(export[0]["unidade"],"PERCENTUAL_AO_DIA")
            self.assertFalse(out["publicacao_automatica"])
            self.assertEqual(len(store.bucket("nivon-private-bucket").items),2)

    def test_sgs_bloqueado_sem_autorizacao_ou_mime(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                coletar_selic_diaria(banco=Path(root)/"db",
                    raw_dir=Path(root)/"raw",executar=False)
            with self.assertRaises(ValueError):
                coletar_selic_diaria(banco=Path(root)/"db",
                    raw_dir=Path(root)/"raw",executar=True,
                    autorizacoes=OPERACOES,
                    abridor=FakeOpener(b"<html>falhou</html>",URL_PONTUAL,"text/html"))

    def test_sicarm_sem_pii_no_jsonl_com_original_privado(self):
        with tempfile.TemporaryDirectory() as directory:
            source=FakeOpener(sicarm_raw(),CONAB_SICARM,"text/plain")
            storage=FakeStorage()
            normalized=[]
            def loader(*,arquivo,project_id,dataset_id,executar):
                content=Path(arquivo).read_text(encoding="utf-8")
                self.assertNotIn("EMPRESA_SECRETA",content)
                self.assertNotIn("EMAIL_SECRETO",content)
                normalized.extend([json.loads(x) for x in content.splitlines()])
                return {"executado":True,"linhas":len(normalized)}
            result=executar_conab_cloud(
                base=Path(directory),project_id="nivon-data",
                dataset_id="nivon_staging",bucket="nivon-private-bucket",
                autorizacoes=OPERACOES,evidencia="Autorização de teste explícita",
                privacidade_verificada=True,executar=True,abridor=source,
                storage_client=storage,bq_loader=loader,
                instante=datetime(2026,10,23,12,tzinfo=timezone.utc))
            self.assertEqual(result["municipios"],1)
            self.assertEqual(normalized[0]["dataset_id"],"CONAB_ARMAZENS_CAPACIDADE")
            self.assertTrue(normalized[0]["campos"]["capacidade_cadastrada_nao_estoque"])
            self.assertEqual(result["qa"]["codigos_ibge_nao_conciliados"],1)
            self.assertFalse(result["publicacao_automatica"])
            objects=storage.bucket("nivon-private-bucket").items
            self.assertEqual(len(objects),3)
            original=objects["nivon/raw/original/CONAB_ARMAZENS_CAPACIDADE/"+result["original"]["sha256"]+".raw"]
            self.assertIn(b"EMPRESA_SECRETA",original.data)
            self.assertNotIn("EMPRESA_SECRETA",json.dumps(normalized,ensure_ascii=False))

    def test_conab_privacidade_obrigatoria(self):
        with self.assertRaises(PermissionError):
            executar_conab_cloud(
                base="x",project_id="nivon-data",dataset_id="nivon_staging",
                bucket="privado",autorizacoes=OPERACOES,
                evidencia="Fonte aprovada para uso",privacidade_verificada=False,
                executar=True)

    def test_conab_rejeita_waf_e_raw_invalido(self):
        with self.assertRaises(ErroConabCloud):
            baixar_txt_conab(abridor=FakeOpener(b"<html>Request Rejected",
                                                CONAB_SICARM,"text/plain"))
        with self.assertRaises(ErroConabCloud):
            preparar_agregado(b"<html>",coletado_em="2026-10-23T12:00:00Z")
        with self.assertRaises(ErroConabCloud):
            baixar_txt_conab(abridor=FakeOpener(sicarm_raw(),
                                                "https://site.invalido", "text/plain"))


if __name__=="__main__":
    unittest.main()
