"""E2E sintetico: conexoes tipadas -> RAW imutavel GCS -> JSONL -> BQ planejado."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import date

from nivon.conectores_fontes_prioritarias import (
    CONAB_URL, SGS_URL, normalizar, ErroFonteNuvem,
)
from nivon.conectores_google_cloud import (
    cloud_config, obter_https, construir_jsonl, enviar_lote_gcp, plano_url,
    ErroConectorCloud, executar_fonte,
)
from nivon.carga_bigquery_fontes import planejar_carga


class _Blob:
    def __init__(self):
        self.content=None
        self.size=None
        self.metadata=None
    def exists(self):
        return self.content is not None
    def reload(self):
        return None
    def upload_from_string(self, value,content_type=None,if_generation_match=None):
        assert if_generation_match==0
        assert content_type
        self.content=value
        self.size=len(value)


class _Bucket:
    def __init__(self):
        self.items={}
    def blob(self,name):
        return self.items.setdefault(name,_Blob())


class _Storage:
    def __init__(self):
        self.buckets={}
    def bucket(self,bucket):
        return self.buckets.setdefault(bucket,_Bucket())


class _Response:
    def __init__(self,data,url,mime="application/json",status=200):
        self.data=data
        self.url=url
        self.headers={"Content-Type":mime}
        self.status=status
    def geturl(self):
        return self.url
    def read(self,n):
        return self.data[:n]
    def __enter__(self): return self
    def __exit__(self,*args): return False


class _HTTP:
    def __init__(self,payload,source=None,mime="application/json"):
        self.payload=payload
        self.source=source
        self.mime=mime
    def open(self,req,timeout):
        return _Response(self.payload,self.source or req.full_url,self.mime)


ENV={
    "NIVON_GCP_COLLECT_ENABLED":"true",
    "NIVON_ZERO_COST_BQ_APPROVED":"true",
    "NIVON_BQ_PROJECT":"nivon-data",
    "NIVON_BQ_DATASET":"nivon_staging",
    "NIVON_GCS_BUCKET":"nivon-private-raw",
    "NIVON_FONTE_BCB_SGS_TAXA_SELIC_DIARIA_ATIVA":"true",
    "NIVON_FONTE_BCB_PTAX_ATIVA":"true",
    "NIVON_FONTE_CONAB_ARMAZENS_CAPACIDADE_ATIVA":"true",
}
SGS_RAW=b'[{"data":"22/10/2026","valor":"0,055"}]'
PTAX_RAW=json.dumps({"value":[{"dataHoraCotacao":"2026-10-22T13:00:00",
  "cotacaoCompra":5.22,"cotacaoVenda":5.24,"tipoBoletim":"Intermediário",
  "paridadeCompra":1,"paridadeVenda":1}]}).encode()


def conab_fake():
    head=("identificacao_armazem;dsc_especie_armazem;dsc_tipo_armazem;"
          "dsc_tipo_entidade;dsc_tipo_pessoa;nom_municipio;cod_ibge;uf;"
          "qtd_capacidade_estatica(t);qtd_capacidade_expedicao(t);"
          "qtd_capacidade_recepcao(t);latitude;longitude;"
          "nome_armazenador;endereco;email\n")
    body=("ARMAZEM-1;A GRANEL;SILO;PRIVADO;PJ;Sorriso;5107925;MT;"
          "100,50;0;0;;;EMPRESA_PRIVADA;ENDERECO;EMAIL\n")
    return (head+body).encode("cp1252")


class TestFontesGoogleCloud(unittest.TestCase):
    def test_pipeline_selic_realistas_sem_cloud_real(self):
        storage=_Storage()
        posts=[]
        def carga(arquivo,cfg):
            plan=planejar_carga(arquivo=arquivo,project_id=cfg["projeto"],
                               dataset_id=cfg["dataset"])
            rows=[json.loads(x) for x in Path(arquivo).read_text(encoding="utf-8").splitlines()]
            posts.append(rows)
            return dict(plan,executado=True)
        out=executar_fonte("BCB_SGS_TAXA_SELIC_DIARIA",
                          cliente_http=_HTTP(SGS_RAW),storage_client=storage,
                          load_callback=carga,ambiente=ENV,agora="2026-10-23T11:00:00Z")
        self.assertEqual(out["observacoes"],1)
        self.assertTrue(out["bigquery"]["executado"])
        self.assertEqual(posts[0][0]["dataset_id"],"BCB_SGS_TAXA_SELIC_DIARIA")
        self.assertEqual(posts[0][0]["campos"]["fonte"],"BCB_SGS")
        self.assertFalse(out["publicacao_editorial"])
        self.assertFalse(posts[0][0]["campos"]["aprovado_para_publicacao"])
        self.assertEqual(len(storage.bucket("nivon-private-raw").items),1)
        repeat=executar_fonte("BCB_SGS_TAXA_SELIC_DIARIA",
                          cliente_http=_HTTP(SGS_RAW),storage_client=storage,
                          load_callback=carga,ambiente=ENV,agora="2026-10-24T11:00:00Z")
        self.assertFalse(repeat["gcs"]["novo"])
        self.assertEqual(posts[0][0]["fingerprint"],posts[1][0]["fingerprint"])

    def test_ptax_planner_adapter_e_lados(self):
        url=plano_url("BCB_PTAX",inicio="2026-10-21",fim="2026-10-22")
        raw=obter_https("BCB_PTAX",url,cliente=_HTTP(PTAX_RAW))
        lote=normalizar("BCB_PTAX",raw,origem=url,coletado_em="2026-10-23T11:00:00Z")
        self.assertEqual(len(lote["registros"]),2)
        self.assertEqual({r["campos"]["lado"] for r in lote["registros"]},{"COMPRA","VENDA"})
        self.assertTrue(all(r["natureza"]=="INFORMADO" for r in lote["registros"]))
        self.assertNotEqual(lote["registros"][0]["valor"],lote["registros"][1]["valor"])

    def test_conab_parser_qc_pii_ausente_no_jsonl(self):
        raw=conab_fake()
        lote=normalizar("CONAB_ARMAZENS_CAPACIDADE",raw,origem=CONAB_URL,
                        coletado_em="2026-10-23T12:00:00Z")
        self.assertEqual(lote["qa"]["estado"],"CONSISTENCIA_INTERNA_OK_SEM_HOMOLOGACAO")
        self.assertEqual(lote["registros"][0]["valor"],100.5)
        self.assertEqual(lote["registros"][0]["referencia"],"2026-10-23")
        self.assertTrue(lote["registros"][0]["campos"]["capacidade_nao_estoque"])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"out.jsonl"
            rawpath=f"gs://nivon-private-raw/raw/CONAB_ARMAZENS_CAPACIDADE/{lote['sha256']}.bin"
            out=construir_jsonl(lote,gcs_uri=rawpath,destino=p)
            self.assertEqual(out["linhas"],1)
            text=p.read_text(encoding="utf-8")
            self.assertNotIn("EMPRESA_PRIVADA",text)
            self.assertNotIn("EMAIL",text)
            self.assertIn("codigo_ibge_nao_homologado",text)
        with self.assertRaises(ErroFonteNuvem):
            normalizar("CONAB_ARMAZENS_CAPACIDADE",b"<html>blocked</html>",
                origem=CONAB_URL,coletado_em="2026-10-23T12:00:00Z")

    def test_cloud_gate_bloqueia_cada_fonte_e_budget(self):
        for k in ("NIVON_GCP_COLLECT_ENABLED","NIVON_ZERO_COST_BQ_APPROVED"):
            env=dict(ENV)
            env[k]="false"
            with self.subTest(k=k),self.assertRaises(PermissionError):
                cloud_config(env)
        env=dict(ENV)
        env.pop("NIVON_FONTE_BCB_SGS_TAXA_SELIC_DIARIA_ATIVA")
        with self.assertRaises(PermissionError):
            executar_fonte("BCB_SGS_TAXA_SELIC_DIARIA",
                cliente_http=_HTTP(SGS_RAW),ambiente=env)
        with self.assertRaises(PermissionError):
            executar_fonte("IMEA_WORKBOOK_LEGADO_STAGING",ambiente=ENV)

    def test_http_failclosed_waf_redirect_mime(self):
        with self.assertRaises(ErroConectorCloud):
            obter_https("BCB_SGS_TAXA_SELIC_DIARIA","https://evil.com/")
        with self.assertRaises(ErroConectorCloud):
            obter_https("BCB_SGS_TAXA_SELIC_DIARIA",SGS_URL,cliente=_HTTP(
                b"<html>WAF</html>","https://api.bcb.gov.br/outro",mime="text/html"))
        with self.assertRaises(ErroConectorCloud):
            obter_https("BCB_SGS_TAXA_SELIC_DIARIA",SGS_URL,
                        cliente=_HTTP(b"<html>Request Rejected</html>",mime="text/plain"))
        with self.assertRaises(ErroConectorCloud):
            obter_https("BCB_SGS_TAXA_SELIC_DIARIA",SGS_URL,
                        cliente=_HTTP(b"{}",mime="text/html"))

    def test_hash_fonte_inalterada_em_coleta_nova_e_revisao_distinta(self):
        now="2026-10-23T11:00:00Z"
        lote=normalizar("BCB_SGS_TAXA_SELIC_DIARIA",SGS_RAW,
                         origem=SGS_URL,coletado_em=now)
        out=normalizar("BCB_SGS_TAXA_SELIC_DIARIA",
                       b'[{"data":"22/10/2026","valor":"0,056"}]',
                       origem=SGS_URL,coletado_em=now)
        with tempfile.TemporaryDirectory() as d:
            path=f"gs://nivon-private-raw/raw/BCB_SGS_TAXA_SELIC_DIARIA/{lote['sha256']}.bin"
            path2=f"gs://nivon-private-raw/raw/BCB_SGS_TAXA_SELIC_DIARIA/{out['sha256']}.bin"
            construir_jsonl(lote,gcs_uri=path,destino=Path(d)/"old.jsonl")
            construir_jsonl(out,gcs_uri=path2,destino=Path(d)/"new.jsonl")
            first=json.loads((Path(d)/"old.jsonl").read_text())
            second=json.loads((Path(d)/"new.jsonl").read_text())
            self.assertNotEqual(first["fingerprint"],second["fingerprint"])
            self.assertEqual(first["identidade"],second["identidade"])

    def test_gcs_objeto_incoerente_bloqueia_replay(self):
        from nivon.conectores_google_cloud import upload_raw_gcs
        lote=normalizar("BCB_SGS_TAXA_SELIC_DIARIA",SGS_RAW,origem=SGS_URL,
                        coletado_em="2026-10-23T11:00:00Z")
        storage=_Storage()
        one=upload_raw_gcs(lote,bucket="nivon-private-raw",client=storage)
        self.assertTrue(one["novo"])
        blob=list(storage.bucket("nivon-private-raw").items.values())[0]
        blob.metadata={"sha256":"x"*64}
        with self.assertRaises(ErroConectorCloud):
            upload_raw_gcs(lote,bucket="nivon-private-raw",client=storage)


if __name__=="__main__":
    unittest.main()
