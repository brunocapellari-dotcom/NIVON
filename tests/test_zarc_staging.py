"""Testes offline do staging ZARC. Dados 100% sinteticos; nenhum GET/DB cloud."""
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest

from nivon.zarc_stream_mt import COLUNAS
from nivon.zarc_staging import (
    abrir_zarc_staging, importar_zarc_local, comparar_edicoes,
    ErroStagingZarc, SCHEMA,
)
from nivon.registro_snapshots import visao_asof, registrar_snapshot, ErroSnapshot

CATOFF={"datasets":[{"id":"ZARC_JANELAS","source_id":"ZARC",
                    "enabled":False,"collection_authorized":False}]}
T1="2026-10-22T16:00:00-04:00"
T2="2026-10-23T14:00:00Z"

def linha(uf="MT",cultura="Soja",municipio="5105259",portaria="123",dec1="1"):
    d={c:"" for c in COLUNAS}
    d.update({"Nome_cultura":cultura,"Cod_Cultura":"99",
      "Cod_Ciclo":"20","Cod_Solo":"2","geocodigo":municipio,
      "UF":uf,"municipio":"Lucas do Rio Verde","Cod_Clima":"7",
      "Nome_Clima":"Tropical","Cod_Outros_Manejos":"1",
      "Nome_Outros_Manejos":"Sequeiro","Produtividade":"3000",
      "Cod_NM":"1","Cod_Munic":"1042","Cod_Meso":"5",
      "Cod_Micro":"6","Portaria":portaria,"SafraIni":"2026",
      "SafraFin":"2027"})
    d.update({f"dec{i}":"" for i in range(1,37)})
    d["dec1"]=dec1
    return d

def CSV(*rows):
    out=io.StringIO(newline="")
    w=csv.DictWriter(out,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return io.BytesIO(out.getvalue().encode("utf-8-sig"))

class TestZarcStaging(unittest.TestCase):
    def setUp(self):
        self.db=abrir_zarc_staging()
        self.addCleanup(self.db.close)
        self.rows=(linha(),linha(uf="GO"),linha(cultura="Milho 2ª Safra",
                                             municipio="5107925"))
    def importar(self, *rows, collected=T1, publicado=None, **opts):
        return importar_zarc_local(self.db,CATOFF,CSV(*rows),coletado_em=collected,
                                   publicacao=publicado,**opts)

    def test_linhas_e_raw_preservados_como_brutos(self):
        r=self.importar(*self.rows)
        self.assertTrue(r["nova_versao"])
        self.assertTrue(r["nova_coleta"])
        self.assertEqual(r["linhas_mt"],2)
        self.assertEqual(r["linhas_total"],3)
        self.assertEqual(r["municipios_mt"],2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM zarc_linhas").fetchone()[0],2)
        original=list(self.db.execute("""SELECT * FROM zarc_linhas
                                       ORDER BY linha_fisica"""))
        self.assertEqual([x["linha_fisica"] for x in original],[1,3])
        self.assertEqual(original[0]["municipio_ibge"],"5105259")
        self.assertEqual(original[0]["municipio_sicor"],"1042")
        raw=json.loads(original[0]["dados_raw_json"])
        self.assertEqual(len(raw),55)
        self.assertEqual(raw["dec1"],"1")
        self.assertEqual(raw["dec36"],"")
        self.assertEqual(r["destino"],"SQLITE_LOCAL_STAGE_SEM_NUVEM")
        self.assertFalse(r["homologado"])
        self.assertFalse(r["publicavel"])

    def test_same_snapshot_replay_and_new_collection(self):
        a=self.importar(*self.rows)
        b=self.importar(*self.rows)
        c=self.importar(*self.rows,collected=T2)
        self.assertEqual(a["sha256"],b["sha256"])
        self.assertFalse(b["nova_versao"] or b["nova_coleta"])
        self.assertFalse(c["nova_versao"])
        self.assertTrue(c["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_edicoes").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_coletas").fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_linhas").fetchone()[0],2)

    def test_duas_edicoes_versoes_inalteradas(self):
        a=self.importar(*self.rows)
        b=self.importar(linha(dec1="2"),*self.rows[1:],collected=T2)
        self.assertNotEqual(a["sha256"],b["sha256"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_edicoes").fetchone()[0],2)
        comparacao=comparar_edicoes(self.db,a["sha256"],b["sha256"])
        self.assertEqual(comparacao["chaves_com_decendios_ou_conteudo_alterados"],1)
        self.assertEqual(comparacao["chaves_ambiguas"],0)
        self.assertEqual(comparacao["chaves_adicionadas"],0)
        self.assertEqual(comparacao["chaves_ausentes"],0)
        self.assertFalse(comparacao["apto_backtest"])

    def test_duplicata_logica_nao_suprimida(self):
        a=self.importar(linha(),linha())
        self.assertEqual(a["linhas_mt"],2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_linhas").fetchone()[0],2)
        b=self.importar(linha(),linha(dec1="2"),collected=T2)
        c=comparar_edicoes(self.db,a["sha256"],b["sha256"])
        self.assertEqual(c["chaves_ambiguas"],1)
        self.assertEqual(c["chaves_com_decendios_ou_conteudo_alterados"],0)

    def test_invalid_file_rolls_back_ledger_too(self):
        b=linha(municipio="wrong")
        with self.assertRaises(ErroStagingZarc):
            self.importar(linha(),b)
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_linhas").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_edicoes").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_coletas").fetchone()[0],0)

    def test_no_mt_rolls_back(self):
        with self.assertRaises(ErroStagingZarc):
            self.importar(linha(uf="GO"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_real_dataset_gate_cannot_be_bypassed(self):
        before=self.db.total_changes
        with self.assertRaises(PermissionError):
            self.importar(linha(),origem="REAL_AUTORIZADO",
                         autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                         evidencia_direitos="DOC-2026-001")
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM zarc_edicoes").fetchone()[0],0)
        self.assertFalse(CATOFF["datasets"][0]["enabled"])

    def test_sem_publicacao_nao_serve_asof(self):
        self.importar(linha(),publicado=None)
        out=visao_asof(self.db,dataset_id="ZARC_JANELAS",
              corte_coleta="2026-10-24T00:00:00Z",
              corte_publicacao="2026-10-24")
        self.assertIsNone(out)

    def test_conflicting_same_hash_publication(self):
        a=self.importar(linha(),publicado="2026-10-21")
        with self.assertRaises(ErroSnapshot):
            self.importar(linha(),publicado="2026-10-20")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM zarc_edicoes").fetchone()[0],1)

    def test_savepoint_preserves_external_transaction(self):
        self.db.execute("SAVEPOINT outer")
        self.importar(linha())
        self.db.execute("ROLLBACK TO SAVEPOINT outer")
        self.db.execute("RELEASE SAVEPOINT outer")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM zarc_linhas").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_schema_invalid_and_oversized_fields(self):
        r=linha()
        r["dec2"]="B"*501
        with self.assertRaises(ErroStagingZarc):self.importar(r)
        r=linha()
        r.pop("dec36")
        stream=CSV(r)  # csv.DictWriter inclui campo vazio; usar cabeçalho quebrado
        corrupt=io.BytesIO(CSV(linha()).getvalue().replace(b"dec36",b"dec88"))
        with self.assertRaises(ErroStagingZarc):
            importar_zarc_local(self.db,CATOFF,corrupt,coletado_em=T1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_temporalidade_and_limits(self):
        with self.assertRaises(ErroStagingZarc):
            self.importar(linha(),collected="2026-10-22T12:00:00")
        with self.assertRaises(ErroStagingZarc):
            self.importar(linha(),max_linhas=0)
        with self.assertRaises(ErroStagingZarc):
            self.importar(linha(),linha(),max_linhas=1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_diff_nonexistent_hash_fails(self):
        a=self.importar(linha())
        with self.assertRaises(ErroStagingZarc):
            comparar_edicoes(self.db,a["sha256"],"a"*64)

    def test_persists_on_local_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path=d+"/zarc_local.sqlite"
            db=abrir_zarc_staging(path)
            try:
                a=importar_zarc_local(db,CATOFF,CSV(linha()),
                                     coletado_em=T1)
                self.assertTrue(a["nova_versao"])
            finally:
                db.close()
            db=abrir_zarc_staging(path)
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM zarc_linhas").fetchone()[0],1)
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            finally:
                db.close()

if __name__=="__main__":
    unittest.main()
