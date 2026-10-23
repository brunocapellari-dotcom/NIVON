"""Fluxo integrado incremental SAGyP: 3 ciclos, revisões, rollback e frescor.

Somente RAWs sintéticos UTF-8 privados e SQLite temporário, sem HTTP.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from nivon.argentina_agricultura import CAMPOS
from nivon.sincronizacao_incremental_argentina_local import (
    SCHEMA, ErroIncrementalArgentina, sincronizar_raw_argentina_local,
)

URL = "https://datos.magyp.gob.ar/dataset/estimaciones.csv"


def arquivo_csv(producao="200", *, repetido=False):
    linhas = [
        ["Soja", "2025", "2024/25", "Cordoba", "14", "Rio Cuarto",
         "14001", "100", "90", producao, "2222"],
    ]
    if repetido:
        linhas.append(list(linhas[0]))
    return (";".join(CAMPOS) + "\n" +
            "\n".join(";".join(x) for x in linhas) + "\n").encode("utf-8")


class TestSincronizacaoArgentinaIncrementalE2E(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="nivon-ar-incremental-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.base.chmod(0o700)
        self.raw = self.base / "raw"
        self.raw.mkdir(mode=0o700)
        self.db = self.base / "quarentena.sqlite"

    def entrada(self, dados):
        digest = sha256(dados).hexdigest()
        p = self.raw / (digest + ".csv")
        p.write_bytes(dados)
        p.chmod(0o600)
        return {"recurso": "soja", "sha256": digest,
                "arquivo": digest + ".csv", "origem_url": URL,
                "coletado_em": "2026-10-20T12:00:00-03:00"}

    def executar(self, entries, *, direito=True):
        return sincronizar_raw_argentina_local(
            {"schema": SCHEMA, "edicoes": entries},
            banco=self.db, pasta_raw=self.raw,
            direitos_armazenamento_verificados=direito,
        )

    def test_tres_ciclos_delta_idempotente_revisao_preservada(self):
        a = self.entrada(arquivo_csv("200"))
        primeira = self.executar([a])
        self.assertEqual(primeira["edicoes_novas"], 1)
        self.assertEqual(primeira["observacoes_novas"], 1)
        self.assertFalse(primeira["publicacao_permitida"])
        (self.raw / a["arquivo"]).unlink()
        segunda = self.executar([a])
        self.assertEqual(segunda["edicoes_novas"], 0)
        self.assertEqual(segunda["estado"], "SEM_DELTA_SEM_DOWNLOAD_OU_ESCRITA_DE_EDICAO")
        b = self.entrada(arquivo_csv("230"))
        terceira = self.executar([a, b])
        self.assertEqual(terceira["edicoes_novas"], 1)
        self.assertEqual(terceira["edicoes_inalteradas"], 1)
        self.assertEqual(terceira["observacoes_apos"], 2)
        with sqlite3.connect(self.db) as db:
            x = db.execute("""SELECT sha256,filas,publicado_utc,disponibilidad_verificada
                              FROM ar_ediciones ORDER BY sha256""").fetchall()
            self.assertEqual(len(x), 2)
            self.assertEqual({r[0] for r in x}, {a["sha256"], b["sha256"]})
            self.assertTrue(all(r[1] == 1 and r[2] is None and r[3] == 0 for r in x))
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_falha_em_um_raw_impede_escrita_dos_demais_do_lote(self):
        a = self.entrada(arquivo_csv("100"))
        b = self.entrada(arquivo_csv("999"))
        (self.raw / b["arquivo"]).write_bytes(b"arquivo adulterado")
        with self.assertRaisesRegex(ErroIncrementalArgentina, "SHA-256"):
            self.executar([a, b])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ar_ediciones").fetchone()[0], 0)

    def test_chave_duplicada_no_csv_impede_importacao(self):
        a = self.entrada(arquivo_csv(repetido=True))
        with self.assertRaisesRegex(ErroIncrementalArgentina, "duplicada"):
            self.executar([a])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ar_estimaciones").fetchone()[0], 0)

    def test_edicao_ja_importada_adulterada_bloqueia_noop(self):
        a = self.entrada(arquivo_csv("200"))
        self.executar([a])
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE ar_estimaciones SET produccion_tm='999' ")
        with self.assertRaisesRegex(ErroIncrementalArgentina, "adulterado"):
            self.executar([a])

    def test_direitos_nao_confirmados_bloqueiam_sem_criar_banco(self):
        a = self.entrada(arquivo_csv())
        with self.assertRaises(PermissionError):
            self.executar([a], direito=False)
        self.assertFalse(self.db.exists())

    def test_nome_raw_nao_pode_escapar_do_diretorio(self):
        a = self.entrada(arquivo_csv())
        a["arquivo"] = "../fora.csv"
        with self.assertRaisesRegex(ErroIncrementalArgentina, "SHA"):
            self.executar([a])
        self.assertFalse(self.db.exists())

    def test_soja_nao_pode_ser_importada_como_milho(self):
        entrada = self.entrada(arquivo_csv("202"))
        entrada["recurso"] = "milho"
        with self.assertRaisesRegex(ErroIncrementalArgentina, "cultivo"):
            self.executar([entrada])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM ar_ediciones").fetchone()[0], 0
            )

    def test_milho_maiz_com_acento_preservado_no_recurso_correto(self):
        dados = arquivo_csv("202").replace(b"Soja", "Maíz".encode("utf-8"))
        entrada = self.entrada(dados)
        entrada["recurso"] = "milho"
        resultado = self.executar([entrada])
        self.assertEqual(resultado["edicoes_novas"], 1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(
                db.execute("SELECT cultivo FROM ar_estimaciones").fetchone()[0],
                "Maíz",
            )

    def test_sem_politica_nao_libera_publicacao_ou_backtest(self):
        a = self.entrada(arquivo_csv())
        resp = self.executar([a])
        self.assertEqual(resp["estado"], "DELTA_LOCAL_ATOMICO_QUARENTENA")
        self.assertIs(resp["publicacao_verificada"], False)
        self.assertIs(resp["cloud_integrado"], False)
        self.assertIs(resp["publicacao_permitida"], False)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ar_ediciones WHERE publicado_utc IS NOT NULL").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
