"""RAW ZARC: testes locais e adversariais, sem fontes reais ou rede."""
import csv
import io
import os
import tempfile
import unittest
from pathlib import Path

from nivon.zarc_raw_vault import guardar_raw_zarc, verificar_raw_zarc, ErroRawZarc
from nivon.zarc_staging import abrir_zarc_staging, importar_zarc_local
from nivon.zarc_stream_mt import COLUNAS

CAT={"datasets":[{"id":"ZARC_JANELAS","source_id":"ZARC",
                  "enabled":False,"collection_authorized":False}]}
TIME="2026-10-22T18:00:00-04:00"


def csv_sintetico(dec1="1"):
    data={c:"" for c in COLUNAS}
    data.update({"Nome_cultura":"CULTURA_TESTE","SafraIni":"2026","SafraFin":"2027",
        "Cod_Cultura":"999","Cod_Ciclo":"20","Cod_Solo":"2",
        "geocodigo":"5105259","UF":"MT","municipio":"MUNICIPIO_TESTE",
        "Cod_Clima":"7","Nome_Clima":"Tropical","Cod_Outros_Manejos":"1",
        "Nome_Outros_Manejos":"Sequeiro","Produtividade":"0",
        "Cod_NM":"1","Cod_Munic":"300","Cod_Meso":"0",
        "Cod_Micro":"0","Portaria":"FICTICIO"})
    for i in range(1,37):
        data[f"dec{i}"]=dec1 if i==1 else ""
    s=io.StringIO()
    w=csv.DictWriter(s,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    w.writeheader()
    w.writerow(data)
    return s.getvalue().encode("utf-8-sig")


class TestRawZarc(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"private_raw"
        self.root.mkdir(mode=0o700)
        self.db=abrir_zarc_staging()
        self.addCleanup(self.db.close)

    def stage(self,body):
        return importar_zarc_local(self.db,CAT,io.BytesIO(body),coletado_em=TIME)

    def test_roundtrip_sha_idempotencia(self):
        body=csv_sintetico()
        edition=self.stage(body)
        a=guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        self.assertEqual(a["sha256"],edition["sha256"])
        self.assertEqual(a["bytes"],len(body))
        self.assertTrue(a["novo_arquivo"])
        self.assertEqual(a["linhas_mt_ledger"],1)
        self.assertFalse(a["nuvem_duravel"])
        b=guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        self.assertFalse(b["novo_arquivo"])
        self.assertEqual(len(list(self.root.glob("*.csv"))),1)
        self.assertEqual(verificar_raw_zarc(db=self.db,raiz=self.root,sha256=edition["sha256"])["integridade"],"SHA256_CONFERE_LEDGER")

    def test_registro_desconhecido_nao_cria_raw(self):
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(csv_sintetico()),
                             raiz=self.root)
        self.assertFalse(list(self.root.glob("*.csv")))
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_arquivo_diferente_e_versoes_distintas(self):
        a=csv_sintetico("1")
        b=csv_sintetico("2")
        ea=self.stage(a)
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(b),raiz=self.root)
        self.stage(b)
        ra=guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(a),raiz=self.root)
        rb=guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(b),raiz=self.root)
        self.assertNotEqual(ra["sha256"],rb["sha256"])
        self.assertEqual(len(list(self.root.glob("*.csv"))),2)
        self.assertEqual(ea["sha256"],ra["sha256"])

    def test_adulteracao_detectada_sem_sobrescrever(self):
        body=csv_sintetico()
        sha=self.stage(body)["sha256"]
        guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        p=self.root/(sha+".csv")
        with p.open("wb") as f:
            f.write(b"corrupt")
        with self.assertRaises(ErroRawZarc):
            verificar_raw_zarc(db=self.db,raiz=self.root,sha256=sha)
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        self.assertEqual(p.read_bytes(),b"corrupt")

    def test_nao_aceitar_symlinks_root_modo_publico(self):
        body=csv_sintetico()
        self.stage(body)
        self.root.chmod(0o755)
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        self.root.chmod(0o700)
        link=Path(self.tmp.name)/"alias"
        link.symlink_to(self.root)
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=link)
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz="relative/path")

    def test_nao_acessa_raw_com_hardlink_terceiro(self):
        body=csv_sintetico()
        sha=self.stage(body)["sha256"]
        guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        p=self.root/(sha+".csv")
        h=Path(self.tmp.name)/"hard"
        os.link(p,h)
        with self.assertRaises(ErroRawZarc):
            verificar_raw_zarc(db=self.db,raiz=self.root,sha256=sha)

    def test_staging_real_bloqueado_antes_da_retencao(self):
        body=csv_sintetico()
        with self.assertRaises(PermissionError):
            importar_zarc_local(self.db,CAT,io.BytesIO(body),coletado_em=TIME,
                 origem="REAL_AUTORIZADO",autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                 evidencia_direitos="DOC-2026-001")
        with self.assertRaises(ErroRawZarc):
            guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(body),raiz=self.root)
        self.assertFalse(list(self.root.iterdir()))

if __name__=="__main__":
    unittest.main()
