"""Benchmark de base de imagem: testes determinísticos e política bloqueada."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from nivon.infra_base_benchmark import (
    ErroBenchmark, comparar, contar, ler, main, PREFIX,
)


def scan(name, values=()):
    return {
        "SchemaVersion": 2, "ArtifactName": PREFIX + name,
        "ArtifactType": "container_image",
        "Results": [{"Target": "debian:synthetic", "Class": "os-pkgs",
                     "Vulnerabilities": [
                         {"VulnerabilityID": f"TEST-CVE-{i}", "Severity": severity}
                         for i, severity in enumerate(values)
                     ]}],
    }


class TestBaseBenchmark(unittest.TestCase):
    def test_reducao_evidenciada_nao_promove_releases(self):
        out = comparar(scan("bookworm", ["CRITICAL", "HIGH", "HIGH"]),
                       scan("trixie", ["MEDIUM", "HIGH"]))
        self.assertEqual(out["high_critical_base"], 3)
        self.assertEqual(out["high_critical_candidate"], 1)
        self.assertEqual(out["delta_high_critical"], -2)
        self.assertTrue(out["candidate_has_fewer_blockers"])
        self.assertFalse(out["candidate_approved"])
        self.assertFalse(out["production_release_allowed"])

    def test_candidato_pior_nao_e_escondido(self):
        out = comparar(scan("bookworm", []),scan("trixie", ["CRITICAL"]))
        self.assertEqual(out["delta_high_critical"], 1)
        self.assertFalse(out["candidate_has_fewer_blockers"])

    def test_ausencia_resultados_nao_e_zero(self):
        invalid = scan("bookworm")
        invalid["Results"] = []
        with self.assertRaises(ErroBenchmark):
            comparar(invalid,scan("trixie"))

    def test_identidade_da_imagem_verificada(self):
        with self.assertRaises(ErroBenchmark):
            contar(scan("bookworm"), imagem=PREFIX+"trixie")
        with self.assertRaises(ErroBenchmark):
            contar(scan("bookworm"), imagem="another:latest")

    def test_severidade_desconhecida_bloqueada(self):
        with self.assertRaises(ErroBenchmark):
            comparar(scan("bookworm", ["ULTRAHIGH"]), scan("trixie"))

    def test_ausencia_vulns_produz_todas_contagens(self):
        out = comparar(scan("bookworm"),scan("trixie"))
        self.assertEqual(sum(out["base"].values()),0)
        self.assertFalse(out["production_release_allowed"])

    def test_json_chave_duplicada_recusado(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"dup.json"
            p.write_text('{"SchemaVersion":2,"SchemaVersion":3}',encoding="utf-8")
            with self.assertRaises(ErroBenchmark):
                ler(p)

    def test_cli_contra_duas_fixtures(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"book.json";b=Path(d)/"trixie.json"
            a.write_text(json.dumps(scan("bookworm",["HIGH"])),encoding="utf-8")
            b.write_text(json.dumps(scan("trixie")),encoding="utf-8")
            from io import StringIO
            from contextlib import redirect_stdout
            f=StringIO()
            with redirect_stdout(f):
                rc=main(["--bookworm",str(a),"--trixie",str(b)])
            self.assertEqual(rc,0)
            self.assertFalse(json.loads(f.getvalue())["production_release_allowed"])


if __name__=="__main__":
    unittest.main()
