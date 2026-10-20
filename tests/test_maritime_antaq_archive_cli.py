"""Offline ANTAQ CLI file safety and default authorization tests."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from nivon.maritime.antaq_archive_cli import inspect_local_antaq_archive


def archive():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("2024Atracacao.txt",
            "IDAtracacao;Ano;Mes;Porto Atracação;Terminal;SGUF\n"
            "99;2024;jan;Santos;Terminal Teste;SP\n")
        z.writestr("2024Carga.txt",
            "IDAtracacao;CDMercadoria;VLPesoCargaBruta;Sentido;Natureza da Carga;Tipo Navegação\n"
            "99;1201;25,00;Embarcados;Granel Sólido;Longo Curso\n")
        z.writestr("2024Mercadoria.txt",
            "CDMercadoria;Nomenclatura Simplificada Mercadoria\n1201;Soja\n")
    return buf.getvalue()


class TestAntaqCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "historico_2024.zip"
        self.path.write_bytes(archive())

    def call(self, **kw):
        opts = dict(year=2024, source_id="ANTAQ_ARCHIVE_FIXTURE",
                    collected_at="2026-10-20T14:00:00Z")
        opts.update(kw)
        return inspect_local_antaq_archive(self.path, **opts)

    def test_requires_explicit_authorization(self):
        with self.assertRaises(PermissionError):
            self.call()

    def test_offline_report_without_storage_side_effect(self):
        result = self.call(rights_verified=True)
        self.assertEqual(result["count_atracacoes_distinct"], 1)
        self.assertEqual(result["count_carga_rows"], 1)
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["file_persisted_to_nivon"])
        self.assertFalse(result["results_persisted_to_nivon"])
        self.assertTrue(self.path.exists())

    def test_symlink_rejected(self):
        alias = Path(self.tmp.name) / "alias.zip"
        alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            inspect_local_antaq_archive(
                alias, year=2024, source_id="ANTAQ", rights_verified=True,
                collected_at="2026-10-20T14:00:00Z",
            )

    def test_wrong_extension_rejected(self):
        fake = Path(self.tmp.name) / "archive.txt"
        fake.write_bytes(archive())
        with self.assertRaises(ValueError):
            inspect_local_antaq_archive(
                fake, year=2024, source_id="ANTAQ", rights_verified=True,
                collected_at="2026-10-20T14:00:00Z",
            )

    def test_asof_without_publication_proof_blocked(self):
        with self.assertRaises(ValueError):
            self.call(rights_verified=True, as_of="2026-10-20T15:00:00Z")

    def test_missing_file_rejected(self):
        with self.assertRaises(ValueError):
            inspect_local_antaq_archive(
                Path(self.tmp.name) / "missing.zip",
                year=2024, source_id="ANTAQ", rights_verified=True,
                collected_at="2026-10-20T14:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
