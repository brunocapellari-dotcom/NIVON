"""Teste de integridade real do backup LOCAL da série ambiental, sem rede."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.backup_sqlite import criar_backup, restaurar_backup, ErroBackup
from nivon.series_ambientais import Ambiental, abrir_ambiental, salvar_lote, consultar_asof

def registro(*,sha="a"*64,valor=100.,pub="2026-10-18T11:00:00Z",coleta="2026-10-18T12:00:00Z"):
    return Ambiental(dataset_id="ANA_HIDRO",estacao_id="12345678",data_local="2026-10-17",
        metrica="VAZAO_M3_S",valor=valor,unidade="M3_S",natureza="OBSERVADO",
        origem_sha256=sha,referencia="2026-10-18",publicado_em=pub,
        coletado_em=coleta,evidencia="ANA_SINTETICA_Fixture")

class TestBackupAmbiental(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.db=abrir_ambiental()
        self.addCleanup(self.db.close)

    def _asof(self,db,pub,coleta):
        return consultar_asof(db,dataset_id="ANA_HIDRO",estacao_id="12345678",
            metrica="VAZAO_M3_S",inicio="2026-10-17",fim="2026-10-17",
            corte_publicacao=pub,corte_coleta=coleta)

    def test_backup_reconcilia_versoes_e_coletas(self):
        salvar_lote(self.db,[registro()])
        salvar_lote(self.db,[registro(sha="b"*64,valor=150.,
            pub="2026-10-19T08:00:00Z",coleta="2026-10-19T10:00:00Z")])
        backup=self.root/"ambiente.sqlite"
        manifest=criar_backup(self.db,backup)
        self.assertEqual(manifest["integridade"],"OK")
        restored=self.root/"restaurado.sqlite"
        restaurar_backup(backup,restored,sha256_esperado=manifest["sha256"])
        with abrir_ambiental(str(restored)) as db:
            self.assertEqual(self._asof(db,"2026-10-18T23:00:00Z",
                "2026-10-19T00:00:00Z")[0]["valor"],100.)
            self.assertEqual(self._asof(db,"2026-10-20T00:00:00Z",
                "2026-10-20T00:00:00Z")[0]["valor"],150.)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ambiental_edicoes").fetchone()[0],2)

    def test_backup_corrompido_rejeita_e_nao_sobrescreve(self):
        salvar_lote(self.db,[registro()])
        backup=self.root/"copia.sqlite"
        manifest=criar_backup(self.db,backup)
        b=bytearray(backup.read_bytes())
        b[-1]^=1
        backup.write_bytes(b)
        with self.assertRaises(ErroBackup):
            restaurar_backup(backup,self.root/"restaurado.sqlite",sha256_esperado=manifest["sha256"])
        self.assertFalse((self.root/"restaurado.sqlite").exists())

if __name__=="__main__":
    unittest.main()
