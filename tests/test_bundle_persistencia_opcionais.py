"""Snapshots V2 com PTAX e diesel, reversíveis e compatíveis com V1."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.bundle_persistencia import (
    salvar_ponto_recuperacao, verificar_ponto_recuperacao,
    recuperar_ponto, ErroBundle,
)
from nivon.progresso_store import abrir_progresso
from nivon.portos_store import abrir_historico_portos
from nivon.outbox_briefing import abrir_outbox
from nivon.registro_snapshots import abrir_registro
from nivon.anp_diesel_store import abrir_historico_diesel


class TestBundleMultifonte(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.snap=self.root/"snapshots"
        self.snap.mkdir(mode=0o700)
        self.db={
            "conab":abrir_progresso(self.root/"conab.sqlite"),
            "portos":abrir_historico_portos(self.root/"portos.sqlite"),
            "outbox":abrir_outbox(self.root/"outbox.sqlite"),
            "mercados":abrir_registro(self.root/"mercados.sqlite"),
            "diesel":abrir_historico_diesel(self.root/"diesel.sqlite"),
        }
        for i,(k,c) in enumerate(self.db.items()):
            c.execute("CREATE TABLE integridade_sintetica (id INTEGER PRIMARY KEY, v TEXT)")
            c.execute("INSERT INTO integridade_sintetica VALUES (?,?)",(i+1,k))
            c.commit()

    def tearDown(self):
        for conn in self.db.values():
            try:conn.close()
            except sqlite3.Error:pass
        self.tmp.cleanup()

    def salvar(self,names=None,sid="bundle_20261020"):
        if names is None:
            names=("conab","portos","outbox","mercados","diesel")
        return salvar_ponto_recuperacao(
            bancos={x:self.db[x] for x in names},
            destino_raiz=self.snap,snapshot_id=sid,
            escritores_pausados=True,
            coletado_em="2026-10-20T15:00:00+00:00",
        )

    def test_5_bancos_com_hash_e_restore_integral(self):
        b=self.salvar()
        self.assertEqual(set(b["bancos"]),set(self.db))
        proof=verificar_ponto_recuperacao(
            raiz=self.snap,snapshot_id="bundle_20261020",
            bancos_exigidos=frozenset(self.db))
        self.assertEqual(proof["manifest"]["schema"],"NIVON_SQLITE_BUNDLE_V2")
        self.assertEqual(len(proof["bancos"]),5)
        result=recuperar_ponto(
            raiz=self.snap,snapshot_id="bundle_20261020",
            destino_novo=self.root/"restore",
            bancos_exigidos=frozenset(self.db),
        )
        self.assertTrue(result["requires_manual_cutover"])
        for i,name in enumerate(self.db):
            restored=self.root/"restore"/(name+".sqlite")
            self.assertEqual(restored.stat().st_mode & 0o077,0)
            with sqlite3.connect(restored) as db:
                self.assertEqual(db.execute(
                    "SELECT v FROM integridade_sintetica").fetchone()[0],name)

    def test_snapshot_legado_v1_continua_restauravel(self):
        self.salvar(names=("conab","portos","outbox"))
        p=verificar_ponto_recuperacao(
            raiz=self.snap,snapshot_id="bundle_20261020")
        self.assertEqual(p["manifest"]["schema"],"NIVON_SQLITE_BUNDLE_V1")
        self.assertEqual(set(p["bancos"]),{"conab","portos","outbox"})
        with self.assertRaises(ErroBundle):
            verificar_ponto_recuperacao(
                raiz=self.snap,snapshot_id="bundle_20261020",
                bancos_exigidos=frozenset(self.db),
            )
        self.assertFalse((self.root/"restore").exists())
        r=recuperar_ponto(raiz=self.snap,snapshot_id="bundle_20261020",
                          destino_novo=self.root/"restore")
        self.assertEqual(len(r["bancos"]),3)

    def test_um_opcional_permanece_v2(self):
        self.salvar(names=("conab","portos","outbox","mercados"))
        proof=verificar_ponto_recuperacao(
            raiz=self.snap,snapshot_id="bundle_20261020",
            bancos_exigidos=frozenset({"mercados"}))
        self.assertEqual(proof["manifest"]["schema"],"NIVON_SQLITE_BUNDLE_V2")
        self.assertNotIn("diesel",proof["bancos"])

    def test_corromper_banco_diesel_bloqueia_restore(self):
        self.salvar()
        path=self.snap/"bundle_20261020"/"diesel.sqlite"
        with path.open("ab") as f:
            f.write(b"CORROMPIDO")
        with self.assertRaises(ErroBundle):
            recuperar_ponto(raiz=self.snap,snapshot_id="bundle_20261020",
                            destino_novo=self.root/"restore")
        self.assertFalse((self.root/"restore").exists())

    def test_nome_adicional_nao_homologado_recusado(self):
        dados=dict(self.db)
        dados["desconhecido"]=self.db["diesel"]
        with self.assertRaises(ErroBundle):
            salvar_ponto_recuperacao(
                bancos=dados,destino_raiz=self.snap,snapshot_id="bundle_20261020",
                escritores_pausados=True,coletado_em="2026-10-20T15:00:00+00:00")
        self.assertEqual(list(self.snap.iterdir()),[])

    def test_destino_existente_nunca_sobrescrito(self):
        self.salvar()
        dest=self.root/"restore"
        dest.mkdir()
        sentinel=dest/"preservar.txt"
        sentinel.write_text("NAO APAGAR")
        with self.assertRaises(ErroBundle):
            recuperar_ponto(raiz=self.snap,snapshot_id="bundle_20261020",
                            destino_novo=dest)
        self.assertEqual(sentinel.read_text(),"NAO APAGAR")

    def test_manifest_tampered_exclui_moeda_gera_erro(self):
        import json
        self.salvar()
        manifest=self.snap/"bundle_20261020"/"manifest.json"
        obj=json.loads(manifest.read_text())
        obj["bancos"].pop("mercados")
        manifest.write_text(json.dumps(obj))
        with self.assertRaises(ErroBundle):
            verificar_ponto_recuperacao(
                raiz=self.snap,snapshot_id="bundle_20261020",
                bancos_exigidos=frozenset(self.db))


if __name__=="__main__":
    unittest.main()
