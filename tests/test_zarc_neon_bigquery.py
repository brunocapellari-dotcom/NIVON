"""ZARC historico: hash, fonte nao homologada, privacidade e gates GCP."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts.zarc_neon_para_bigquery import normalizar,plano,carregar,ZarcBloqueado

def origem(id=1):
    sha="a"*64
    obj={"source_sha256":sha,"linha_fisica":id,"municipio_ibge":"5105259",
         "chave_logica_sha":"b"*64,"conteudo_sha":"c"*64,
         "dados_raw":{"cultura":"soja","janela":8,"risco":None}}
    return {"source_sha256":sha,"linha_fisica":id,"municipio_ibge":"5105259",
       "chave_logica_sha":"b"*64,"conteudo_sha":"c"*64,
       "payload_json":json.dumps(obj),"data_referencia":None,
       "data_publicacao":None,"data_coleta":"2026-10-23T12:00:00+00:00",
       "competencia":"2026/2027","direitos_revisados":False,
       "dados_agronomicos_homologados":False,"raw_backup_verificado":False,
       "tipo_coleta":"REAL_AUTORIZADO"}

def file_at(folder,records):
    p=Path(folder)/"zarc.jsonl"
    with p.open("w") as f:
        for record in records:f.write(json.dumps(record)+"\n")
    p.chmod(0o600)
    return p

class ZarcTest(unittest.TestCase):
    def test_nao_promocao_automatica(self):
        r=normalizar(origem())
        self.assertEqual(r["data_particao"],"2026-10-23")
        self.assertIsNone(r["data_referencia"])
        self.assertIsNone(r["data_publicacao"])
        self.assertFalse(r["apto_modelo"])
        self.assertFalse(r["dados_agronomicos_homologados"])
        self.assertFalse(r["direitos_revisados"])
    def test_hash_preciso(self):
        r=normalizar(origem())
        self.assertEqual(len(r["payload_sha256"]),64)
        self.assertEqual(r["municipio_ibge"],"5105259")
    def test_falha_em_identidade_falsa(self):
        x=origem()
        x["linha_fisica"]=2
        with self.assertRaises(ZarcBloqueado):normalizar(x)
    def test_arquivo_privado(self):
        with tempfile.TemporaryDirectory() as d:
            p=file_at(d,[normalizar(origem(1)),normalizar(origem(2))])
            info=plano(p)
            self.assertEqual(info["rows"],2)
            self.assertFalse(info["cloud_written"])
            self.assertFalse(info["agronomic_homologation"])
    def test_hash_corrompido_bloqueado(self):
        with tempfile.TemporaryDirectory() as d:
            r=normalizar(origem())
            r["payload_sha256"]="0"*64
            p=file_at(d,[r])
            with self.assertRaises(ZarcBloqueado):plano(p)
    def test_dois_identificadores_iguais_bloqueados(self):
        with tempfile.TemporaryDirectory() as d:
            r=normalizar(origem())
            p=file_at(d,[r,r])
            with self.assertRaises(ZarcBloqueado):plano(p)
    def test_zero_gcp_sem_custo_revisado(self):
        with tempfile.TemporaryDirectory() as d:
            p=file_at(d,[normalizar(origem())])
            with patch.dict(os.environ,{"NIVON_GCP_WRITE_APPROVED":"false","NIVON_GCP_COST_REVIEWED":"false"}):
                with self.assertRaises(PermissionError):carregar(p)

if __name__=="__main__":unittest.main()
