"""Testes offline de geração do pacote com RAW e MT exportados."""
import csv
import gzip
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path

from nivon.zarc_pacote_real import criar_pacote
from nivon.zarc_stream_mt import COLUNAS,URL
from nivon.zarc_sinais_ckan import RESOURCE_ID

def csv_fixture():
    b=io.StringIO()
    w=csv.DictWriter(b,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    w.writeheader()
    for uf,nom in [("MT","SOJA TESTE"),("GO","MILHO TESTE"),("MT","MILHO TESTE")]:
        r={c:"" for c in COLUNAS}
        r.update({"Nome_cultura":nom,"SafraIni":"2026","SafraFin":"2027",
          "Cod_Cultura":"99","Cod_Ciclo":"20","Cod_Solo":"2",
          "geocodigo":"5105259","UF":uf,"municipio":"FICTICIO",
          "Cod_Clima":"7","Cod_Outros_Manejos":"1",
          "Cod_Munic":"24","Portaria":"TESTE"})
        w.writerow(r)
    return b.getvalue().encode("utf-8-sig")

def metadata():
    return {
      "fonte_id":"MAPA_ZARC","licenca_declarada":"cc-by",
      "coleta":"2026-10-23T10:00:00Z","revision_id":"pkg-test",
      "atualizado_em":"2026-10-23T09:00:00",
      "recursos":[{"id":RESOURCE_ID,"formato":"CSV",
       "url_somente_referencia":URL,"revision_id":"resource-test",
       "atualizado_em":"2026-10-23T09:00:00"}],
    }

def download_local(*,destino,executar=False):
    assert executar is True
    body=csv_fixture()
    Path(destino).write_bytes(body)
    return {"bytes":len(body),"sha256":hashlib.sha256(body).hexdigest(),
            "mime":"text/csv"}

class TestPacoteReal(unittest.TestCase):
    def test_sem_optin(self):
        with self.assertRaises(PermissionError):
            criar_pacote(destino="/tmp",executar=False)

    def test_licenca_arquivos_e_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            result=criar_pacote(destino=d,executar=True,
                consulta_ckan=metadata,downloader=download_local,
                instante=datetime(2026,10,23,12,tzinfo=timezone.utc))
            self.assertEqual(result["mt_linhas"],2)
            self.assertFalse(result["publicavel"])
            manifest=json.loads((Path(d)/"manifest.json").read_text())
            self.assertEqual(manifest["source_csv_sha256"],
                hashlib.sha256(csv_fixture()).hexdigest())
            self.assertEqual(manifest["mt_municipios"],1)
            self.assertFalse(manifest["postgres_agricola_atualizado"])
            raw=Path(d)/manifest["raw_gzip"]["filename"]
            mt=Path(d)/manifest["mt_jsonl_gzip"]["filename"]
            self.assertEqual(gzip.decompress(raw.read_bytes()),csv_fixture())
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(),
                             manifest["raw_gzip"]["sha256"])
            records=[json.loads(x) for x in gzip.decompress(mt.read_bytes()).splitlines()]
            self.assertEqual(len(records),2)
            self.assertEqual([x["linha_fisica"] for x in records],[1,3])
            self.assertEqual(records[0]["campos_csv"]["Nome_cultura"],"SOJA TESTE")
            self.assertEqual(records[1]["campos_csv"]["Nome_cultura"],"MILHO TESTE")
            self.assertEqual(records[0]["campos_csv"]["dec36"],"")
            self.assertFalse(manifest["publicavel"])
            self.assertFalse(manifest["apto_backtest"])

    def test_sem_limpeza_de_pasta_nao_vazia(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"important"
            p.write_text("preserve")
            with self.assertRaises(Exception):
                criar_pacote(destino=d,executar=True,
                             consulta_ckan=metadata,downloader=download_local)
            self.assertEqual(p.read_text(),"preserve")

    def test_licenca_incorreta_bloqueia_antes_do_download(self):
        with tempfile.TemporaryDirectory() as d:
            def denied():
                x=metadata()
                x["licenca_declarada"]="unknown"
                return x
            with self.assertRaises(Exception):
                criar_pacote(destino=d,executar=True,
                             consulta_ckan=denied,downloader=download_local)
            self.assertEqual(list(Path(d).iterdir()),[])

if __name__=="__main__":
    unittest.main()
