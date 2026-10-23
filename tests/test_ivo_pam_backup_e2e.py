"""E2E de backup portavel do SQLite e bytes content-addressed PAM."""
import hashlib
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from nivon.ivo_pam_backup import (
    ErroBackupPAM, criar_backup_pam, restaurar_backup_pam,
)
from nivon.ivo_pam_operacao import abrir_operacao_pam, processar_captura_pam
from nivon.ivo_pam_ponte_operacional import revisar_capturas_pam
from nivon.sidra_pam import planejar_pam_1612

T = datetime(2026, 10, 22, 14, tzinfo=timezone.utc)


def payload(plano, value):
    return json.dumps([
        {"D1C": "Município (Código)", "D2C": "Variável (Código)",
         "D3C": "Ano (Código)",
         "D4C": "Produto das lavouras temporárias (Código)",
         "V": "Valor", "MN": "Unidade de Medida"},
        {"D1C": plano["municipio_ibge"], "D2C": plano["variavel"],
         "D3C": str(plano["ano"]), "D4C": plano["categoria_c81"],
         "V": value, "MN": "Toneladas"},
    ], ensure_ascii=False).encode("utf-8")


class TestBackupPAM(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cofre = self.root / "cofre"
        self.banco = self.root / "operacional.sqlite"
        db = abrir_operacao_pam(self.banco)
        for city, year, val in (
            ("5107958", 2021, "180"),
            ("5105259", 2024, "740"),
        ):
            plan = planejar_pam_1612(
                municipio_ibge=city, ano=year,
                codigo_produto_c81="2713", codigo_variavel="214",
            )
            processar_captura_pam(
                db=db, raiz=self.cofre, plano=plan,
                payload=payload(plan, val), coletado_em=T,
                origem="TRANSPORTE_TESTE",
            )
        db.close()
        self.zip = self.root / "backup.zip"
        self.restored = self.root / "restaurado"

    def make_backup(self):
        return criar_backup_pam(
            banco=self.banco, cofre=self.cofre, arquivo_zip=self.zip)

    def test_backup_e_restauro_conferidos_e_sem_promocao(self):
        original = self.make_backup()
        self.assertEqual(original["capturas"], 2)
        self.assertEqual(original["vintages"], 2)
        self.assertEqual(original["objetos_e_recibos"], 4)
        self.assertFalse(original["publicacao_autorizada"])
        res = restaurar_backup_pam(
            arquivo_zip=self.zip, destino=self.restored)
        self.assertTrue(res["integridade_local_aprovada"])
        self.assertEqual(res["capturas"], 2)
        self.assertEqual(res["vintages"], 2)
        self.assertFalse(res["registro_canonico_modificado"])
        db = abrir_operacao_pam(self.restored / "operacional.sqlite")
        try:
            out = revisar_capturas_pam(db=db, raiz=self.restored)
            self.assertEqual(out["capturas_consideradas"], 2)
            self.assertTrue(all(not x["liberado_para_promocao"]
                                for x in out["itens"]))
        finally:
            db.close()

    def test_restaura_original_sha_exato(self):
        self.make_backup()
        restaurar_backup_pam(arquivo_zip=self.zip, destino=self.restored)
        for path in self.cofre.rglob("*"):
            if path.is_file():
                other = self.restored / path.relative_to(self.cofre)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 hashlib.sha256(other.read_bytes()).hexdigest())

    def test_nao_sobrescreve_backup_existente(self):
        self.make_backup()
        with self.assertRaises(ErroBackupPAM):
            self.make_backup()

    def test_nao_sobrescreve_restauro_existente(self):
        self.make_backup()
        restaurar_backup_pam(arquivo_zip=self.zip, destino=self.restored)
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(arquivo_zip=self.zip, destino=self.restored)

    def test_zip_com_path_traversal_e_recusado_sem_escrita(self):
        self.make_backup()
        evil = self.root / "evil.zip"
        with zipfile.ZipFile(self.zip) as z, zipfile.ZipFile(evil, "w") as out:
            for info in z.infolist():
                out.writestr(info.filename, z.read(info))
            out.writestr("../../nao_deveria_existir", b"test")
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(arquivo_zip=evil, destino=self.restored)
        self.assertFalse(self.restored.exists())
        self.assertFalse((self.root.parent / "nao_deveria_existir").exists())

    def test_bytes_alterados_no_zip_sao_bloqueados(self):
        self.make_backup()
        altered = self.root / "alterado.zip"
        with zipfile.ZipFile(self.zip) as z, zipfile.ZipFile(altered, "w") as out:
            for info in z.infolist():
                raw = z.read(info)
                if info.filename.endswith(".bin"):
                    raw = raw + b"X"
                out.writestr(info.filename, raw)
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(arquivo_zip=altered, destino=self.restored)
        self.assertFalse(self.restored.exists())

    def test_manifesto_marcado_homologado_e_recusado(self):
        self.make_backup()
        altered = self.root / "fake_approved.zip"
        with zipfile.ZipFile(self.zip) as z, zipfile.ZipFile(altered, "w") as out:
            for info in z.infolist():
                raw = z.read(info)
                if info.filename == "manifesto.json":
                    m = json.loads(raw)
                    m["homologacao_operacional"] = True
                    raw = json.dumps(m).encode()
                out.writestr(info.filename, raw)
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(arquivo_zip=altered, destino=self.restored)

    def test_sqlite_modificado_antes_do_backup_nega(self):
        db = abrir_operacao_pam(self.banco)
        db.execute("UPDATE pam_vintages SET valor=999 WHERE ano=2021")
        db.commit()
        db.close()
        with self.assertRaises(ErroBackupPAM):
            self.make_backup()
        self.assertFalse(self.zip.exists())

    def test_symlink_de_objeto_nega_backup(self):
        path = next((self.cofre / "objetos_sha256").iterdir())
        path.unlink()
        path.symlink_to(self.banco)
        with self.assertRaises(ErroBackupPAM):
            self.make_backup()
        self.assertFalse(self.zip.exists())

    def test_limite_de_quota_aplicado_no_backup_e_restauro(self):
        with self.assertRaises(ErroBackupPAM):
            criar_backup_pam(banco=self.banco, cofre=self.cofre,
                             arquivo_zip=self.zip, max_bytes=1024)
        self.assertFalse(self.zip.exists())
        self.make_backup()
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(
                arquivo_zip=self.zip, destino=self.restored, max_bytes=1024)
        self.assertFalse(self.restored.exists())


if __name__ == "__main__":
    unittest.main()
