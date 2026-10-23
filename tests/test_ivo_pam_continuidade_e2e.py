"""PAM operacional: planejamento incremental, retentativa e alertas as-of.

Integra staging real SQLite com recortes SIDRA canônicos. Sem internet.
"""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.ivo_pam_continuidade import (
    ErroContinuidadePAM, main, planejar_continuidade_pam,
)
from nivon.ivo_pam_operacao import abrir_operacao_pam, processar_captura_pam
from nivon.sidra_pam import planejar_pam_1612

T = datetime(2026, 10, 23, 11, tzinfo=timezone.utc)
P1 = {"municipio_ibge": "5107958", "ano": 2021,
      "variavel": "214", "categoria_c81": "2713"}
P2 = {"municipio_ibge": "5105259", "ano": 2024,
      "variavel": "214", "categoria_c81": "2713"}
P3 = {"municipio_ibge": "5107925", "ano": 2024,
      "variavel": "214", "categoria_c81": "2713"}


def plan(d):
    return planejar_pam_1612(
        municipio_ibge=d["municipio_ibge"], ano=d["ano"],
        codigo_produto_c81=d["categoria_c81"], codigo_variavel=d["variavel"],
    )


def sidra(d, value="100"):
    return json.dumps([
        {"D1C": "Município (Código)", "D2C": "Variável (Código)",
         "D3C": "Ano (Código)",
         "D4C": "Produto das lavouras temporárias (Código)",
         "V": "Valor", "MN": "Unidade de Medida"},
        {"D1C": d["municipio_ibge"], "D2C": d["variavel"],
         "D3C": str(d["ano"]), "D4C": d["categoria_c81"],
         "V": value, "MN": "Toneladas"},
    ], ensure_ascii=False).encode("utf-8")


class TestIVOContinuidadeE2E(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.dbpath = self.base / "operacional.sqlite"
        self.db = abrir_operacao_pam(self.dbpath)
        self.addCleanup(self.db.close)
        self.cofre = self.base / "cofre"
        self.tasks = [dict(P1), dict(P2), dict(P3)]

    def store(self, item=P1, val="100", when=T):
        return processar_captura_pam(
            db=self.db, raiz=self.cofre, plano=plan(item),
            payload=sidra(item, val), coletado_em=when,
            origem="TRANSPORTE_TESTE",
        )

    def report(self, cutoff=T+timedelta(days=1), **kwargs):
        return planejar_continuidade_pam(
            db=self.db, tarefas=self.tasks, corte=cutoff, raiz=self.cofre, **kwargs,
        )

    def test_sem_capturas_gera_backlog_estruturado(self):
        r = self.report()
        self.assertEqual(r["pendentes"], 3)
        self.assertEqual(r["selecionados"], 3)
        self.assertEqual(r["alertas"], 0)
        self.assertEqual(len(r["tarefas_pendentes"]), 3)
        self.assertTrue(all(x["estado"] == "PRIMEIRA_CAPTURA_PENDENTE"
                            for x in r["situacoes"]))
        self.assertFalse(r["autoriza_coleta"])
        self.assertEqual(r["requisicoes_externas_executadas"], 0)
        self.assertFalse(r["escrita_no_sqlite"])

    def test_captura_recente_nao_requisita_outra_e_mantem_faltantes(self):
        self.store(P1)
        self.store(P2)
        r = self.report()
        self.assertEqual(r["pendentes"], 1)
        self.assertEqual(r["tarefas_pendentes"], [P3])
        self.assertEqual([x["estado"] for x in r["situacoes"]],
                         ["CAPTURA_RECENTE", "CAPTURA_RECENTE",
                          "PRIMEIRA_CAPTURA_PENDENTE"])
        self.assertEqual(r, self.report())

    def test_dado_antigo_volta_ao_plano_sem_coletar(self):
        self.store()
        r = self.report(cutoff=T+timedelta(days=8))
        self.assertEqual(r["situacoes"][0]["estado"], "CAPTURA_DESATUALIZADA")
        self.assertEqual(r["pendentes"], 3)
        self.assertFalse(r["autoriza_coleta"])

    def test_limite_exato_de_frescor(self):
        self.store()
        x = self.report(cutoff=T+timedelta(days=6, hours=23),
                        idade_maxima_dias=7)
        self.assertEqual(x["situacoes"][0]["estado"], "CAPTURA_RECENTE")
        y = self.report(cutoff=T+timedelta(days=7), idade_maxima_dias=7)
        self.assertEqual(y["situacoes"][0]["estado"], "CAPTURA_DESATUALIZADA")

    def test_revisao_numerica_cria_alerta_sem_data_oficial(self):
        self.store(P1, "100", T)
        self.store(P1, "120", T+timedelta(hours=2))
        r = self.report(cutoff=T+timedelta(hours=3))
        self.assertEqual(r["alertas"], 1)
        self.assertEqual(r["situacoes"][0]["mudancas_entre_capturas"], 1)
        evento = r["alertas_de_revisao"][0]
        self.assertEqual(evento["tipo"], "VALOR_ALTERADO")
        self.assertFalse(evento["publicacao_oficial_na_data_comprovada"])
        self.assertFalse(evento["valor_numerico_publicavel"])
        self.assertNotIn('"valor": 120', str(r))
        self.assertEqual(r["situacoes"][0]["capturas_no_corte"], 2)

    def test_corte_historico_nao_vaza_revision_futura(self):
        self.store(P1, "100", T)
        self.store(P1, "120", T+timedelta(hours=2))
        before = self.report(cutoff=T+timedelta(hours=1))
        after = self.report(cutoff=T+timedelta(hours=3))
        self.assertEqual(before["alertas"], 0)
        self.assertEqual(before["situacoes"][0]["capturas_no_corte"], 1)
        self.assertEqual(after["alertas"], 1)
        self.assertNotIn(after["alertas_de_revisao"][0]["arquivo_sha256"],
                         str(before))

    def test_vintages_sem_mudanca_nao_criam_falso_alerta(self):
        self.store(P1, "100", T)
        self.store(P1, "100", T+timedelta(hours=2))
        r = self.report(cutoff=T+timedelta(hours=3))
        self.assertEqual(r["alertas"], 0)
        self.assertEqual(r["situacoes"][0]["capturas_no_corte"], 2)
        self.assertEqual(r["situacoes"][0]["mudancas_entre_capturas"], 0)

    def test_resultado_falho_reinsere_so_o_alvo_correspondente(self):
        self.store(P1)
        self.store(P2)
        resultado = {
            "estado": "LOTE_PAM_CONCLUIDO", "total": 3,
            "aprovados": 2, "falhas": 1,
            "resultados": [{"ordem": 0, "status": "ERRO", "tipo": "TimeoutError"},
                           {"ordem": 1, "status": "OK"},
                           {"ordem": 2, "status": "OK"}],
        }
        r = self.report(resultado_anterior=resultado)
        self.assertEqual(r["situacoes"][0]["estado"], "RETOMAR_FALHA_ANTERIOR")
        self.assertEqual(r["situacoes"][1]["estado"], "CAPTURA_RECENTE")
        self.assertEqual(r["pendentes"], 2)
        self.assertEqual(r["tarefas_pendentes"], [P1, P3])
        self.assertNotIn("TimeoutError", str(r))

    def test_resultado_falso_e_ordem_invalida_nao_passam(self):
        self.store()
        previous = {
            "estado": "LOTE_PAM_CONCLUIDO", "total": 1,
            "aprovados": 0, "falhas": 1,
            "resultados": [{"ordem": 7, "status": "ERRO"}],
        }
        with self.assertRaises(ErroContinuidadePAM):
            self.report(resultado_anterior=previous)
        previous["resultados"][0]["ordem"] = 0
        previous["falhas"] = 0
        with self.assertRaises(ErroContinuidadePAM):
            self.report(resultado_anterior=previous)

    def test_recortes_duplicados_ou_semantica_invalida_bloqueiam(self):
        for tasks in ([P1, P1], [dict(P1, variavel="999")],
                      [dict(P1, municipio_ibge="123")], []):
            with self.subTest(tasks=tasks), self.assertRaises(ErroContinuidadePAM):
                planejar_continuidade_pam(db=self.db, tarefas=tasks, corte=T, raiz=self.cofre)

    def test_hash_do_objeto_corrompido_bloqueia_planejamento(self):
        row = self.store()
        original = self.cofre / "objetos_sha256" / (row["sha256"] + ".bin")
        original.write_bytes(b"corrupcao intencional")
        with self.assertRaises(ErroContinuidadePAM):
            self.report()

    def test_valor_sqlite_alterado_bloqueia_alertas(self):
        self.store()
        self.db.execute("UPDATE pam_vintages SET valor=777777")
        self.db.commit()
        with self.assertRaises(ErroContinuidadePAM):
            self.report()

    def test_corte_timezone_invalido_e_idade_fora_do_limite(self):
        with self.assertRaises(ErroContinuidadePAM):
            self.report(cutoff=T.replace(tzinfo=None))
        for idade in (0, 366, True):
            with self.assertRaises(ErroContinuidadePAM):
                self.report(idade_maxima_dias=idade)

    def test_clI_idempotente_e_sqlite_so_leitura(self):
        self.store()
        self.db.commit()
        taskpath = self.base / "tarefas.json"
        taskpath.write_text(json.dumps(self.tasks), encoding="utf-8")
        dest = self.base / "continuidade.json"
        args = ["--db", str(self.dbpath), "--acervo", str(self.cofre),
                "--tarefas", str(taskpath),
                "--saida", str(dest),
                "--corte", (T+timedelta(days=1)).isoformat()]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(args), 0)
        self.assertEqual(json.loads(buf.getvalue())["pendentes"], 2)
        first = dest.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        self.assertEqual(first, dest.read_bytes())
        dest.write_text("tamper")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 2)

    def test_clI_sem_banco_nao_cria_sqlite(self):
        path = self.base / "no.db"
        tasks = self.base / "tasks.json"
        tasks.write_text(json.dumps(self.tasks))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--db", str(path), "--acervo", str(self.cofre),
                "--tarefas", str(tasks),
                "--saida", str(self.base / "report.json"),
                "--corte", T.isoformat(),
            ]), 2)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
