"""Teste independente de concorrência no ledger SQLite do NIVON.

Usa somente arquivo temporário local e hashes sintéticos. A meta R03 exige
16 processos e 48 escritas sem falhas silenciosas, duplicações ou perdas.
Sem banco remoto, serviços externos ou rede.
"""
from __future__ import annotations

import hashlib
import multiprocessing
import queue
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.registro_snapshots import abrir_registro, registrar_snapshot


DATASET = "IBGE_CODIGOS_MUNICIPIOS"
CATALOGO = {"datasets": [{"id": DATASET, "source_id": "IBGE"}]}


def _gravar_tres_versoes(db_path: str, identificador: int, largada, saida):
    db = None
    try:
        # Uma conexão independente por processo, schema já criado na origem.
        db = sqlite3.connect(db_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        largada.wait(timeout=20)
        for sequencia in range(3):
            digest = hashlib.sha256(
                f"fixture-concorrencia-{identificador}-{sequencia}".encode()
            ).hexdigest()
            registrar_snapshot(
                db, CATALOGO, dataset_id=DATASET, sha256=digest,
                tamanho=123, mime="application/json", schema_versao="IBGE.1",
                coletado_em="2026-10-20T15:00:00Z",
                competencia="2026-10", referencia="2026-10-20",
                publicacao="2026-10-20",
            )
        saida.put((identificador, "OK"))
    except BaseException as exc:
        saida.put((identificador, f"{type(exc).__name__}: {exc}"))
    finally:
        if db is not None:
            db.close()


class TestAuditoriaConcorrenciaSQLite(unittest.TestCase):
    def test_r03_dezesseis_processos_quarenta_oito_escritas_atomicas(self):
        with tempfile.TemporaryDirectory(prefix="nivon-audit-r03-") as temp:
            db_path = str(Path(temp) / "ledger.sqlite")
            db = abrir_registro(db_path)
            db.close()

            ctx = multiprocessing.get_context("spawn")
            largada = ctx.Barrier(16)
            resultados = ctx.Queue()
            workers = [
                ctx.Process(
                    target=_gravar_tres_versoes,
                    args=(db_path, indice, largada, resultados),
                    name=f"audit-ledger-{indice}",
                )
                for indice in range(16)
            ]
            try:
                for proc in workers:
                    proc.start()
                for proc in workers:
                    proc.join(timeout=25)
                travados = [proc.name for proc in workers if proc.is_alive()]
                for proc in workers:
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(timeout=5)

                observados = {}
                for _ in range(16):
                    try:
                        indice, resultado = resultados.get(timeout=1)
                    except queue.Empty:
                        break
                    observados[indice] = resultado

                erros = {indice: estado for indice, estado in observados.items()
                         if estado != "OK"}
                self.assertFalse(travados, f"processos travados: {travados}")
                self.assertEqual(
                    len(observados), 16,
                    f"processos sem resultado: {16 - len(observados)}; erros={erros}",
                )
                self.assertFalse(erros, f"R03: writes falharam: {erros}")
                with sqlite3.connect(db_path) as conferencia:
                    n_snapshots = conferencia.execute(
                        "SELECT COUNT(*) FROM nivon_snapshots"
                    ).fetchone()[0]
                    n_coletas = conferencia.execute(
                        "SELECT COUNT(*) FROM nivon_coletas"
                    ).fetchone()[0]
                    fk = conferencia.execute("PRAGMA foreign_key_check").fetchall()
                    integridade = conferencia.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0]
                self.assertEqual((n_snapshots, n_coletas), (48, 48))
                self.assertFalse(fk)
                self.assertEqual(integridade, "ok")
            finally:
                resultados.close()
                resultados.join_thread()


if __name__ == "__main__":
    unittest.main()
