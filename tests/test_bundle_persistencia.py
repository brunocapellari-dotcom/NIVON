"""Backup conjunto NIVON com prova de restore e falhas adversariais offline."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.bundle_persistencia import (
    salvar_ponto_recuperacao, verificar_ponto_recuperacao,
    recuperar_ponto, ErroBundle,
)
from nivon.outbox_briefing import abrir_outbox, agendar_briefing
from nivon.progresso_store import abrir_progresso
from nivon.portos_store import abrir_historico_portos


class TestBundlePersistencia(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.p=Path(self.tmp.name)
        self.root=self.p/"backups"
        self.root.mkdir(mode=0o700)
        self.paths={name:self.p/(name+".sqlite") for name in
                    ("conab","portos","outbox")}
        self.db={
            "conab":abrir_progresso(self.paths["conab"]),
            "portos":abrir_historico_portos(self.paths["portos"]),
            "outbox":abrir_outbox(self.paths["outbox"]),
        }
        for i,(name,db) in enumerate(self.db.items()):
            db.execute("CREATE TABLE exemplo (chave TEXT PRIMARY KEY, valor INTEGER)")
            db.execute("INSERT INTO exemplo VALUES (?,?)",(name,i+1))
            db.commit()
        m="Briefing sintético"
        agendar_briefing(
            self.db["outbox"],dia_local="2026-10-20",
            destinatario_hmac="a"*64,
            briefing={"texto":m,"sha256":hashlib.sha256(m.encode()).hexdigest(),
                      "status":"PREPARADO_SEM_ENVIO"},
            agora="2026-10-20T12:00:00+00:00",
            auditoria_aprovada=True,
        )

    def tearDown(self):
        for db in self.db.values():
            try:
                db.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def salvar(self,ident="snapshot_20261020"):
        return salvar_ponto_recuperacao(
            bancos=self.db,destino_raiz=self.root,snapshot_id=ident,
            escritores_pausados=True,coletado_em="2026-10-20T12:00:00+00:00")

    def test_bundle_integridade_permissao_recovery(self):
        r=self.salvar()
        self.assertFalse(r["cloud_duravel"])
        self.assertEqual(set(r["bancos"]),{"conab","portos","outbox"})
        for path in (self.root/"snapshot_20261020").iterdir():
            self.assertEqual(path.stat().st_mode & 0o077,0)
        prova=verificar_ponto_recuperacao(
            raiz=self.root,snapshot_id="snapshot_20261020")
        self.assertEqual(prova["status"],"VERIFICADO_LOCAL")
        self.assertTrue(prova["manifest"]["consistencia_entre_bancos_nao_garantida"])
        # Recupera em local novo. Não necessita source DB aberto.
        for db in self.db.values(): db.close()
        x=recuperar_ponto(
            raiz=self.root,snapshot_id="snapshot_20261020",
            destino_novo=self.p/"restore")
        self.assertTrue(x["requires_manual_cutover"])
        for i,name in enumerate(("conab","portos","outbox")):
            with sqlite3.connect(self.p/"restore"/(name+".sqlite")) as db:
                self.assertEqual(
                    db.execute("SELECT valor FROM exemplo WHERE chave=?",(name,)).fetchone()[0],
                    i+1,
                )
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        with sqlite3.connect(self.p/"restore/outbox.sqlite") as db:
            self.assertEqual(
                db.execute("SELECT status FROM briefing_outbox").fetchone()[0],
                "PENDING")

    def test_sem_pausar_escritores_bloqueia(self):
        with self.assertRaises(PermissionError):
            salvar_ponto_recuperacao(
                bancos=self.db,destino_raiz=self.root,
                snapshot_id="snapshot_20261020",coletado_em="2026-10-20T12:00:00+00:00")
        self.assertEqual(list(self.root.iterdir()),[])

    def test_duplicate_id_nao_sobrescreve(self):
        self.salvar()
        with self.assertRaises(ErroBundle):
            self.salvar()
        self.assertTrue((self.root/"snapshot_20261020/manifest.json").is_file())

    def test_hash_corrompido_impede_restore(self):
        self.salvar()
        arquivo=self.root/"snapshot_20261020/conab.sqlite"
        with arquivo.open("ab") as f: f.write(b"ALTERACAO")
        with self.assertRaises(ErroBundle):
            verificar_ponto_recuperacao(raiz=self.root,snapshot_id="snapshot_20261020")
        with self.assertRaises(ErroBundle):
            recuperar_ponto(raiz=self.root,snapshot_id="snapshot_20261020",
                            destino_novo=self.p/"restore")
        self.assertFalse((self.p/"restore").exists())

    def test_manifest_caminho_hostil_bloqueia(self):
        self.salvar()
        manifest=self.root/"snapshot_20261020/manifest.json"
        data=json.loads(manifest.read_text())
        data["bancos"]["conab"]["filename"]="../../../../etc/passwd"
        manifest.write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaises(ErroBundle):
            verificar_ponto_recuperacao(raiz=self.root,snapshot_id="snapshot_20261020")

    def test_snapshots_incompletos_nao_sao_publicados(self):
        self.db["portos"].close()
        with self.assertRaises(sqlite3.Error):
            self.salvar()
        self.assertEqual(list(self.root.iterdir()),[])

    def test_identificador_traversal_proibido(self):
        for ident in ("..","../fora",".hidden","//","a"*100):
            with self.subTest(ident=ident),self.assertRaises(ErroBundle):
                self.salvar(ident)

    def test_raiz_symlink_bloqueada(self):
        alias=self.p/"alias"
        alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ErroBundle):
            salvar_ponto_recuperacao(
                bancos=self.db,destino_raiz=alias,
                snapshot_id="snapshot_20261020",
                escritores_pausados=True,coletado_em="2026-10-20T12:00:00+00:00")

    def test_diretorio_destino_existente_nao_apaga(self):
        self.salvar()
        destino=self.p/"restore"
        destino.mkdir()
        protegido=destino/"prova.txt"
        protegido.write_text("NAO APAGAR")
        with self.assertRaises(ErroBundle):
            recuperar_ponto(
                raiz=self.root,snapshot_id="snapshot_20261020",
                destino_novo=destino)
        self.assertEqual(protegido.read_text(),"NAO APAGAR")


if __name__=="__main__":
    unittest.main()
