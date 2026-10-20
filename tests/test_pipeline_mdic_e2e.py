"""E2E sintético: manifesto -> HTTP fake -> CSV privado -> SQLite -> backup."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from nivon.mdic_manifesto import catalogar_arquivos_mdic
from nivon.mdic_aquisicao import baixar_csv_anual_mdic
from nivon.mdic_exportacao import HEADER
from nivon.ingestao_mdic import ingerir_arquivo_mdic,observar_mdic_asof_coleta,ErroIngestaoMDIC
from nivon.registro_snapshots import abrir_registro
from nivon.backup_sqlite import criar_backup,restaurar_backup

URL="https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/ncm/EXP_2026.csv"
HTML=('<html><a href="'+URL+'">EXP</a></html>').encode()
ROW={"CO_ANO":"2026","CO_MES":"09","CO_NCM":"12019000","CO_UNID":"10",
     "CO_PAIS":"160","SG_UF_NCM":"MT","CO_VIA":"01","CO_URF":"081",
     "QT_ESTAT":"1","KG_LIQUIDO":"2000","VL_FOB":"800"}
CSV=(";".join(HEADER)+"\n"+";".join(ROW[k] for k in HEADER)+"\n").encode()
CAT={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                  "enabled":True,"collection_authorized":True}]}
class Response:
    status=200
    headers={"Content-Type":"text/csv"}
    def __init__(self):self.content=io.BytesIO(CSV)
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return URL
    def read(self,n):return self.content.read(n)
class Opener:
    def open(self,req,timeout):
        assert req.full_url==URL
        return Response()
class TestMDICPontaAPonta(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name);os.chmod(self.root,0o700)
        self.manifest=catalogar_arquivos_mdic(HTML,ano_inicial=2026,
                          ano_final=2026,exigir_completo=False)
        self.db=abrir_registro(":memory:");self.addCleanup(self.db.close)
    def baixar(self):
        return baixar_csv_anual_mdic(manifesto=self.manifest,
            item=self.manifest["arquivos"][0],catalogo=CAT,
            diretorio_privado=self.root,
            direitos=frozenset({"COLETA","ARMAZENAMENTO"}),
            evidencia_direitos="TESTE-ISOLADO-NAO-OFICIAL",
            permitir_rede=True,abridor=Opener())
    def guardar(self,meta,**extra):
        return ingerir_arquivo_mdic(self.db,CAT,caminho=meta["arquivo_local"],
             ano=2026,direcao="EXPORTACAO",granularidade="NCM",
             codigos=frozenset({"12019000"}),
             coletado_em=extra.pop("coletado_em","2026-10-20T14:30:00Z"),
             sha256_esperado=extra.pop("sha256_esperado",meta["sha256"]),**extra)
    def asof(self,db=None):
        return observar_mdic_asof_coleta(db or self.db,dataset_id="MDIC_COMEX_NCM",
            ano=2026,direcao="EXPORTACAO",corte_coleta="2026-10-20T19:00:00Z",
            incluir_sinteticos=True)
    def test_fluxo_mock_transfer_parser_ledger_backup_restore(self):
        f=self.baixar();r=self.guardar(f)
        self.assertEqual(f["sha256"],r["sha256"])
        x=self.asof()
        self.assertEqual(x["conteudo"]["recortes"][0]["peso_liquido_kg"],2000)
        self.assertEqual(x["conteudo"]["recortes"][0]["valor_fob_usd"],800)
        self.assertFalse(x["dados_homologados"])
        backup=self.root/"backup.sqlite"
        snap=criar_backup(self.db,backup)
        path=self.root/"restore.sqlite"
        restaurar_backup(backup,path,sha256_esperado=snap["sha256"])
        with abrir_registro(str(path)) as db:
            self.assertEqual(self.asof(db)["sha256"],f["sha256"])
    def test_arquivo_alterado_entre_transferencia_e_ingestao_nao_registra(self):
        meta=self.baixar()
        Path(meta["arquivo_local"]).write_bytes(CSV.replace(b"800",b"900"))
        with self.assertRaisesRegex(ErroIngestaoMDIC,"diverge do SHA"):
            self.guardar(meta)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
    def test_uso_real_sem_sha_esperado_bloqueado(self):
        meta=self.baixar()
        with self.assertRaises(PermissionError):
            self.guardar(meta,tipo="REAL_AUTORIZADO",sha256_esperado=None,
                autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                evidencia_direitos="TESTE-ISOLADO-NAO-OFICIAL")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
    def test_capturas_repetidas_deduplicam_snapshot(self):
        f=self.baixar();self.guardar(f)
        f2=self.baixar()
        r=self.guardar(f2,coletado_em="2026-10-20T16:00:00Z")
        self.assertFalse(r["novo_snapshot"])
        self.assertTrue(r["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_coletas").fetchone()[0],2)
