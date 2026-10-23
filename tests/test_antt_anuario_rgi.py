"""Testes determinísticos da Tabela 12 — amostras sintéticas, âncoras oficiais."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from nivon.antt_anuario_rgi import ErroAnuarioANTT, extrair_tabela_12, persistir, baixar_pdf

def texto_base():
    linhas=[
       "SP – São Paulo            SP – São Paulo             14.403.113         1,24%",
       "MT – Rondonópolis         MT – Sorriso                9.946.350         0,85%",
       "PA – Itaituba             MT – Sinop                  6.350.618         0,55%",
    ]
    for i in range(13):
        letras=chr(65+i)
        toneladas=f"{1_000_000-i*1000:,}".replace(",",".")
        linhas.append(f"MT – Teste {letras}           PA – Teste {letras}             {toneladas}          0,10%")
    return ("Anuário TRC 2025\nTabela 12 - Principais Fluxos (RGIs de Origem e Destino)\n"+
            "\n".join(linhas)+"\nFonte: Painel de Movimentação de Frota")

class TestAnuarioRGI(unittest.TestCase):
    def test_parse_e_granularidade(self):
        rows=extrair_tabela_12(texto_base())
        self.assertEqual(len(rows),16)
        self.assertEqual(rows[1]["toneladas"],9946350)
        self.assertEqual(rows[1]["ano"],2025)
        self.assertEqual(rows[1]["escopo"],"TOP_16_FLUXOS_GERAIS_ANUAIS")
        self.assertIsNone(rows[1]["ncm"])

    def test_idempotencia(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"antt.sqlite"
            rows=extrair_tabela_12(texto_base())
            sha=hashlib.sha256(b"fixture-sintetica").hexdigest()
            a=persistir(db,rows,sha256=sha,data_coleta="2026-10-23T11:00:00+00:00")
            b=persistir(db,rows,sha256=sha,data_coleta="2026-10-23T11:00:00+00:00")
            self.assertEqual(a["estado"],"NOVO_SNAPSHOT")
            self.assertEqual(b["estado"],"IDEMPOTENTE")
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM antt_anuario_rgi_fluxos").fetchone()[0],16)

    def test_rejeita_layout_alterado(self):
        for raw in ("",texto_base().replace("Tabela 12","Tabela 11"),
                    texto_base().replace("6.350.618","6.350.617"),
                    texto_base().replace("Fonte:","Linha:")[:-250]):
            with self.assertRaises(ErroAnuarioANTT):
                extrair_tabela_12(raw)

    def test_url_nao_oficial_bloqueada(self):
        with self.assertRaises(ErroAnuarioANTT):
            baixar_pdf("https://app.powerbi.com/view?r=teste")

if __name__=="__main__":
    unittest.main()
