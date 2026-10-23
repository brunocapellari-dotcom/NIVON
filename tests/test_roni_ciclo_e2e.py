"""Aceitação integrada NIVON RONI: lote atômico + versões + backup/restore.

Sem HTTP, cloud, contas pagas, fonte real nem publicações homologadas.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from nivon.noaa_roni import ErroRONI
from nivon.roni_store import (
    abrir_arquivo_roni, executar_lote_roni, auditar_acervo_roni,
    consultar_arquivo_roni,
)
from nivon.roni_ciclo import (
    processar_ciclo_roni, relatorio_revisoes_roni,
    gerar_backup_roni, validar_backup_roni,
)
from test_pipeline_roni_e2e import fake_source, manifest, T1, T2, T3
from nivon.roni_cli import executar_manifesto_roni


def itens(*samples):
    return [{
        "raw": raw, "sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "coletado_em": when, "classe": "SINTETICO",
        "filename": f"arquivo_{i}.ascii",
    } for i, (raw, when) in enumerate(samples)]


class TestCicloRONIRecuperavel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / "roni.sqlite"
        self.raw = self.root / "raw"
        self.db = abrir_arquivo_roni(self.dbpath)
        self.addCleanup(self.db.close)

    def _importar_versoes(self):
        first = executar_lote_roni(
            self.db, raw_dir=self.raw, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        second = executar_lote_roni(
            self.db, raw_dir=self.raw, raw=fake_source(1953, revised=True),
            coletado_em=T2, instante_registro=T2)
        return first, second

    def test_batch_multiarquivo_atomico_aprovado_com_auditoria_integral(self):
        doc = self.root / "input"
        doc.mkdir()
        for n, raw in (("one.ascii", fake_source()),
                       ("two.ascii", fake_source(1953, revised=True))):
            (doc / n).write_bytes(raw)
        m = manifest(doc, [
            ("one.ascii", T1, "SINTETICO"),
            ("two.ascii", T2, "SINTETICO"),
        ])
        resp = executar_manifesto_roni(
            manifesto=m, modo="executar", banco=self.dbpath,
            raw_dir=self.raw, confirmar_gravacao_local=True)
        self.assertEqual(resp["lotes_processados"], 2)
        self.assertTrue(resp["lote_atomico"])
        self.assertEqual(resp["snapshots_novos"], 2)
        self.assertTrue(resp["auditoria"]["integridade_sqlite"])
        self.assertEqual(resp["auditoria"]["registros_validados"], 84)
        self.assertEqual(len(list(self.raw.glob("*.ascii"))), 2)
        report = relatorio_revisoes_roni(
            self.db, raw_dir=self.raw, corte_em="2026-11-01T00:00:00Z")
        self.assertEqual(report["competencias_revisadas"], 1)
        self.assertEqual(report["competencias_novas"], 12)
        self.assertEqual(report["ultima_competencia"], "1953-12")
        self.assertFalse(report["resultado_enso_preditivo"])

    def test_falha_no_terceiro_arquivo_desfaz_db_e_limpa_novos_raw(self):
        originals = itens(
            (fake_source(), T1),
            (fake_source(1953, revised=True), T2),
            (fake_source(1952, revised=True), T3),
        )
        with self.assertRaisesRegex(ErroRONI, "truncou"):
            processar_ciclo_roni(self.db, raw_dir=self.raw, itens=originals)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM roni_snapshots").fetchone()[0], 0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM roni_valores").fetchone()[0], 0)
        self.assertFalse(list(self.raw.glob("*.ascii")))

    def test_falha_em_lote_preserva_base_anterior_e_conteudo_original(self):
        baseline = executar_lote_roni(
            self.db, raw_dir=self.raw, raw=fake_source(),
            coletado_em=T1, instante_registro=T1)
        before = auditar_acervo_roni(self.db, raw_dir=self.raw)
        with self.assertRaisesRegex(ErroRONI, "truncou"):
            processar_ciclo_roni(self.db, raw_dir=self.raw, itens=itens(
                (fake_source(1953, revised=True), T2),
                (fake_source(1952, revised=True), T3),
            ))
        after = auditar_acervo_roni(self.db, raw_dir=self.raw)
        self.assertEqual(after["snapshots_auditados"], before["snapshots_auditados"])
        self.assertEqual(after["registros_validados"], before["registros_validados"])
        self.assertEqual(len(list(self.raw.glob("*.ascii"))), 1)
        self.assertEqual(
            consultar_arquivo_roni(
                self.db, raw_dir=self.raw, corte_em="2026-11-01T00:00:00Z"
            )["snapshot_sha256"], baseline["sha256"])

    def test_relatorio_temporal_restaura_edicao_e_nao_fabrica_previsao(self):
        first, second = self._importar_versoes()
        executar_lote_roni(
            self.db, raw_dir=self.raw, raw=fake_source(),
            coletado_em=T3, instante_registro=T3)
        prev = relatorio_revisoes_roni(
            self.db, raw_dir=self.raw, corte_em="2026-10-21T13:00:00Z")
        current = relatorio_revisoes_roni(
            self.db, raw_dir=self.raw, corte_em="2026-10-22T13:00:00Z")
        future = relatorio_revisoes_roni(
            self.db, raw_dir=self.raw, corte_em="2026-10-19T13:00:00Z")
        self.assertEqual(prev["snapshot_mais_recente_sha256"], second["sha256"])
        self.assertEqual(current["snapshot_mais_recente_sha256"], first["sha256"])
        self.assertEqual(current["snapshot_anterior_sha256"], second["sha256"])
        self.assertEqual(current["ultima_competencia"], "1952-12")
        self.assertGreater(current["competencias_revisadas"], 0)
        self.assertEqual(future["estado"], "SEM_EDICAO_NO_CORTE")
        self.assertFalse(current["vintage_historico_externo_comprovado"])

    def test_backup_sqlite_raw_gerado_e_validado_e_reutilizavel(self):
        self._importar_versoes()
        destination = self.root / "exportacao"
        result = gerar_backup_roni(self.db, raw_dir=self.raw, destino=destination)
        self.assertEqual(result["estado"], "BACKUP_LOCAL_VERIFICADO_NAO_HOMOLOGADO")
        self.assertEqual(result["snapshots"], 2)
        self.assertTrue((destination / "manifesto_backup.json").is_file())
        self.assertEqual(validar_backup_roni(caminho=destination)["snapshots"], 2)
        restored = abrir_arquivo_roni(destination / "roni.sqlite")
        self.addCleanup(restored.close)
        self.assertEqual(
            auditar_acervo_roni(
                restored, raw_dir=destination / "raw")["registros_validados"], 84)
        self.assertFalse(result["homologado"])

    def test_backup_com_raw_alterado_ou_db_corrompido_bloqueado(self):
        self._importar_versoes()
        backup = self.root / "backup"
        gerar_backup_roni(self.db, raw_dir=self.raw, destino=backup)
        one = next((backup / "raw").glob("*.ascii"))
        saved = one.read_bytes()
        one.write_bytes(b"ADULTERADO")
        with self.assertRaises(ErroRONI):
            validar_backup_roni(caminho=backup)
        one.write_bytes(saved)
        with (backup / "roni.sqlite").open("ab") as fp:
            fp.write(b"INJECAO")
        with self.assertRaises(ErroRONI):
            validar_backup_roni(caminho=backup)

    def test_backup_nao_sobrescreve_destino_existente(self):
        self._importar_versoes()
        folder = self.root / "backup"
        gerar_backup_roni(self.db, raw_dir=self.raw, destino=folder)
        with self.assertRaises(ErroRONI):
            gerar_backup_roni(self.db, raw_dir=self.raw, destino=folder)

    def test_cli_relatorio_backup_e_verificar_backup_em_lote(self):
        self._importar_versoes()
        base = [sys.executable, "-m", "nivon.roni_cli"]
        def call(*args):
            p = subprocess.run([*base, *args], capture_output=True,
                               text=True, timeout=20)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            return json.loads(p.stdout)
        report = call("relatorio", "--banco", str(self.dbpath),
                      "--raw-dir", str(self.raw),
                      "--corte-em", "2026-10-22T12:00:00Z")
        self.assertEqual(report["competencias_revisadas"], 1)
        back = self.root / "bkp_cli"
        result = call("backup", "--banco", str(self.dbpath),
                      "--raw-dir", str(self.raw), "--destino-backup", str(back))
        self.assertEqual(result["snapshots"], 2)
        verified = call("validar-backup", "--destino-backup", str(back))
        self.assertEqual(verified["estado"], "BACKUP_RESTAURAVEL_VALIDADO")


if __name__ == "__main__":
    unittest.main()
