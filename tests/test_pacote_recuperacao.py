import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.pacote_recuperacao import (ErroPacote,criar_pacote_recuperacao,
                                     testar_restore_pacote)

class TestPacoteRecuperacao(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE exemplo (id INTEGER PRIMARY KEY,n INTEGER)")
        self.db.execute("INSERT INTO exemplo VALUES (1,123)")
        self.db.commit()

    def criar(self):
        return criar_pacote_recuperacao(self.db,self.path,nome="nivon_teste")

    def test_backup_e_restore_estrutural(self):
        r=self.criar()
        a=testar_restore_pacote(r["manifesto"],diretorio_temporario=self.path)
        self.assertEqual(a["estado"],"DRILL_LOCAL_APROVADO")
        self.assertEqual(a["tabelas_verificadas"],1)
        self.assertFalse(a["backup_remoto_confirmado"])

    def test_nao_sobrescrever_backup_existente(self):
        self.criar()
        with self.assertRaises(ErroPacote):self.criar()

    def test_traversal_nome_arquivo_rejeitado(self):
        with self.assertRaises(ErroPacote):
            criar_pacote_recuperacao(self.db,self.path,nome="../copia")

    def test_arquivo_alterado_rejeitado(self):
        r=self.criar()
        backup=Path(r["backup"])
        with backup.open("ab") as f:f.write(b"alterado")
        with self.assertRaises(ErroPacote):
            testar_restore_pacote(r["manifesto"],diretorio_temporario=self.path)

    def test_manifesto_tabelas_adulterado_rejeitado(self):
        r=self.criar()
        path=Path(r["manifesto"])
        d=json.loads(path.read_text())
        d["tabelas"]["exemplo"]=999
        path.write_text(json.dumps(d))
        with self.assertRaises(ErroPacote):
            testar_restore_pacote(path,diretorio_temporario=self.path)

    def test_manifesto_traversal_bloqueado(self):
        r=self.criar()
        path=Path(r["manifesto"])
        d=json.loads(path.read_text())
        d["arquivo"]="../segredo.sqlite"
        path.write_text(json.dumps(d))
        with self.assertRaises(ErroPacote):
            testar_restore_pacote(path,diretorio_temporario=self.path)

    def test_manifesto_duplicado_bloqueado(self):
        r=self.criar()
        Path(r["manifesto"]).write_text('{"formato":"NIVON_SQLITE_RECOVERY_V1","formato":"INJETADO"}')
        with self.assertRaises(ErroPacote):
            testar_restore_pacote(r["manifesto"],diretorio_temporario=self.path)

    def test_backup_nao_copia_linhas_para_manifesto(self):
        self.db.execute("CREATE TABLE confidencial (valor TEXT)")
        self.db.execute("INSERT INTO confidencial VALUES ('SECRET_VALUE_TEST')")
        self.db.commit()
        r=self.criar()
        s=Path(r["manifesto"]).read_text(encoding="utf-8")
        self.assertNotIn("SECRET_VALUE_TEST",s)
        self.assertIn("confidencial",s)

    def test_symlink_manifesto_bloqueado(self):
        r=self.criar()
        link=self.path/"link.manifest.json"
        link.symlink_to(Path(r["manifesto"]))
        with self.assertRaises(ErroPacote):
            testar_restore_pacote(link,diretorio_temporario=self.path)
