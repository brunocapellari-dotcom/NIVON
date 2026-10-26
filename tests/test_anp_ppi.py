"""Regressão offline do PPI ANP: 4 abas, unidades, qualidade e ledger."""
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

from nivon.anp_ppi import (
    XLSX_URL, ABAS, DATASET, ErroPPI, baixar_planilha,
    normalizar_xlsx, coletar_anp_ppi,
)
from nivon.ingestao_fontes_reais import exportar_jsonl


def arquivo_exemplo(*, valor_diesel=5.5, duplicar=False, ausente=False):
    wb = Workbook()
    wb.remove(wb.active)
    for aba in ABAS:
        ws = wb.create_sheet(aba)
        ws.append(["Preços PPI ANP"])
        ws.append(["R$/litro"])
        ws.append(["Semana", "Terminal A", "Terminal B", None, "Variação percentual"])
        ws.append(["05/10/2026 a 09/10/2026", 4.2, 4.3])
        primeiro = valor_diesel if "Diesel" in aba else 4.4
        if ausente and "GLP" in aba:
            primeiro = None
        ws.append(["12/10/2026 a 16/10/2026", primeiro, 4.5])
        if duplicar and "Diesel" in aba:
            ws.append(["12/10/2026 a 16/10/2026", 4.8, 4.9])
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


class Resposta:
    status = 200

    def __init__(self, blob, url=XLSX_URL):
        self.url = url
        self.blob = blob

    def geturl(self):
        return self.url

    def read(self, tamanho):
        return self.blob[:tamanho]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Cliente:
    def __init__(self, resp):
        self.resp = resp
        self.urls = []

    def open(self, req, timeout=60):
        self.urls.append(req.full_url)
        return self.resp


@unittest.skipIf(Workbook is None, "requer extra excel: pip install -e '.[excel]'")
class AnpPpiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.agora = datetime(2026, 10, 26, 13, tzinfo=timezone.utc)

    def test_quatro_produtos_com_periodos_e_unidades(self):
        obs, resumo = normalizar_xlsx(arquivo_exemplo(), hoje=date(2026, 10, 26))
        self.assertEqual(len(obs), 16)
        self.assertEqual(set(resumo), {"gasolina", "diesel", "qav", "glp"})
        self.assertEqual(resumo["diesel"]["semanas"], 2)
        self.assertEqual(resumo["glp"]["unidade"], "R$/13kg")
        diesel = next(o for o in obs if o["campos"]["produto"] == "diesel"
                      and o["referencia"] == "2026-10-16"
                      and o["campos"]["terminal"] == "Terminal A")
        self.assertEqual(diesel["valor"], "5.5")
        self.assertEqual(diesel["natureza"], "INFORMADO")
        self.assertEqual(diesel["competencia"], "2026-10-12")
        self.assertTrue(diesel["campos"]["sem_tributos"])
        self.assertEqual(diesel["campos"]["fonte_primaria"], "ANP")

    def test_ledger_idempotente_e_revisao_da_semana(self):
        cliente = Cliente(Resposta(arquivo_exemplo()))
        args = {
            "banco": self.base / "fontes.sqlite",
            "raw_dir": self.base / "raw",
            "executar": True,
            "cliente": cliente,
            "instante": self.agora,
            "hoje": date(2026, 10, 26),
        }
        a = coletar_anp_ppi(**args)
        b = coletar_anp_ppi(**args)
        self.assertEqual(a["novas_observacoes"], 16)
        self.assertEqual(b["novas_observacoes"], 0)
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertEqual(a["ultima_semana"], "2026-10-16")
        self.assertTrue(Path(a["arquivo_raw"]).exists())
        self.assertEqual(cliente.urls, [XLSX_URL, XLSX_URL])
        destino = self.base / "staging.jsonl"
        result = exportar_jsonl(
            banco=args["banco"], destino=destino, dataset_id=DATASET
        )
        self.assertEqual(result["observacoes"], 16)
        first = json.loads(destino.read_text().splitlines()[0])
        self.assertEqual(first["dataset_id"], DATASET)
        self.assertIn("fingerprint", first)
        cliente.resp = Resposta(arquivo_exemplo(valor_diesel=5.8))
        revisado = coletar_anp_ppi(**args)
        self.assertEqual(revisado["novas_observacoes"], 1)
        with sqlite3.connect(args["banco"]) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM snapshots WHERE dataset_id=?", (DATASET,)).fetchone()[0],
                2
            )

    def test_mudancas_inseguras_nao_entram_no_ledger(self):
        with self.assertRaises(PermissionError):
            coletar_anp_ppi(banco=self.base / "db", raw_dir=self.base / "raw")
        with self.assertRaises(ErroPPI):
            normalizar_xlsx(arquivo_exemplo(duplicar=True), hoje=date(2026, 10, 26))
        with self.assertRaises(ErroPPI):
            normalizar_xlsx(arquivo_exemplo(valor_diesel=-3), hoje=date(2026, 10, 26))
        with self.assertRaises(ErroPPI):
            normalizar_xlsx(arquivo_exemplo(), hoje=date(2025, 10, 26))
        with self.assertRaises(ErroPPI):
            baixar_planilha(cliente=Cliente(Resposta(b"<html>erro</html>")))
        with self.assertRaises(ErroPPI):
            baixar_planilha(cliente=Cliente(Resposta(arquivo_exemplo(), url="https://evil.example/x")))


if __name__ == "__main__":
    unittest.main()
