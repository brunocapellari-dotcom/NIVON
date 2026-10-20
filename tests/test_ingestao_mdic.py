import tempfile
import sqlite3
import unittest
from pathlib import Path
from nivon.registro_snapshots import abrir_registro
from nivon.backup_sqlite import criar_backup,restaurar_backup
from nivon.ingestao_mdic import ingerir_arquivo_mdic,observar_mdic_asof_coleta,ErroIngestaoMDIC
from nivon.mdic_exportacao import HEADER

CAT={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                  "enabled":False,"collection_authorized":False}]}
def row(fob="800"):
    d=dict(CO_ANO="2026",CO_MES="09",CO_NCM="12019000",CO_UNID="10",
           CO_PAIS="160",SG_UF_NCM="MT",CO_VIA="01",CO_URF="081",
           QT_ESTAT="1",KG_LIQUIDO="2000",VL_FOB=fob)
    return ";".join(d[k] for k in HEADER)
class TestMDICIngestao(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)
        self.csv=self.dir/"EXP_2026.csv"
        self.csv.write_text(";".join(HEADER)+"\n"+row()+"\n")
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)
    def ingerir(self,**kw):
        return ingerir_arquivo_mdic(self.db,CAT,caminho=self.csv,ano=2026,
              direcao="EXPORTACAO",granularidade="NCM",
              codigos=frozenset({"12019000"}),
              coletado_em=kw.pop("coletado_em","2026-10-20T12:00:00Z"),**kw)
    def visao(self,cut="2026-10-21T00:00:00Z",sinteticos=True):
        return observar_mdic_asof_coleta(self.db,dataset_id="MDIC_COMEX_NCM",
                ano=2026,direcao="EXPORTACAO",corte_coleta=cut,
                incluir_sinteticos=sinteticos)
    def test_ingestao_e_conteudo_sem_cnpj(self):
        r=self.ingerir()
        self.assertTrue(r["novo_snapshot"])
        v=self.visao()
        self.assertEqual(v["conteudo"]["recortes"][0]["valor_fob_usd"],800)
        self.assertFalse(v["publicacao_permitida"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_mdic_agregados").fetchone()[0],1)
    def test_second_collect_dedup(self):
        self.ingerir()
        r=self.ingerir(coletado_em="2026-10-20T14:00:00Z")
        self.assertFalse(r["novo_snapshot"])
        self.assertTrue(r["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_mdic_agregados").fetchone()[0],1)
    def test_revision_respects_asof(self):
        self.ingerir()
        self.csv.write_text(";".join(HEADER)+"\n"+row("999")+"\n")
        self.ingerir(coletado_em="2026-10-21T12:00:00Z")
        self.assertEqual(self.visao(cut="2026-10-20T18:00:00Z")["conteudo"]["recortes"][0]["valor_fob_usd"],800)
        self.assertEqual(self.visao(cut="2026-10-21T15:00:00Z")["conteudo"]["recortes"][0]["valor_fob_usd"],999)
    def test_real_requires_catalog_gate(self):
        with self.assertRaises(PermissionError):self.ingerir(tipo="REAL_AUTORIZADO")
        with self.assertRaises(PermissionError):
            self.ingerir(tipo="REAL_AUTORIZADO",
                autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                evidencia_direitos="DOC-2026-001")
    def test_synthetic_hidden_by_default(self):
        self.ingerir()
        self.assertIsNone(self.visao(sinteticos=False))
    def test_different_filter_same_sha_blocked(self):
        self.ingerir()
        with self.assertRaises(ErroIngestaoMDIC):
            ingerir_arquivo_mdic(self.db,CAT,caminho=self.csv,ano=2026,
              direcao="EXPORTACAO",granularidade="NCM",
              codigos=frozenset({"12019000","31021010"}),
              coletado_em="2026-10-20T14:00:00Z")
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM nivon_coletas").fetchone()[0],1,
            "ingestão recusada nunca deve registrar coleta adicional")
    def test_backup_restore_aggregate_and_ledger(self):
        self.ingerir()
        backup=self.dir/"copia.sqlite"
        r=criar_backup(self.db,backup)
        restored=self.dir/"restaurado.sqlite"
        restaurar_backup(backup,restored,sha256_esperado=r["sha256"])
        with abrir_registro(str(restored)) as db:
            x=db.execute("SELECT count(*) FROM nivon_mdic_agregados").fetchone()[0]
            self.assertEqual(x,1)
            self.assertEqual(db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],1)
    def test_data_corte_obrigatoria(self):
        self.ingerir()
        with self.assertRaises(ErroIngestaoMDIC):
            self.visao(cut="2026-10-20")

    def test_falha_de_insert_em_agregado_reverte_snapshot(self):
        import sqlite3
        from nivon.ingestao_mdic import _tabelas
        _tabelas(self.db)
        self.db.execute("""CREATE TRIGGER falha_mdic BEFORE INSERT ON nivon_mdic_agregados
                           BEGIN SELECT RAISE(ABORT,'falha sintética MDIC'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ingerir()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_coletas").fetchone()[0],0)
