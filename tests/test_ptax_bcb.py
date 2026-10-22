"""Testes determinísticos de PTAX. NÃO consulta a API real."""
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from nivon.ptax_bcb import (
    ORIGEM, iniciar_banco, janela_incremental, janelas,
    normalizar, sincronizar, url_ptax,
)


def resposta(data="2026-10-20", compra=5.1, venda=5.2, tipo="Fechamento"):
    return {"value": [{
        "cotacaoCompra": compra, "cotacaoVenda": venda,
        "dataHoraCotacao": f"{data} 13:05:00.0",
        "tipoBoletim": tipo,
    }]}


class TestPTAX(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.banco = Path(self.temp.name) / "ptax.sqlite3"

    def test_endpoints_diferenciam_dolar_e_euro(self):
        usd = url_ptax("USD", date(2026, 10, 19), date(2026, 10, 20))
        eur = url_ptax("EUR", date(2026, 10, 19), date(2026, 10, 20))
        self.assertIn("CotacaoDolarPeriodo", usd)
        self.assertIn("CotacaoMoedaPeriodo", eur)
        self.assertIn("olinda.bcb.gov.br", usd)
        self.assertEqual(parse_qs(urlsplit(usd).query)["@dataInicial"], ["'10-19-2026'"])
        self.assertEqual(parse_qs(urlsplit(eur).query)["@moeda"], ["'EUR'"])

    def test_endpoint_dolar_sem_tipo_boletim(self):
        obs = resposta()["value"][0]
        obs.pop("tipoBoletim")
        row = normalizar(obs, "USD", date(2026, 10, 20),
                         date(2026, 10, 20), "2026-10-21T14:00:00+00:00")
        self.assertEqual(row["tipo_boletim"], "COTACAO_DOLAR_DIARIA")
        with self.assertRaises(ValueError):
            normalizar(obs, "EUR", date(2026, 10, 20),
                       date(2026, 10, 20), "2026-10-21T14:00:00+00:00")

    def test_resposta_paginada_gera_erro_explicito(self):
        with self.assertRaises(ValueError):
            sincronizar(self.banco, "USD", inicio=date(2026, 10, 20),
                        fim=date(2026, 10, 20),
                        transporte=lambda u: {"value": [], "@odata.nextLink": "pagina2"},
                        hoje=date(2026, 10, 21))

    def test_normalizacao_preserva_hora_sem_inventar_publicacao(self):
        row = normalizar(resposta()["value"][0], "USD", date(2026, 10, 20),
                         date(2026, 10, 20), "2026-10-21T14:00:00+00:00")
        self.assertEqual(row["data_referencia"], "2026-10-20")
        self.assertEqual(row["data_hora_cotacao_origem"], "2026-10-20 13:05:00.0")
        self.assertIsNone(row["data_publicacao"])
        self.assertEqual(row["unidade"], "BRL/USD")
        self.assertEqual(row["fonte_original"], ORIGEM)

    def test_coleta_idempotente_e_revisoes_preservadas(self):
        atual = [resposta()]
        def stub(url):
            return atual[0]
        kw = dict(banco=self.banco, moeda="USD", inicio=date(2026, 10, 20),
                  fim=date(2026, 10, 20), hoje=date(2026, 10, 21), transporte=stub)
        self.assertEqual(sincronizar(**kw)["novos_ou_revisados"], 1)
        self.assertEqual(sincronizar(**kw)["repetidos"], 1)
        atual[0] = resposta(venda=5.25)
        self.assertEqual(sincronizar(**kw)["novos_ou_revisados"], 1)
        with sqlite3.connect(self.banco) as conn:
            self.assertEqual(conn.execute("select count(*) from ptax_observacoes").fetchone()[0], 2)
            self.assertEqual(conn.execute("select count(distinct chave) from ptax_observacoes").fetchone()[0], 1)
            self.assertEqual(conn.execute("select count(*) from ptax_execucoes").fetchone()[0], 3)

    def test_mantem_multiplo_boletim_e_compra_venda(self):
        resultado = {"value": resposta()["value"] + resposta(compra=5.0, venda=5.1, tipo="Abertura")["value"]}
        out = sincronizar(self.banco, "USD", inicio=date(2026, 10, 20),
                          fim=date(2026, 10, 20), transporte=lambda url: resultado,
                          hoje=date(2026, 10, 21))
        self.assertEqual(out["recebidos"], 2)
        with sqlite3.connect(self.banco) as conn:
            rows = conn.execute("select tipo_boletim, cotacao_compra, cotacao_venda from ptax_observacoes order by tipo_boletim").fetchall()
            self.assertEqual(rows, [("Abertura", "5.0", "5.1"), ("Fechamento", "5.1", "5.2")])

    def test_periodo_vazio_nao_cria_cotacao_zerada(self):
        out = sincronizar(self.banco, "USD", inicio=date(2026, 10, 18),
                          fim=date(2026, 10, 18), transporte=lambda u: {"value": []},
                          hoje=date(2026, 10, 21))
        self.assertEqual(out["estado"], "SEM_COTACAO_NO_PERIODO")
        with sqlite3.connect(self.banco) as conn:
            self.assertEqual(conn.execute("select count(*) from ptax_observacoes").fetchone()[0], 0)

    def test_erro_de_formato_nao_salva_dados(self):
        with self.assertRaises(ValueError):
            sincronizar(self.banco, "USD", inicio=date(2026, 10, 20),
                        fim=date(2026, 10, 20), transporte=lambda u: {"value": [{"cotacaoCompra": 0}]},
                        hoje=date(2026, 10, 21))
        with sqlite3.connect(self.banco) as conn:
            self.assertEqual(conn.execute("select count(*) from ptax_execucoes").fetchone()[0], 0)

    def test_janela_31_dias_sem_lacunas(self):
        dias = list(janelas(date(2026, 8, 1), date(2026, 10, 21)))
        self.assertGreater(len(dias), 1)
        self.assertEqual(dias[0][0], date(2026, 8, 1))
        self.assertEqual(dias[-1][1], date(2026, 10, 21))
        for anterior, seguinte in zip(dias, dias[1:]):
            self.assertEqual(anterior[1].toordinal() + 1, seguinte[0].toordinal())

    def test_incremental_reprocessa_tres_dias(self):
        sincronizar(self.banco, "USD", inicio=date(2026, 10, 20),
                    fim=date(2026, 10, 20), transporte=lambda u: resposta(),
                    hoje=date(2026, 10, 21))
        with sqlite3.connect(self.banco) as conn:
            inicio, fim = janela_incremental(conn, "USD", date(2026, 10, 21))
        self.assertEqual(inicio, date(2026, 10, 17))
        self.assertEqual(fim, date(2026, 10, 21))

    def test_periodo_historico_e_futuro_protegidos(self):
        with self.assertRaises(ValueError):
            sincronizar(self.banco, "EUR", inicio=date(2000, 1, 1),
                        fim=date(2000, 1, 3), transporte=lambda u: {"value": []})
        with self.assertRaises(ValueError):
            sincronizar(self.banco, "USD", inicio=date(2026, 10, 20),
                        fim=date(2027, 1, 1), transporte=lambda u: {"value": []},
                        hoje=date(2026, 10, 21))
        with self.assertRaises(ValueError):
            sincronizar(self.banco, "USD", inicio=date(2020, 1, 1),
                        fim=date(2021, 1, 2), transporte=lambda u: {"value": []},
                        hoje=date(2026, 10, 21))

    def test_erro_rede_nao_e_sucesso(self):
        def fora(url):
            raise OSError("offline")
        with self.assertRaises(OSError):
            sincronizar(self.banco, "USD", inicio=date(2026, 10, 20),
                        fim=date(2026, 10, 20), transporte=fora,
                        hoje=date(2026, 10, 21))

    def test_multiplas_paginas_sem_sobreposicao(self):
        calls = []
        def fake(url):
            p = parse_qs(urlsplit(url).query)
            inicio = date.strptime(p["@dataInicial"][0].strip("'"), "%m-%d-%Y") if hasattr(date, "strptime") else None
            # Cada página retorna vazia; testamos somente a contagem de URLs.
            calls.append(url)
            return {"value": []}
        sincronizar(self.banco, "USD", inicio=date(2026, 9, 1),
                    fim=date(2026, 10, 21), transporte=fake,
                    hoje=date(2026, 10, 21))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
