"""Integração E2E do operador único sem acesso remoto e sem cloud."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nivon.operador_incremental_agro import (
    ErroLoteAgro, executar_fontes_incrementais, main, _manifesto_json,
)


class TestOperadorIncrementalAgro(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="nivon-lote-agro-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cfile = self.root / "conab.json"
        self.afile = self.root / "argentina.json"
        self.cfile.write_text('{"edicoes":[]}', encoding="utf-8")
        self.afile.write_text('{"edicoes":[]}', encoding="utf-8")
        self.conab = {
            "manifesto": str(self.cfile), "banco": str(self.root / "conab.sqlite"),
            "raw_dir": str(self.root), "backups": str(self.root / "backups"),
        }
        self.argentina = {
            "manifesto": str(self.afile), "banco": str(self.root / "argentina.sqlite"),
            "raw_dir": str(self.root),
        }

    def test_preflight_padrao_nao_abre_banco_ou_importa(self):
        with (
            patch("nivon.operador_incremental_agro.sincronizar_incremental_lab") as conab,
            patch("nivon.operador_incremental_agro.sincronizar_raw_argentina_local") as arg,
        ):
            r = executar_fontes_incrementais(conab=self.conab, argentina=self.argentina)
        self.assertFalse(r["executado"])
        self.assertFalse(r["publicacao_permitida"])
        conab.assert_not_called()
        arg.assert_not_called()
        self.assertFalse(Path(self.conab["banco"]).exists())

    def test_sem_direitos_argentina_falha_antes_de_conab(self):
        with patch("nivon.operador_incremental_agro.sincronizar_incremental_lab") as c:
            with self.assertRaises(PermissionError):
                executar_fontes_incrementais(
                    conab=self.conab, argentina=self.argentina, executar=True,
                )
            c.assert_not_called()

    def test_lote_duas_fontes_e_replay_sem_delta(self):
        with (
            patch("nivon.operador_incremental_agro.sincronizar_incremental_lab",
                  side_effect=[
                      {"estado": "DELTA_LAB_GRAVADO_E_BACKUP_RECONFERIDO",
                       "edicoes_novas": 1, "observacoes_novas": 11},
                      {"estado": "SEM_DELTA_NENHUM_DOWNLOAD_OU_GRAVACAO",
                       "edicoes_novas": 0, "observacoes_novas": 0},
                  ]) as conab,
            patch("nivon.operador_incremental_agro.sincronizar_raw_argentina_local",
                  side_effect=[
                      {"estado": "DELTA_LOCAL_ATOMICO_QUARENTENA",
                       "edicoes_novas": 1, "observacoes_novas": 1},
                      {"estado": "SEM_DELTA_SEM_DOWNLOAD_OU_ESCRITA_DE_EDICAO",
                       "edicoes_novas": 0, "observacoes_novas": 0},
                  ]) as arg,
        ):
            results = [
                executar_fontes_incrementais(
                    conab=self.conab, argentina=self.argentina, executar=True,
                    direitos_argentina_verificados=True,
                ) for _ in range(2)
            ]
        self.assertEqual(conab.call_count, 2)
        self.assertEqual(arg.call_count, 2)
        self.assertEqual(results[0]["resultados"]["CONAB_LAB"]["edicoes_novas"], 1)
        self.assertEqual(results[0]["resultados"]["ARG_SAGYP"]["edicoes_novas"], 1)
        self.assertEqual(results[1]["resultados"]["CONAB_LAB"]["edicoes_novas"], 0)
        for result in results:
            self.assertEqual(result["estado"], "FONTES_LOCAIS_CONFERIDAS_SEM_PROMOCAO")
            self.assertFalse(result["cloud_integrado"])
            self.assertFalse(result["publicacao_permitida"])
            self.assertFalse(result["rede_usada"])

    def test_falha_da_segunda_fonte_nao_esconde_primeiro_commit(self):
        with (
            patch("nivon.operador_incremental_agro.sincronizar_incremental_lab",
                  return_value={"estado": "DELTA", "edicoes_novas": 1}),
            patch("nivon.operador_incremental_agro.sincronizar_raw_argentina_local",
                  side_effect=ValueError("fixture de falha")),
        ):
            r = executar_fontes_incrementais(
                conab=self.conab, argentina=self.argentina, executar=True,
                direitos_argentina_verificados=True,
            )
        self.assertEqual(r["estado"], "LOTE_PARCIAL_FALHOU_FECHADO")
        self.assertEqual(r["fonte_com_erro"], "ARG_SAGYP")
        self.assertEqual(r["fontes_ja_confirmadas"], ["CONAB_LAB"])
        self.assertFalse(r["publicacao_permitida"])

    def test_mesmo_banco_duas_fontes_bloqueado(self):
        arg = {**self.argentina, "banco": self.conab["banco"]}
        with self.assertRaisesRegex(ErroLoteAgro, "independentes"):
            executar_fontes_incrementais(
                conab=self.conab, argentina=arg, executar=True,
                direitos_argentina_verificados=True,
            )

    def test_json_duplicado_ou_constante_nao_confiavel(self):
        for texto in ('{"a":1,"a":2}', '{"a":NaN}', '[]'):
            self.cfile.write_text(texto, encoding="utf-8")
            with self.subTest(texto=texto), self.assertRaises(ErroLoteAgro):
                _manifesto_json(self.cfile)

    def test_cli_dry_run_sem_efeito_colateral(self):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--conab-manifesto", str(self.cfile),
                         "--conab-banco", self.conab["banco"],
                         "--conab-raw-dir", self.conab["raw_dir"],
                         "--conab-backups", self.conab["backups"]])
        self.assertEqual(code, 0)
        r = json.loads(out.getvalue())
        self.assertEqual(r["estado"], "EXECUCAO_DESABILITADA")
        self.assertFalse(Path(self.conab["banco"]).exists())


if __name__ == "__main__":
    unittest.main()
