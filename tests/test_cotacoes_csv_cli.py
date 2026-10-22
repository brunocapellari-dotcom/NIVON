"""Testes E2E offline do comando CEPEA/IMEA, sem preços reais."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from nivon.cotacoes_csv_cli import executar_importacao, main, ErroCLIImportacao
from nivon.historico_vintages import ArmazemVintages

_CSV = ("serie_id;produto;localidade;competencia;referencia;preco;unidade\\n"
        "SOJA_MT;Soja;Sorriso;2026-10;2026-10-20;123,45;BRL/SC60KG\\n")
_DOC = {"fonte_id":"IMEA", "fonte_url":"https://www.imea.com.br/",
        "edicao_id":"EDICAO_SINTETICA", "coletado_em":"2026-10-21T14:00:00Z",
        "publicado_em":None, "disponivel_em":None, "arquivo_csv":"cotacoes.csv"}

class TestCLI(unittest.TestCase):
    def _dados(self, diretorio):
        root = Path(diretorio)
        (root/"cotacoes.csv").write_text(_CSV, encoding="utf-8")
        m = root/"manifesto.json"
        m.write_text(json.dumps(_DOC), encoding="utf-8")
        return m

    def test_somente_validacao_sem_abrir_banco(self):
        with tempfile.TemporaryDirectory() as t:
            m=self._dados(t)
            out=executar_importacao(manifesto=m)
            self.assertEqual(out["linhas"], 1)
            self.assertFalse(out["publicavel"])
            self.assertEqual(out["modo"], "VALIDACAO_OFFLINE")
            self.assertEqual(sorted(p.name for p in Path(t).iterdir()),
                             ["cotacoes.csv","manifesto.json"])

    def test_persistencia_supervisionada_idempotente_sem_asof(self):
        with tempfile.TemporaryDirectory() as t:
            m=self._dados(t)
            with self.assertRaises(ErroCLIImportacao):
                executar_importacao(manifesto=m,banco="quarentena.sqlite")
            x=executar_importacao(manifesto=m,persistir=True,banco="quarentena.sqlite")
            self.assertEqual(x["novas"],1)
            y=executar_importacao(manifesto=m,persistir=True,banco="quarentena.sqlite")
            self.assertEqual(y["duplicadas"],1)
            db=ArmazemVintages(Path(t)/"quarentena.sqlite")
            try:
                self.assertEqual(db.contar(),1)
                self.assertIsNone(db.consultar_asof(dataset_id="IMEA_FISICO",
                    serie_id="SOJA_MT",competencia="2026-10",
                    instante_decisao="2026-10-25T00:00:00Z"))
            finally:
                db.fechar()

    def test_rejeita_traversal_symlink_e_campos_adicionais(self):
        with tempfile.TemporaryDirectory() as t:
            m=self._dados(t)
            d=dict(_DOC, arquivo_csv="../invasor.csv")
            m.write_text(json.dumps(d),encoding="utf-8")
            with self.assertRaises(ErroCLIImportacao):
                executar_importacao(manifesto=m)
            d=dict(_DOC, segredo="NAO_DEVE_PASSAR")
            m.write_text(json.dumps(d),encoding="utf-8")
            with self.assertRaises(ErroCLIImportacao):
                executar_importacao(manifesto=m)
            m.write_text(json.dumps(_DOC),encoding="utf-8")
            (Path(t)/"secreto.csv").write_text(_CSV,encoding="utf-8")
            (Path(t)/"cotacoes.csv").unlink()
            (Path(t)/"cotacoes.csv").symlink_to(Path(t)/"secreto.csv")
            with self.assertRaises(ErroCLIImportacao):
                executar_importacao(manifesto=m)

    def test_cli_nao_expoe_cotacao(self):
        with tempfile.TemporaryDirectory() as t:
            m=self._dados(t)
            output=io.StringIO()
            with redirect_stdout(output):
                rc=main(["--manifesto",str(m)])
            self.assertEqual(rc,0)
            self.assertNotIn("123,45",output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["modo"],"VALIDACAO_OFFLINE")
            output=io.StringIO()
            with redirect_stderr(output):
                rc=main(["--manifesto",str(m),"--banco","quarentena.sqlite"])
            self.assertEqual(rc,2)
            self.assertNotIn(str(m),output.getvalue())

if __name__=="__main__":
    unittest.main()
