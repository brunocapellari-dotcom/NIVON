"""E2E da CLI em processo Python separado, sem rede ou dados oficiais."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import nivon


def _captura(esp, tabela):
    dims = {"territorio": "D1C", "periodo": "D2C", "variavel": "D3C",
            "referencia_temporal": "D4C", "inspecao": "D5C"}
    totals = {"referencia_temporal": "0", "inspecao": "0"}
    if esp == "BOVINO":
        dims["rebanho"] = "D6C"
        totals["rebanho"] = "0"
    cab = {c: c + " codigo" for c in dims.values()}
    cab.update({"NC": "nivel", "MN": "unidade", "V": "valor"})
    rows = []
    for variable, value, unit in (("9999", "100", "Cabeças"),
                                   ("8888", "23000", "Quilogramas")):
        row = {"NC": "1", "V": value, "MN": unit, "D1C": "1",
               "D2C": "202602", "D3C": variable, "D4C": "0", "D5C": "0"}
        if esp == "BOVINO":
            row["D6C"] = "0"
        rows.append(row)
    entry = {
        "especie": esp, "tabela_sidra": tabela,
        "url_valores": f"https://apisidra.ibge.gov.br/values/t/{tabela}/n1/1/p/202602/v/allxp/h/y",
        "url_metadados": f"https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/metadados",
        "arquivo_valores": f"{tabela}-valores.json",
        "arquivo_metadados": f"{tabela}-metadados.json",
        "publicacao_declarada": "2026-09-21T12:00:00-03:00",
        "coleta_declarada": "2026-10-21T12:00:00-04:00",
        "dimensoes": dims, "totais": totals,
        "variaveis": {"9999": "ABATE_CABECAS", "8888": "PESO_CARCACAS_KG"},
    }
    return entry, json.dumps([cab, *rows], ensure_ascii=False).encode(), (
        json.dumps({"id": int(tabela)}).encode())


class TestCLISidra(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.base = self.dir / "dados"
        self.base.mkdir()
        self.manifest = self.dir / "manifesto.json"
        self.banco = self.dir / "sidra.sqlite"
        entries = []
        for esp, tabela in (("BOVINO", "1092"), ("SUINO", "1093"), ("FRANGO", "1094")):
            entry, valores, meta = _captura(esp, tabela)
            (self.base / entry["arquivo_valores"]).write_bytes(valores)
            (self.base / entry["arquivo_metadados"]).write_bytes(meta)
            entries.append(entry)
        self.entries = entries
        self._manifest(entries)

    def _manifest(self, entries):
        self.manifest.write_text(
            json.dumps({"schema_version": "1.0", "capturas": entries}),
            encoding="utf-8")

    def executar(self, *extras, rights=True):
        cmd = [sys.executable, "-m", "nivon.pecuaria_sidra_operacao",
               "--manifest", str(self.manifest),
               "--base-dir", str(self.base), "--corte",
               "2026-10-23T00:00:00-04:00"]
        if rights:
            cmd.append("--confirmar-direitos")
        cmd.extend(extras)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(nivon.__file__).resolve().parents[1])
        return subprocess.run(cmd, capture_output=True, text=True,
                              env=env, timeout=12)

    def test_dryrun_cli_tres_especies_sem_db(self):
        r = self.executar()
        self.assertEqual(r.returncode, 0, r.stderr)
        x = json.loads(r.stdout)
        self.assertEqual(x["status"], "LOTE_OFFLINE_NAO_HOMOLOGADO")
        self.assertFalse(x["persistido"])
        self.assertEqual(set(x["especies"]), {"BOVINO", "SUINO", "FRANGO"})
        self.assertEqual(x["qualidade"]["registros_normalizados"], 6)
        self.assertFalse(x["publicacao_permitida"])
        self.assertFalse(self.banco.exists())

    def test_gravacao_cli_idempotente_lote_inteiro(self):
        args = ("--gravar", "--banco", str(self.banco))
        r = self.executar(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        one = json.loads(r.stdout)
        self.assertEqual(one["qualidade"]["n_especies"], 3)
        self.assertTrue(one["persistido"])
        two = self.executar(*args)
        self.assertEqual(two.returncode, 0, two.stderr)
        self.assertEqual(json.loads(two.stdout)["ids_capturas"], one["ids_capturas"])

    def test_sem_declaracao_direitos_nao_le(self):
        r = self.executar(rights=False)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stderr)["status"], "BLOQUEADO_SEM_PROMOCAO")
        self.assertFalse(self.banco.exists())

    def test_manifesto_path_traversal_e_symlink(self):
        entries = json.loads(json.dumps(self.entries))
        entries[0]["arquivo_valores"] = "../manifesto.json"
        self._manifest(entries)
        r = self.executar()
        self.assertEqual(r.returncode, 2)
        self.assertIn("arquivo", json.loads(r.stderr)["detalhe"])
        entries[0]["arquivo_valores"] = self.entries[0]["arquivo_valores"]
        alvo = self.dir / "secret.json"
        alvo.write_text('{"mock":true}')
        link = self.base / "symlink.json"
        try:
            link.symlink_to(alvo)
        except (OSError, NotImplementedError):
            return
        entries[0]["arquivo_valores"] = "symlink.json"
        self._manifest(entries)
        r = self.executar()
        self.assertEqual(r.returncode, 2)
        self.assertIn("symlink", json.loads(r.stderr)["detalhe"])
        self.assertFalse(self.banco.exists())

    def test_schema_e_contrato_errados_falham_fechado(self):
        entries = json.loads(json.dumps(self.entries))
        entries[0]["variaveis"]["7777"] = "ABATE_CABECAS"
        self._manifest(entries)
        r = self.executar("--gravar", "--banco", str(self.banco))
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.banco.exists())

    def test_gravar_requer_banco(self):
        r = self.executar("--gravar")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.banco.exists())


if __name__ == "__main__":
    unittest.main()
