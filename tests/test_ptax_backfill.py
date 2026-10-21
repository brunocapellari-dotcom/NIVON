"""Backfill PTAX — testes offline de retomada, histórico e segurança."""
from datetime import date, datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from nivon.ptax_backfill import (
    RAIZ_REPO, banco_privado, janelas_backfill, recuperar_historico,
)


def registro(data: date, valor: str = "5.00") -> dict:
    return {
        "cotacaoCompra": valor,
        "cotacaoVenda": str(float(valor) + 0.01),
        "dataHoraCotacao": f"{data.isoformat()} 13:05:00.0",
        # USD diário não tem tipoBoletim
    }


def inicio_da_url(url: str) -> date:
    params = parse_qs(urlsplit(url).query)
    return datetime.strptime(params["@dataInicial"][0].strip("'"), "%m-%d-%Y").date()


class TestBackfill(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.banco = Path(d.name) / "historico.sqlite3"
        self.inicio = date(2026, 1, 1)
        self.fim = date(2026, 3, 4)
        self.hoje = date(2026, 10, 21)
        self.kw = dict(
            banco=self.banco, moeda="USD", inicio=self.inicio, fim=self.fim,
            dias_janela=31, max_janelas=8, segundos_entre_consultas=0,
            hoje=self.hoje,
        )

    def test_janelas_continuas_inclusive_leap_year(self):
        t = list(janelas_backfill(date(2024, 2, 1), date(2024, 4, 1), dias=20))
        self.assertEqual(t[0][0], date(2024, 2, 1))
        self.assertEqual(t[-1][1], date(2024, 4, 1))
        for anterior, seguinte in zip(t, t[1:]):
            self.assertEqual((seguinte[0] - anterior[1]).days, 1)
        self.assertEqual(sum((b - a).days + 1 for a, b in t), 61)

    def test_planejamento_sem_requisicao_e_sem_db(self):
        def proibido(_):
            self.fail("dry-run não pode consultar API")
        r = recuperar_historico(**dict(self.kw, dry_run=True, transporte=proibido))
        self.assertEqual(r["estado"], "PLANEJADO_SEM_COLETA")
        self.assertEqual(r["janelas_totais"], 2 + 1)
        self.assertFalse(self.banco.exists())

    def test_limite_e_retoma_sem_perder_janelas(self):
        chamadas = []
        def simulado(url):
            a = inicio_da_url(url)
            chamadas.append(a)
            return {"value": [registro(a)]}
        r1 = recuperar_historico(**dict(self.kw, max_janelas=1, transporte=simulado))
        self.assertEqual(r1["estado"], "PARCIAL_LIMITE")
        self.assertEqual(r1["janelas_pendentes"], 2)
        r2 = recuperar_historico(**dict(self.kw, max_janelas=8, transporte=simulado))
        self.assertEqual(r2["estado"], "COMPLETO")
        self.assertEqual(r2["janelas_puladas"], 1)
        self.assertEqual(len(chamadas), 3)
        r3 = recuperar_historico(**dict(self.kw, transporte=simulado))
        self.assertEqual(r3["janelas_executadas"], 0)
        self.assertEqual(len(chamadas), 3)
        with sqlite3.connect(self.banco) as con:
            self.assertEqual(con.execute("select count(*) from ptax_observacoes").fetchone()[0], 3)
            self.assertEqual(con.execute("select count(*) from ptax_execucoes").fetchone()[0], 3)

    def test_falha_segunda_janela_tem_checkpoint_e_retentativa(self):
        chamadas = []
        def instavel(url):
            a = inicio_da_url(url)
            chamadas.append(a)
            if a == date(2026, 2, 1):
                raise OSError("Falha simulada")
            return {"value": [registro(a)]}
        with self.assertRaisesRegex(RuntimeError, "interrompido"):
            recuperar_historico(**dict(self.kw, transporte=instavel))
        with sqlite3.connect(self.banco) as con:
            estados = con.execute(
                "SELECT inicio,estado FROM ptax_backfill_janelas ORDER BY inicio"
            ).fetchall()
            self.assertEqual(estados, [("2026-01-01", "SUCESSO"), ("2026-02-01", "FALHOU")])
            self.assertEqual(con.execute("select count(*) from ptax_observacoes").fetchone()[0], 1)
        def recomeçar(url):
            a = inicio_da_url(url)
            chamadas.append(a)
            return {"value": [registro(a)]}
        saida = recuperar_historico(**dict(self.kw, transporte=recomeçar))
        self.assertEqual(saida["estado"], "COMPLETO")
        self.assertEqual(saida["janelas_puladas"], 1)
        with sqlite3.connect(self.banco) as con:
            self.assertEqual(con.execute(
                "select tentativas from ptax_backfill_janelas where inicio='2026-02-01'"
            ).fetchone()[0], 2)

    def test_revalidacao_preserva_versoes_corrigidas(self):
        atual = ["5.00"]
        def consulta(url):
            return {"value": [registro(inicio_da_url(url), atual[0])]}
        self.assertEqual(recuperar_historico(**dict(self.kw, transporte=consulta))["novos_ou_revisados"], 3)
        atual[0] = "5.12"
        saida = recuperar_historico(**dict(self.kw, transporte=consulta, revalidar=True))
        self.assertEqual(saida["novos_ou_revisados"], 3)
        with sqlite3.connect(self.banco) as con:
            self.assertEqual(con.execute("select count(*) from ptax_observacoes").fetchone()[0], 6)
            self.assertEqual(con.execute("select count(distinct chave) from ptax_observacoes").fetchone()[0], 3)

    def test_janelas_vazias_antigas_sao_checkpointadas(self):
        vazio = lambda url: {"value": []}
        out = recuperar_historico(**dict(self.kw, transporte=vazio))
        self.assertEqual(out["estado"], "COMPLETO")
        out2 = recuperar_historico(**dict(self.kw, transporte=vazio))
        self.assertEqual(out2["janelas_executadas"], 0)
        with sqlite3.connect(self.banco) as con:
            self.assertEqual(con.execute("select count(*) from ptax_backfill_janelas").fetchone()[0], 3)

    def test_janelas_recentes_sao_revalidadas(self):
        kw = dict(self.kw, inicio=date(2026, 10, 18), fim=date(2026, 10, 21))
        chamadas = []
        def vazio(url):
            chamadas.append(url)
            return {"value": []}
        recuperar_historico(**dict(kw, transporte=vazio))
        recuperar_historico(**dict(kw, transporte=vazio))
        self.assertEqual(len(chamadas), 2)

    def test_db_no_repositorio_e_symlink_bloqueados(self):
        with self.assertRaises(ValueError):
            banco_privado(RAIZ_REPO / "arquivo.sqlite3")
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "atalho"
            link.symlink_to(RAIZ_REPO, target_is_directory=True)
            with self.assertRaises(ValueError):
                banco_privado(link / "arquivo.sqlite3")

    def test_parametros_invalidos_nao_criam_banco(self):
        for kwargs in [
            dict(self.kw, dias_janela=32),
            dict(self.kw, max_janelas=0),
            dict(self.kw, moeda="INR"),
            dict(self.kw, inicio=date(2027, 1, 1)),
        ]:
            with self.assertRaises(ValueError):
                recuperar_historico(**kwargs)
        self.assertFalse(self.banco.exists())


if __name__ == "__main__":
    unittest.main()
