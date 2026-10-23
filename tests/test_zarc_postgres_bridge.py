"""Ponte ZARC -> PostgreSQL: testes 100% sintéticos/offline."""
import csv
import io
import tempfile
import unittest
from pathlib import Path

from nivon.zarc_staging import abrir_zarc_staging, importar_zarc_local
from nivon.zarc_raw_vault import guardar_raw_zarc
from nivon.zarc_postgres_bridge import (
    plano_migracao_zarc,iterar_lotes_postgres,ErroPlanoZarc
)
from nivon.zarc_stream_mt import COLUNAS

CAT={"datasets":[{"id":"ZARC_JANELAS","source_id":"ZARC",
                "enabled":False,"collection_authorized":False}]}
TIME="2026-10-22T14:00:00-04:00"


def amostra(linhas=3):
    s=io.StringIO()
    writer=csv.DictWriter(s,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    writer.writeheader()
    for i in range(linhas):
        d={c:"" for c in COLUNAS}
        d.update({"Nome_cultura":"CULTURA_TESTE","SafraIni":"2026",
          "SafraFin":"2027","Cod_Cultura":"999","Cod_Ciclo":"20",
          "Cod_Solo":"2","geocodigo":"5105259","UF":"MT",
          "municipio":"MUNICIPIO_FICTICIO","Cod_Clima":"7",
          "Nome_Clima":"Tropical","Cod_Outros_Manejos":"1",
          "Nome_Outros_Manejos":"Sequeiro","Produtividade":"0",
          "Cod_NM":"1","Cod_Munic":"1","Cod_Meso":"0",
          "Cod_Micro":"0","Portaria":"TESTE_FICTICIO"})
        for n in range(1,37):
            d[f"dec{n}"]="1" if i%2 else ""
        writer.writerow(d)
    return s.getvalue().encode("utf-8-sig")


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.root=self.dir/"raw"
        self.root.mkdir(mode=0o700)
        self.db=abrir_zarc_staging()
        self.addCleanup(self.db.close)
        self.data=amostra()
        ed=importar_zarc_local(self.db,CAT,io.BytesIO(self.data),
                 coletado_em=TIME)
        self.sha=ed["sha256"]
        guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(self.data),raiz=self.root)

    def test_plano_sem_conexao_externa(self):
        p=plano_migracao_zarc(db=self.db,raiz=self.root,sha256=self.sha)
        self.assertEqual(p["linhas_mt"],3)
        self.assertEqual(p["tipo_ledger"],"SINTETICO")
        self.assertFalse(p["gravacao_postgres_executada"])
        self.assertFalse(p["conexao_externa_realizada"])
        self.assertFalse(p["apto_para_publicacao"])
        self.assertTrue(p["selecionar_banco_agricola_antes_de_aplicar"])

    def test_emite_2_lotes_sem_deduplicar(self):
        batches=list(iterar_lotes_postgres(db=self.db,raiz=self.root,
                                           sha256=self.sha,tamanho_lote=2))
        self.assertEqual([len(x) for x in batches],[2,1])
        r=[x for batch in batches for x in batch]
        self.assertEqual([x["linha_fisica"] for x in r],[1,2,3])
        self.assertEqual(r[0]["municipio_ibge"],"5105259")
        self.assertEqual(len(r[0]["dados_raw"]),55)
        self.assertEqual(r[1]["dados_raw"]["dec1"],"1")
        self.assertFalse(r[1]["risco_interpretado"])
        self.assertFalse(r[1]["homologado"])
        self.assertEqual(len({x["chave_logica_sha"] for x in r}),1)

    def test_detecta_corrupcao_staging_sem_corromper_raw(self):
        self.db.execute("""UPDATE zarc_linhas SET dados_raw_json='{"a":"b"}'
                          WHERE sha256=? AND linha_fisica=2""",(self.sha,))
        with self.assertRaises(ErroPlanoZarc):
            list(iterar_lotes_postgres(db=self.db,raiz=self.root,
                                      sha256=self.sha,tamanho_lote=2))

    def test_validacao_limite_lote(self):
        for n in (0,501,True,"200"):
            with self.subTest(n=n),self.assertRaises(ErroPlanoZarc):
                list(iterar_lotes_postgres(db=self.db,raiz=self.root,
                                          sha256=self.sha,tamanho_lote=n))

    def test_raw_ausente_bloqueia_plano(self):
        (self.root/(self.sha+".csv")).unlink()
        with self.assertRaises(Exception):
            plano_migracao_zarc(db=self.db,raiz=self.root,sha256=self.sha)

if __name__=="__main__":
    unittest.main()
