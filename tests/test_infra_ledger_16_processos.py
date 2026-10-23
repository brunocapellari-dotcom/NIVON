"""R03: 16 processos / 48 jobs distintos + disputa idempotente (somente sintético).

Verifica transações duráveis e exclusividade dos leases do ledger NIVON.
Nenhum job real, rede, cron, envio, dado privado ou banco externo.
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.infra_job_ledger import abrir_ledger, finalizar, registrar, reservar

DUE = "2026-10-20T08:00:00-04:00"
BEFORE = "2026-10-20T07:59:00-04:00"
NOW = "2026-10-20T08:01:00-04:00"
DONE = "2026-10-20T08:01:05-04:00"
HASH = "f" * 64
SHARED = "TEST_SYNTHETIC_STRESS_SHARED"


def _trabalhador(caminho: str, indice: int, evento, resultado) -> None:
    db = None
    try:
        if not evento.wait(timeout=20):
            raise RuntimeError("barreira não liberada")
        db = abrir_ledger(caminho)
        for j in range(3):
            chave = f"TEST_SYNTHETIC_STRESS_{indice:02d}_{j}"
            reg = registrar(db, chave=chave, vencimento=DUE,
                            input_sha256=HASH, registrado_em=BEFORE)
            if not reg["novo"]:
                raise AssertionError(f"job novo já existia: {chave}")
            lease = reservar(db, chave=chave, vencimento=DUE,
                             agora=NOW, lease_segundos=30)
            if not lease["reservado"]:
                raise AssertionError(f"job sem lease exclusivo: {chave}")
            fim = finalizar(db, chave=chave, vencimento=DUE,
                            token=lease["token"], agora=DONE,
                            sucesso=True, output_sha256=HASH)
            if fim["estado"] != "SUCCEEDED":
                raise AssertionError(f"job não finalizou: {chave}")
        registrar(db, chave=SHARED, vencimento=DUE,
                  input_sha256=HASH, registrado_em=BEFORE)
        compartilhado = reservar(db, chave=SHARED, vencimento=DUE,
                                agora=NOW, lease_segundos=30)
        if compartilhado["reservado"]:
            finalizar(db, chave=SHARED, vencimento=DUE,
                     token=compartilhado["token"], agora=DONE,
                     sucesso=True, output_sha256=HASH)
        resultado.put(("ok", indice, bool(compartilhado["reservado"])))
    except BaseException as exc:
        resultado.put(("error", indice, type(exc).__name__ + ": " + str(exc)))
    finally:
        if db is not None:
            db.close()


class TestStressSQLiteR03(unittest.TestCase):
    def test_16_processos_48_jobs_sem_perda_e_um_lease_compartilhado(self):
        with tempfile.TemporaryDirectory() as d:
            os.chmod(d, 0o700)
            caminho = str(Path(d) / "job_stress.sqlite")
            with abrir_ledger(caminho):
                pass  # schema inicial antes da competição; banco ainda sem jobs
            context = multiprocessing.get_context("spawn")
            evento = context.Event()
            resultados = context.Queue()
            processos = [
                context.Process(target=_trabalhador,
                                args=(caminho, i, evento, resultados))
                for i in range(16)
            ]
            for proc in processos:
                proc.start()
            evento.set()
            for proc in processos:
                proc.join(timeout=35)
            travados = [p.pid for p in processos if p.is_alive()]
            for p in processos:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=5)
            self.assertFalse(travados, "processos presos: " + repr(travados))
            self.assertTrue(all(p.exitcode == 0 for p in processos),
                            "workers terminaram com código não zero")
            registros = []
            for _ in range(16):
                try:
                    registros.append(resultados.get(timeout=5))
                except queue.Empty:
                    self.fail("processos sem resultado persistido")
            erros = [r for r in registros if r[0] != "ok"]
            self.assertEqual(erros, [], "falha concorrente (não ignorar)")
            self.assertEqual(sum(1 for r in registros if r[2]), 1)
            with abrir_ledger(caminho) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM nivon_job").fetchone()[0], 49)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM nivon_job WHERE status='SUCCEEDED'"
                ).fetchone()[0], 49)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM nivon_job WHERE attempts != 1"
                ).fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM nivon_job_event"
                ).fetchone()[0], 147)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM nivon_job_event WHERE event='STARTED' AND job_key=?",
                    (SHARED,),
                ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
