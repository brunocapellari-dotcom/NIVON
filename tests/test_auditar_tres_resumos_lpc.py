"""Testes do auditor local: snapshots fictícios, zero acesso à rede."""
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io

from scripts.auditar_tres_resumos_lpc import carregar_manifesto_local, main
from test_anp_lpc_homologacao import lote, Workbook


@unittest.skipIf(Workbook is None, "openpyxl opcional ausente")
class TestCLIAnpTresSemanas(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        source = lote()
        (self.base/"indice.html").write_bytes(source["indice_html"])
        entries = []
        for idx, ed in enumerate(source["edicoes"]):
            nome = f"semana-{idx}.xlsx"
            (self.base/nome).write_bytes(ed["xlsx"])
            entries.append({
                **{k:v for k,v in ed.items() if k != "xlsx"},
                "arquivo":nome,
            })
        doc = {
            "indice_arquivo":"indice.html",
            "indice_sha256_esperado":source["indice_sha256_esperado"],
            "capturado_indice_em":source["capturado_indice_em"],
            "as_of":source["as_of"],
            "ano":source["ano"], "edicoes":entries,
        }
        self.manifest = self.base/"manifesto.json"
        self.manifest.write_text(json.dumps(doc), encoding="utf-8")

    def test_resultado_nao_expoe_preco_e_nao_homologa(self):
        out = self.base/"relatorio.json"
        self.assertEqual(main(["--manifesto",str(self.manifest),
                               "--saida",str(out)]),0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["numero_edicoes"],3)
        self.assertFalse(payload["publicavel"])
        self.assertFalse(payload["layout_real_homologado"])
        self.assertFalse(payload["dados_reais_persistidos"])
        self.assertNotIn("5.75",out.read_text(encoding="utf-8"))
        self.assertNotIn("5.9",out.read_text(encoding="utf-8"))
        self.assertEqual(list(self.base.glob("*.tmp")),[])

    def test_stdout_continua_somente_metadados(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc=main(["--manifesto",str(self.manifest)])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(stdout.getvalue())["numero_edicoes"],3)

    def test_arquivo_fora_da_raiz_bloqueado(self):
        doc=json.loads(self.manifest.read_text(encoding="utf-8"))
        doc["edicoes"][0]["arquivo"]="../../exfiltracao.xlsx"
        self.manifest.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"fora da raiz"):
            carregar_manifesto_local(self.manifest)

    def test_nao_aceita_url_que_nao_esteja_no_indice(self):
        doc=json.loads(self.manifest.read_text(encoding="utf-8"))
        doc["edicoes"][0]["url"]="https://www.gov.br/anp/link-nao-listado.xlsx"
        self.manifest.write_text(json.dumps(doc),encoding="utf-8")
        st=io.StringIO()
        with redirect_stderr(st):
            rc=main(["--manifesto",str(self.manifest)])
        self.assertEqual(rc,2)
        self.assertIn("não listado",st.getvalue())

    def test_nao_aceita_arquivo_xlsx_alterado_sem_novo_sha(self):
        p=self.base/"semana-1.xlsx"
        p.write_bytes(p.read_bytes()+b"adulterado")
        st=io.StringIO()
        with redirect_stderr(st):
            rc=main(["--manifesto",str(self.manifest)])
        self.assertEqual(rc,2)
        self.assertIn("SHA",st.getvalue())


if __name__ == "__main__":
    unittest.main()
