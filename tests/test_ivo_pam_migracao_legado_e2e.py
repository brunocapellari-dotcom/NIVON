"""Migração E2E: piloto ZIP legado -> ZIP canônico e restauro auditado."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.ivo_pam_operacao import abrir_operacao_pam, processar_captura_pam
from nivon.ivo_pam_backup import restaurar_backup_pam
from nivon.ivo_pam_migracao_legado import (
    ErroMigracaoPAM, converter_zip_piloto_pam, main,
)
from nivon.sidra_pam import planejar_pam_1612

T = datetime(2026, 10, 23, 14, tzinfo=timezone.utc)


def raw(p, val):
    return json.dumps([
        {"D1C": "Município (Código)", "D2C": "Variável (Código)",
         "D3C": "Ano (Código)",
         "D4C": "Produto das lavouras temporárias (Código)",
         "V": "Valor", "MN": "Unidade de Medida"},
        {"D1C": p["municipio_ibge"], "D2C": p["variavel"],
         "D3C": str(p["ano"]), "D4C": p["categoria_c81"],
         "V": str(val), "MN": "Toneladas"},
    ], ensure_ascii=False).encode("utf-8")


class TestMigracaoLegadoPAM(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = Path(t.name)
        self.root = self.dir / "origem"
        self.root.mkdir()
        self.cofre = self.root / "cofre"
        self.p = planejar_pam_1612(
            municipio_ibge="5107958", ano=2021,
            codigo_produto_c81="2713", codigo_variavel="214",
        )
        with abrir_operacao_pam(self.root / "pam.sqlite") as db:
            for n, val in enumerate((100, 120)):
                processar_captura_pam(
                    db=db, raiz=self.cofre, plano=self.p,
                    payload=raw(self.p, val),
                    coletado_em=T + timedelta(hours=n),
                    origem="TRANSPORTE_TESTE",
                )
            db.commit()
        self.legacy = self.dir / "piloto_legado.zip"
        with zipfile.ZipFile(self.legacy, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(self.root.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(self.root).as_posix())
            z.writestr("resultado_coleta.json", b"{}")
            z.writestr("auditoria.json", b"{}")
        self.new = self.dir / "canonico.zip"

    def test_converte_preservando_capturas_revisoes_e_bytes(self):
        sha_original = hashlib.sha256(self.legacy.read_bytes()).hexdigest()
        res = converter_zip_piloto_pam(
            arquivo_legado=self.legacy, arquivo_canonico=self.new,
        )
        self.assertEqual(res["capturas"], 2)
        self.assertEqual(res["vintages"], 2)
        self.assertEqual(res["zip_original_sha256"], sha_original)
        self.assertTrue(self.new.is_file())
        self.assertEqual(hashlib.sha256(self.legacy.read_bytes()).hexdigest(),
                         sha_original)
        self.assertEqual(res["promocoes"], 0)
        self.assertFalse(res["direitos_de_uso_verificados"])
        restored = restaurar_backup_pam(
            arquivo_zip=self.new, destino=self.dir / "restaurado",
        )
        self.assertEqual(restored["capturas"], 2)
        self.assertEqual(restored["vintages"], 2)
        self.assertFalse(restored["registro_canonico_modificado"])

    def test_zip_sem_manifesto_historico_nao_vira_prova_de_licenca(self):
        r = converter_zip_piloto_pam(
            arquivo_legado=self.legacy, arquivo_canonico=self.new,
        )
        self.assertFalse(r["homologacao_de_fonte"])
        self.assertFalse(r["publicacao_autorizada"])
        self.assertFalse(r["treino_habilitado"])

    def test_objeto_adulterado_no_legado_bloqueia(self):
        damaged = self.dir / "adulterado.zip"
        with zipfile.ZipFile(self.legacy) as orig, zipfile.ZipFile(damaged, "w") as out:
            for name in orig.namelist():
                data = orig.read(name)
                if name.startswith("cofre/objetos_sha256/"):
                    data = b"conteudo corrompido"
                out.writestr(name, data)
        with self.assertRaises(ErroMigracaoPAM):
            converter_zip_piloto_pam(
                arquivo_legado=damaged, arquivo_canonico=self.new,
            )
        self.assertFalse(self.new.exists())

    def test_zip_traversal_e_recusado_sem_escrita(self):
        damaged = self.dir / "path-traversal.zip"
        with zipfile.ZipFile(self.legacy) as orig, zipfile.ZipFile(damaged, "w") as out:
            for name in orig.namelist():
                out.writestr(name, orig.read(name))
            out.writestr("../escapou.txt", b"evil")
        with self.assertRaises(ErroMigracaoPAM):
            converter_zip_piloto_pam(
                arquivo_legado=damaged, arquivo_canonico=self.new,
            )
        self.assertFalse((self.dir / "escapou.txt").exists())
        self.assertFalse(self.new.exists())

    def test_nao_sobrescreve_backup_canonico_existente(self):
        self.new.write_bytes(b"backup nao sobrescrever")
        with self.assertRaises(ErroMigracaoPAM):
            converter_zip_piloto_pam(
                arquivo_legado=self.legacy, arquivo_canonico=self.new)
        self.assertEqual(self.new.read_bytes(), b"backup nao sobrescrever")

    def test_cli_offline_grava_um_novo_backup_canônico(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main([
                "--origem", str(self.legacy),
                "--destino", str(self.new),
            ]), 0)
        r = json.loads(stdout.getvalue())
        self.assertEqual(r["capturas"], 2)
        self.assertEqual(r["promocoes"], 0)


if __name__ == "__main__":
    unittest.main()
