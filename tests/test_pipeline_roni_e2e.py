"""E2E realista offline: arquivos -> pipeline -> SQLite -> revisões -> restart.

Fixtures estritamente sintéticas com calendários NOAA, sem dados reais.
Os testes exercitam persistência, integridade e queries PIT; não homologam ENSO.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nivon.noaa_roni import SEASONS, ErroRONI
from nivon.roni_store import (
    abrir_arquivo_roni, executar_lote_roni, consultar_arquivo_roni,
    panorama_local_roni, auditar_acervo_roni,
)
from nivon.roni_cli import executar_manifesto_roni

T1 = "2026-10-20T12:00:00Z"
T2 = "2026-10-21T12:00:00Z"
T3 = "2026-10-22T12:00:00Z"


def fake_source(last_year=1952, revised=False):
    rows = ["SEAS YR ANOM"]
    for y in range(1950, last_year + 1):
        for month, s in enumerate(SEASONS, 1):
            v = 0.1 + month / 100.0
            if revised and y == 1951 and month == 3:
                v = -0.80
            rows.append(f"{s} {y} {v:+.2f}")
    return ("\n".join(rows) + "\n").encode("ascii")


def manifest(path, items):
    (path / "lotes.json").write_text(
        json.dumps({"schema_version": "1.0", "project": "NIVON",
                    "lotes": [{"arquivo": name, "coletado_em": capture,
                               "classe": cls} for name, capture, cls in items]}),
        encoding="utf-8",
    )
    return path / "lotes.json"


class TestPipelineRONIPersistente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.raw_dir = self.p / "snapshots"
        self.dbpath = self.p / "roni.sqlite"

    def test_persistencia_incremental_revisao_sem_mudanca_reinicio_e_asof(self):
        db = abrir_arquivo_roni(self.dbpath)
        original = fake_source()
        updated = fake_source(1953, revised=True)
        a = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=original,
            coletado_em=T1, instante_registro=T1)
        self.assertEqual(a["estado"], "PRIMEIRA_EDICAO")
        self.assertEqual(a["competencias_novas"], 36)
        self.assertFalse(a["homologado"])
        repeat = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=original,
            coletado_em="2026-10-20T13:00:00Z",
            instante_registro="2026-10-20T13:00:00Z")
        self.assertEqual(repeat["estado"], "SEM_MUDANCA")
        self.assertEqual(repeat["capturas_registradas"], 2)
        b = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=updated,
            coletado_em=T2, instante_registro=T2)
        self.assertEqual(b["estado"], "NOVA_EDICAO_COM_REVISÕES")
        self.assertEqual(b["competencias_novas"], 12)
        self.assertEqual(b["competencias_revisadas"], 1)
        self.assertEqual(panorama_local_roni(
            db, raw_dir=self.raw_dir)["total_edicoes"], 2)
        db.close()
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        prev = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-10-20T13:30:00Z")
        current = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-10-21T13:30:00Z")
        before = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-10-20T11:30:00Z")
        self.assertEqual(before["estado"], "SEM_SNAPSHOT_CONHECIDO_ASOF")
        self.assertEqual(prev["snapshot_sha256"], a["sha256"])
        self.assertEqual(current["snapshot_sha256"], b["sha256"])
        self.assertTrue(current["arquivo_verificado"])
        self.assertFalse(current["pode_treinar_asof"])
        report = panorama_local_roni(db, raw_dir=self.raw_dir)
        self.assertEqual(report["total_capturas"], 3)
        self.assertEqual(report["competencia_ultima"], "1953-12")

    def test_lote_manifesto_passa_preflight_executa_e_e_idempotente(self):
        (self.p / "jan.ascii").write_bytes(fake_source())
        (self.p / "fev.ascii").write_bytes(fake_source(1953, revised=True))
        man = manifest(self.p, [
            ("jan.ascii", T1, "SINTETICO"),
            ("fev.ascii", T2, "SINTETICO")])
        dry = executar_manifesto_roni(manifesto=man)
        self.assertEqual(dry["estado"], "PREFLIGHT_OK_SEM_ESCRITA")
        self.assertEqual(dry["gravacoes"], 0)
        self.assertFalse(self.raw_dir.exists())
        self.assertFalse(self.dbpath.exists())
        with self.assertRaises(PermissionError):
            executar_manifesto_roni(
                manifesto=man, modo="executar",
                banco=self.dbpath, raw_dir=self.raw_dir)
        run = executar_manifesto_roni(
            manifesto=man, modo="executar", banco=self.dbpath,
            raw_dir=self.raw_dir, confirmar_gravacao_local=True)
        self.assertEqual(run["lotes_processados"], 2)
        self.assertEqual(run["http"], 0)
        self.assertEqual(run["resultados"][0]["estado"], "PRIMEIRA_EDICAO")
        self.assertEqual(run["resultados"][1]["estado"], "NOVA_EDICAO_COM_REVISÕES")
        self.assertEqual(run["panoramas"]["SINTETICO"]["total_edicoes"], 2)
        self.assertFalse(run["publicacao"])
        again = executar_manifesto_roni(
            manifesto=man, modo="executar", banco=self.dbpath,
            raw_dir=self.raw_dir, confirmar_gravacao_local=True)
        self.assertEqual(
            [x["estado"] for x in again["resultados"]],
            ["SEM_MUDANCA", "SEM_MUDANCA"])
        self.assertEqual(again["panoramas"]["SINTETICO"]["total_edicoes"], 2)

    def test_preflight_falha_antes_de_qualquer_escrita(self):
        (self.p / "a.ascii").write_bytes(fake_source())
        (self.p / "b.ascii").write_bytes(b"URL NOT NOAA")
        man = manifest(self.p, [("a.ascii", T1, "SINTETICO"),
                                ("b.ascii", T2, "SINTETICO")])
        with self.assertRaises(ErroRONI):
            executar_manifesto_roni(
                manifesto=man, modo="executar", banco=self.dbpath,
                raw_dir=self.raw_dir, confirmar_gravacao_local=True)
        self.assertFalse(self.dbpath.exists())
        self.assertFalse(self.raw_dir.exists())

    def test_alteracao_de_raw_arquivado_e_detectada(self):
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        x = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        (self.raw_dir / (x["sha256"] + ".ascii")).write_bytes(b"CORROMPIDO")
        with self.assertRaisesRegex(ErroRONI, "modificado"):
            consultar_arquivo_roni(db, raw_dir=self.raw_dir, corte_em=T2)
        with self.assertRaises(ErroRONI):
            executar_lote_roni(
                db, raw_dir=self.raw_dir, raw=fake_source(),
                coletado_em=T2, instante_registro=T2)

    def test_arquivo_truncado_em_revisao_nao_altera_indice(self):
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(1953),
            coletado_em=T1, instante_registro=T1)
        with self.assertRaisesRegex(ErroRONI, "truncou"):
            executar_lote_roni(
                db, raw_dir=self.raw_dir, raw=fake_source(1952),
                coletado_em=T2, instante_registro=T2)
        self.assertEqual(
            panorama_local_roni(db, raw_dir=self.raw_dir)["total_edicoes"], 1)

    def test_arquivo_real_retrodatado_nao_engana_primeira_ingestao(self):
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        with self.assertRaisesRegex(ErroRONI, "não pode ser injetado"):
            executar_lote_roni(
                db, raw_dir=self.raw_dir, raw=fake_source(),
                coletado_em=T1, classe="EXTERNO_NAO_HOMOLOGADO",
                instante_registro=T1)
        s = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, classe="EXTERNO_NAO_HOMOLOGADO")
        earlier = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-10-21T13:00:00Z",
            classe="EXTERNO_NAO_HOMOLOGADO")
        self.assertEqual(earlier["estado"], "SEM_SNAPSHOT_CONHECIDO_ASOF")
        now = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-12-01T12:00:00Z",
            classe="EXTERNO_NAO_HOMOLOGADO")
        self.assertEqual(now["snapshot_sha256"], s["sha256"])
        self.assertFalse(now["disponibilidade_historica_noaa_comprovada"])

    def test_retorno_de_edicao_antiga_reativa_vintage_sem_reescrever_raw(self):
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        a = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        b = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(1953, revised=True),
            coletado_em=T2, instante_registro=T2)
        c = executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T3, instante_registro=T3)
        self.assertEqual(c["estado"], "RETORNO_EDICAO_ARQUIVADA")
        self.assertEqual(c["sha256"], a["sha256"])
        self.assertNotEqual(c["sha256"], b["sha256"])
        latest = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-10-22T13:00:00Z")
        before = consultar_arquivo_roni(
            db, raw_dir=self.raw_dir, corte_em="2026-10-21T13:00:00Z")
        self.assertEqual(latest["snapshot_sha256"], a["sha256"])
        self.assertEqual(latest["snapshot_ativo_desde"], "2026-10-22T12:00:00+00:00")
        self.assertEqual(before["snapshot_sha256"], b["sha256"])
        self.assertEqual(panorama_local_roni(
            db, raw_dir=self.raw_dir)["total_edicoes"], 2)
        self.assertEqual(panorama_local_roni(
            db, raw_dir=self.raw_dir)["total_capturas"], 3)

    def test_edicoes_conflitantes_no_mesmo_instante_nao_sao_ordenadas_pelo_sha(self):
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        with self.assertRaisesRegex(ErroRONI, "mesmo instante"):
            executar_lote_roni(
                db, raw_dir=self.raw_dir, raw=fake_source(1953),
                coletado_em=T1, instante_registro=T1)
        self.assertEqual(
            panorama_local_roni(db, raw_dir=self.raw_dir)["total_edicoes"], 1)

    def test_manifesto_impede_caminhos_fora_do_diretorio(self):
        (self.p / "a.ascii").write_bytes(fake_source())
        man = manifest(self.p, [("../a.ascii", T1, "SINTETICO")])
        with self.assertRaisesRegex(ErroRONI, "fora do diretório"):
            executar_manifesto_roni(manifesto=man)
        (self.p / "link.ascii").symlink_to(self.p / "a.ascii")
        man = manifest(self.p, [("link.ascii", T1, "SINTETICO")])
        with self.assertRaisesRegex(ErroRONI, "symlink"):
            executar_manifesto_roni(manifesto=man)

    def test_auditoria_completa_funciona_apos_restauracao_da_base_e_raw(self):
        db = abrir_arquivo_roni(self.dbpath)
        executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(1953, revised=True),
            coletado_em=T2, instante_registro=T2)
        report = auditar_acervo_roni(db, raw_dir=self.raw_dir)
        self.assertEqual(report["snapshots_auditados"], 2)
        self.assertEqual(report["registros_validados"], 84)
        self.assertEqual(report["capturas_auditadas"], 2)
        self.assertFalse(report["homologado"])
        copy_path = self.p / "restore.sqlite"
        target = abrir_arquivo_roni(copy_path)
        db.backup(target)
        target.close()
        db.close()
        restored_raw = self.p / "restored"
        shutil.copytree(self.raw_dir, restored_raw)
        reopened = abrir_arquivo_roni(copy_path)
        self.addCleanup(reopened.close)
        after = auditar_acervo_roni(reopened, raw_dir=restored_raw)
        self.assertEqual(after["registros_validados"], 84)
        self.assertEqual(after["estado"], "ACERVO_LOCAL_INTEGRO_NAO_HOMOLOGADO")
        self.assertFalse(after["vintage_historico_externo_auditado"])

    def test_auditoria_rejeita_valor_sqlite_adulterado(self):
        db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(db.close)
        executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        with db:
            db.execute("UPDATE roni_valores SET anomalia=15 WHERE competencia='1951-03'")
        with self.assertRaisesRegex(ErroRONI, "diverge"):
            auditar_acervo_roni(db, raw_dir=self.raw_dir)

    def test_auditoria_cli_recupera_acervo_sem_qualquer_http(self):
        db = abrir_arquivo_roni(self.dbpath)
        executar_lote_roni(
            db, raw_dir=self.raw_dir, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        db.close()
        result = subprocess.run(
            [sys.executable, "-m", "nivon.roni_cli", "auditar",
             "--banco", str(self.dbpath), "--raw-dir", str(self.raw_dir)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertTrue(report["integridade_sha256"])
        self.assertEqual(report["snapshots_auditados"], 1)
        self.assertFalse(report["homologado"])

    def test_cli_processa_lote_com_uma_unica_invocacao(self):
        (self.p / "jan.ascii").write_bytes(fake_source())
        man = manifest(self.p, [("jan.ascii", T1, "SINTETICO")])
        cmd = [sys.executable, "-m", "nivon.roni_cli", "executar",
               "--manifesto", str(man), "--banco", str(self.dbpath),
               "--raw-dir", str(self.raw_dir), "--confirmar-gravacao-local"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        result = json.loads(proc.stdout)
        self.assertEqual(result["estado"],
                         "LOTES_PERSISTIDOS_OFFLINE_NAO_HOMOLOGADOS")
        self.assertEqual(result["resultados"][0]["competencias_novas"], 36)
        self.assertEqual(len(list(self.raw_dir.glob("*.ascii"))), 1)


if __name__ == "__main__":
    unittest.main()
