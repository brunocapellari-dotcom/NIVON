"""E2E sintético de backups SQLite CONAB: verificações SHA, WAL e restauração."""
from __future__ import annotations
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from nivon.backup_restore_conab import (
    ErroBackupConab, criar_backup_conab, restaurar_em_diretorio_novo, main,
)
from nivon.progresso_store import abrir_progresso, gravar_progresso
from nivon.registro_snapshots import abrir_registro
from nivon.progresso_conab_historico import (
    preparar_esquema, registrar_progresso_local,
)
from nivon.conab_agrobr import normalizar_progresso

CAT={"datasets":[{"id":"CONAB_PROGRESSO_SEMANAL","source_id":"CONAB",
                  "enabled":False,"collection_authorized":False}]}
URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
AT="2026-10-20T12:00:00+00:00"


def sample(pct=0.35):
    return normalizar_progresso([
        {"cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
         "uf":"MT","semana_atual":"2026-10-18","pct_semana_atual":pct,
         "pct_ano_anterior":0.30,"pct_semana_anterior":0.27,
         "pct_media_5_anos":0.29},
    ],fonte_url=URL,coletado_em=datetime.fromisoformat(AT),
      publicado_em="2026-10-19T12:00:00Z")


class TestBackupRestoreConab(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.legacy=self.root/"original_legacy.db"
        self.canonical=self.root/"original_canonical.db"
        self.backup=self.mkprivate("backup")
        self.restored=self.mkprivate("restored")
        a=abrir_progresso(self.legacy)
        b=abrir_registro(str(self.canonical))
        preparar_esquema(b)
        gravar_progresso(a,sample(),evidence_id="TEST_ONLY",direitos_confirmados=True)
        raw=b"fixture-original-RAW-CONAB"
        registrar_progresso_local(
            b,CAT,registros=sample(),
            sha256_origem=hashlib.sha256(raw).hexdigest(),
            bytes_origem=len(raw),mime_origem="text/plain",coletado_em=AT)
        a.close()
        b.close()

    def mkprivate(self,name):
        p=self.root/name
        p.mkdir(mode=0o700)
        if os.name=="posix":
            p.chmod(0o700)
        return p

    def create(self):
        return criar_backup_conab(self.legacy,self.canonical,self.backup)

    def manifest(self):
        return json.loads((self.backup/"backup_manifesto.json").read_text())

    def test_backup_copia_duas_bases_sem_migracao(self):
        result=self.create()
        self.assertFalse(result["migracao_permitida"])
        self.assertFalse(result["restauracao_testada"])
        self.assertEqual(result["arquivos"],2)
        self.assertEqual(sorted(x.name for x in self.backup.iterdir()),
                         ["backup_manifesto.json","canonico.sqlite","legado.sqlite"])
        doc=self.manifest()
        self.assertEqual(doc["consistencia_entre_bancos"],"NAO_ATOMICA")
        self.assertFalse(doc["contem_raw_externo"])
        self.assertFalse(doc["apto_migracao_producao"])
        self.assertEqual(doc["arquivos"]["LEGADO"]["linhas_por_tabela"]["progresso_observacoes"],1)
        self.assertEqual(doc["arquivos"]["CANONICO"]["linhas_por_tabela"]["nivon_conab_progresso"],1)

    def test_backup_realmente_restaura_em_novo_destino(self):
        self.create()
        original_data=(self.legacy.stat().st_size,self.canonical.stat().st_size)
        result=restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertTrue(result["hashes_iguais"])
        self.assertTrue(result["contagens_iguais"])
        self.assertFalse(result["migracao_ou_publicacao_liberada"])
        self.assertTrue((self.restored/"restauracao_verificada.json").exists())
        with sqlite3.connect(str(self.restored/"legado.sqlite")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM progresso_edicoes").fetchone()[0],1)
        with sqlite3.connect(str(self.restored/"canonico.sqlite")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM nivon_coletas").fetchone()[0],1)
        self.assertEqual(original_data,(self.legacy.stat().st_size,self.canonical.stat().st_size))

    def test_sem_backup_nao_deixa_restaurar(self):
        with self.assertRaises(ErroBackupConab):
            restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertEqual(list(self.restored.iterdir()),[])

    def test_nao_permite_backup_com_mesmo_arquivo_duas_vezes(self):
        with self.assertRaises(ErroBackupConab):
            criar_backup_conab(self.legacy,self.legacy,self.backup)
        self.assertEqual(list(self.backup.iterdir()),[])

    def test_banco_faltante_nao_e_criado(self):
        missing=self.root/"faltante.sqlite"
        with self.assertRaises(ErroBackupConab):
            criar_backup_conab(missing,self.canonical,self.backup)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.backup.iterdir()),[])

    def test_destino_backup_nao_vazio_bloqueado(self):
        sentinel=self.backup/"usuario.txt"
        sentinel.write_text("nao tocar",encoding="utf-8")
        with self.assertRaises(ErroBackupConab):
            self.create()
        self.assertEqual(sentinel.read_text(),"nao tocar")

    def test_destino_restore_nao_vazio_bloqueado(self):
        self.create()
        file=self.restored/"arquivo-existente"
        file.write_text("preservado",encoding="utf-8")
        with self.assertRaises(ErroBackupConab):
            restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertEqual(file.read_text(),"preservado")

    def test_restauração_repetida_nao_sobrescreve(self):
        self.create()
        restaurar_em_diretorio_novo(self.backup,self.restored)
        before=(self.restored/"legado.sqlite").read_bytes()
        with self.assertRaises(ErroBackupConab):
            restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertEqual(before,(self.restored/"legado.sqlite").read_bytes())

    def test_tamper_de_snapshot_falha_antes_de_restaurar(self):
        self.create()
        p=self.backup/"legado.sqlite"
        with p.open("ab") as f:
            f.write(b"ADULTERADO")
        with self.assertRaisesRegex(ErroBackupConab,"hash/tamanho"):
            restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertEqual(list(self.restored.iterdir()),[])

    def test_tamper_do_manifesto_nao_libera_migracao(self):
        self.create()
        path=self.backup/"backup_manifesto.json"
        content=self.manifest()
        content["apto_migracao_producao"]=True
        path.write_text(json.dumps(content),encoding="utf-8")
        with self.assertRaises(ErroBackupConab):
            restaurar_em_diretorio_novo(self.backup,self.restored)

    def test_tamper_hash_no_manifesto_bloqueado(self):
        self.create()
        p=self.backup/"backup_manifesto.json"
        obj=self.manifest()
        obj["arquivos"]["LEGADO"]["sha256"]="0"*64
        p.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaises(ErroBackupConab):
            restaurar_em_diretorio_novo(self.backup,self.restored)

    def test_manifesto_com_chave_duplicada_bloqueado(self):
        self.create()
        path=self.backup/"backup_manifesto.json"
        path.write_text('{"schema":"x","schema":"y"}',encoding="utf-8")
        with self.assertRaises(ErroBackupConab):
            restaurar_em_diretorio_novo(self.backup,self.restored)

    def test_inexistencia_tabela_canonica_na_origem_bloqueia(self):
        with sqlite3.connect(str(self.canonical)) as db:
            db.execute("DROP TABLE nivon_conab_progresso")
        with self.assertRaises(ErroBackupConab):
            self.create()
        self.assertEqual(list(self.backup.iterdir()),[])

    def test_destino_symlink_bloqueado(self):
        p=self.root/"alias"
        try:
            p.symlink_to(self.backup,target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest("symlinks indisponíveis")
        with self.assertRaises(ErroBackupConab):
            criar_backup_conab(self.legacy,self.canonical,p)

    def test_fonte_symlink_bloqueada(self):
        link=self.root/"link_orig.db"
        try:
            link.symlink_to(self.legacy)
        except (OSError,NotImplementedError):
            self.skipTest("symlinks indisponíveis")
        with self.assertRaises(ErroBackupConab):
            criar_backup_conab(link,self.canonical,self.backup)

    @unittest.skipUnless(os.name=="posix","permissões POSIX")
    def test_destino_com_permissao_publica_bloqueia(self):
        self.backup.chmod(0o755)
        with self.assertRaisesRegex(ErroBackupConab,"0700"):
            self.create()

    def test_backup_nao_e_atomico_entre_bancos(self):
        self.create()
        self.assertEqual(self.manifest()["consistencia_entre_bancos"],"NAO_ATOMICA")
        self.assertIn("capturado_inicio_utc",self.manifest()["arquivos"]["LEGADO"])
        self.assertIn("capturado_fim_utc",self.manifest()["arquivos"]["CANONICO"])

    def test_snapshot_arquivos_privados(self):
        self.create()
        if os.name=="posix":
            for path in self.backup.iterdir():
                self.assertEqual(path.stat().st_mode & 0o077,0)
        restaurar_em_diretorio_novo(self.backup,self.restored)
        if os.name=="posix":
            for path in self.restored.iterdir():
                self.assertEqual(path.stat().st_mode & 0o077,0)

    def test_source_wal_mode_preserved_after_snapshot(self):
        with sqlite3.connect(str(self.legacy)) as src:
            original = src.execute("PRAGMA journal_mode").fetchone()[0]
        self.create()
        with sqlite3.connect(str(self.legacy)) as src:
            after = src.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(original.lower(),"wal")
        self.assertEqual(after.lower(),original.lower())
        with sqlite3.connect(str(self.backup/"legado.sqlite")) as back:
            self.assertEqual(back.execute("PRAGMA journal_mode").fetchone()[0].lower(),"delete")

    @unittest.skipUnless(os.name=="posix","permissões POSIX")
    def test_backup_perdeu_privacidade_recusa_restauracao(self):
        self.create()
        self.backup.chmod(0o755)
        with self.assertRaisesRegex(ErroBackupConab,"0700"):
            restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertEqual(list(self.restored.iterdir()),[])

    def test_manifesto_falsificado_nao_dispensa_integrity_check(self):
        self.create()
        damaged=self.backup/"legado.sqlite"
        with damaged.open("r+b") as f:
            f.seek(0)
            f.write(b"NIVON_NOT_SQLITE!")
            f.flush()
            os.fsync(f.fileno())
        info=self.manifest()
        raw=damaged.read_bytes()
        info["arquivos"]["LEGADO"]["sha256"]=hashlib.sha256(raw).hexdigest()
        (self.backup/"backup_manifesto.json").write_text(
            json.dumps(info),encoding="utf-8")
        with self.assertRaises((ErroBackupConab,sqlite3.Error)):
            restaurar_em_diretorio_novo(self.backup,self.restored)
        self.assertEqual(list(self.restored.iterdir()),[])

    def test_cli_backup_e_restore(self):
        args_backup=["backup","--legado",str(self.legacy),"--canonico",
                     str(self.canonical),"--destino",str(self.backup)]
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(args_backup),0)
        self.assertEqual(json.loads(out.getvalue())["arquivos"],2)
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["restaurar","--backup",str(self.backup),
                                   "--destino",str(self.restored)]),0)
        self.assertTrue(json.loads(out.getvalue())["integridade_sqlite"]=="ok")

    def test_cli_invalid_missing_target(self):
        missing=self.root/"missing"
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exc:
            main(["backup","--legado",str(self.legacy),"--canonico",
                  str(self.canonical),"--destino",str(missing)])
        self.assertEqual(exc.exception.code,2)
        self.assertFalse(missing.exists())


if __name__=="__main__":
    unittest.main()
