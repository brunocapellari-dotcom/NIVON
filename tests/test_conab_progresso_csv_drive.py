"""Contrato observado no arquivo CONAB_Plantio_Colheita_Historico.xlsx do Drive.

Somente três primeiras linhas foram usadas como fixture de schema; o arquivo
de 17.982 linhas permaneceu no Drive. Sem prova as-of ou atualização live.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from unittest import TestCase

from nivon.conab_progresso_csv_drive import (
    normalizar_csv_progresso_conab, ErroConabProgressoDrive,
)

ROWS=[
    ",Data,Semana,Mês,Ano,Estado,Semeadura / Colheita,Produto,Dado,INFO",
    "0,2019-11-08 00:00:00,45,Novembro,2019,Bahia,Semeadura,Milho 1ª,0.01,Brasil",
    "1,2019-11-08 00:00:00,45,Novembro,2019,Goiás,Semeadura,Milho 1ª,0.45,Brasil",
    "2,2019-11-08 00:00:00,45,Novembro,2019,Maranhão,Semeadura,Milho 1ª,0,Brasil",
]


def raw():
    return ("\n".join(ROWS)+"\n").encode("utf-8")


def run(b=None):
    payload=raw() if b is None else b
    return normalizar_csv_progresso_conab(
        raw_csv=payload,sha256_esperado=sha256(payload).hexdigest(),
        adquirido_em="2026-10-22T12:00:00-04:00")


class TestDriveProgressoConab(TestCase):
    def test_schema_real_de_três_linhas_sem_vintage(self):
        out=run()
        self.assertEqual(out["total"],3)
        self.assertEqual(out["data_min"],"2019-11-08")
        self.assertEqual(out["data_max"],"2019-11-08")
        self.assertEqual([r["uf"] for r in out["registros"]],["BA","GO","MA"])
        self.assertEqual(out["registros"][0]["progresso_fracao"],"0.01")
        self.assertEqual(out["registros"][2]["progresso_fracao"],"0")
        self.assertIsNone(out["registros"][0]["disponivel_em"])
        self.assertFalse(out["habilita_backtest"])

    def test_detecta_indice_semana_incorreta(self):
        tampered=raw().replace(b",45,Novembro",b",44,Novembro")
        with self.assertRaisesRegex(ErroConabProgressoDrive,"calendário"):
            run(tampered)

    def test_detecta_indice_repetido(self):
        tampered=raw().replace(b"\n1,",b"\n0,")
        with self.assertRaisesRegex(ErroConabProgressoDrive,"sequencial"):
            run(tampered)

    def test_progresso_nao_pode_ultrapassar_cem_porcento(self):
        tampered=raw().replace(b"Milho 1\xc2\xaa,0.45",b"Milho 1\xc2\xaa,1.45")
        with self.assertRaisesRegex(ErroConabProgressoDrive,"fração"):
            run(tampered)

    def test_formato_alterado_bloqueia(self):
        tampered=raw().replace(b"Semeadura / Colheita",b"Operacao")
        with self.assertRaisesRegex(ErroConabProgressoDrive,"schema"):
            run(tampered)

    def test_hash_errado_bloqueia(self):
        with self.assertRaisesRegex(ErroConabProgressoDrive,"SHA"):
            normalizar_csv_progresso_conab(
                raw_csv=raw(),sha256_esperado="a"*64,
                adquirido_em="2026-10-22T12:00:00-04:00")

    def test_cli_produz_historico_sem_flags_de_publicacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            inp,out=root/"input.csv",root/"dossie.json"
            inp.write_bytes(raw())
            project=Path(__file__).resolve().parents[1]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(project/"src")+os.pathsep+env.get("PYTHONPATH","")
            argv=[
                sys.executable,"-m","nivon.conab_progresso_csv_drive",
                "--input",str(inp),
                "--sha256",sha256(raw()).hexdigest(),
                "--adquirido-em","2026-10-22T12:00:00-04:00",
                "--out",str(out),
            ]
            p=subprocess.run(argv,cwd=project,env=env,text=True,
                             capture_output=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stderr)
            obj=json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(obj["total"],3)
            self.assertFalse(obj["habilita_publicacao"])
            self.assertFalse(obj["habilita_treino"])
            self.assertFalse(obj["habilita_backtest"])


if __name__=="__main__":
    import unittest
    unittest.main()
