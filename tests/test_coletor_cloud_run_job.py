"""Coletor nivon-coletor: orquestração, fail-closed e saúde idempotente (offline)."""
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.carga.coletor import executar_fonte, main, registrar_saude
from nivon.fontes import FONTES, Contexto

RAIZ = Path(__file__).resolve().parents[1]
ENV = {"NIVON_COLETOR_HABILITADO": "true", "NIVON_BQ_PROJECT": "nivon-data",
       "NIVON_BQ_DATASET": "nivon_raw", "NIVON_GCS_BUCKET": "nivon-data-raw-2026",
       "CLOUD_RUN_EXECUTION": "nivon-coletor-abc12", "NIVON_REVISAO": "deadbeef"}
CTX = Contexto("nivon-data", "nivon_raw", "nivon-data-raw-2026", Path("/tmp/x"), 2026)


class Runner:
    def __init__(self, falhar=()):
        self.falhar, self.cmds = set(falhar), []

    def __call__(self, cmd, env, timeout, check):
        self.cmds.append((cmd, env))
        if cmd[2] in self.falhar:
            return subprocess.CompletedProcess(cmd, 2)
        return subprocess.CompletedProcess(cmd, 0)


class Fontes(unittest.TestCase):
    def test_quatro_fontes_da_primeira_meta(self):
        self.assertEqual(set(FONTES), {"ptax", "antt_ferrovia", "conab", "maritimo"})

    def test_modulos_existem_no_repositorio(self):
        for f in FONTES.values():
            for cmd in f.etapas(CTX):
                mod = cmd[2]
                base = RAIZ / (mod.replace(".", "/") + ".py") if mod.startswith("scripts.") \
                    else RAIZ / "src" / (mod.replace(".", "/") + ".py")
                self.assertTrue(base.is_file(), mod)

    def test_conab_nunca_cria_tabela_e_antt_usa_ano_corrente(self):
        conab = [c for c in FONTES["conab"].etapas(CTX) if c[2] == "nivon.conab_gcp_schema"][0]
        self.assertNotIn("--aplicar", conab)
        antt = FONTES["antt_ferrovia"].etapas(CTX)[0]
        self.assertEqual(antt[antt.index("--inicio") + 1:antt.index("--fim") + 2],
                         ["2025", "--fim", "2026"])
        self.assertNotIn("--permitir-criar-tabela", antt)


class Execucao(unittest.TestCase):
    def test_para_na_primeira_etapa_com_falha(self):
        r = Runner(falhar={"nivon.conab_incremental"})
        out = executar_fonte(FONTES["conab"], CTX, runner=r)
        self.assertEqual(out["status"], "FALHA")
        self.assertEqual(out["etapa_falha"], "2:nivon.conab_incremental")
        self.assertEqual(len(r.cmds), 2)  # não arquiva nem carrega após a falha

    def test_timeout_vira_falha(self):
        def lento(cmd, env, timeout, check):
            raise subprocess.TimeoutExpired(cmd, timeout)
        out = executar_fonte(FONTES["ptax"], CTX, runner=lento)
        self.assertEqual((out["status"], out["codigo_saida"]), ("FALHA", 124))

    def test_env_da_fonte_maritima(self):
        r = Runner()
        executar_fonte(FONTES["maritimo"], CTX, runner=r)
        self.assertEqual(r.cmds[0][1]["NIVON_MARITIMO_COLETA_HABILITADA"], "true")


class Main(unittest.TestCase):
    def setUp(self):
        self.registros = []

    def registrar(self, resultados, **kw):
        self.registros.append((resultados, kw))

    def test_fail_closed_sem_habilitacao(self):
        r = Runner()
        self.assertEqual(main([], env={**ENV, "NIVON_COLETOR_HABILITADO": ""}, runner=r,
                              registrar=self.registrar), 3)
        self.assertEqual(r.cmds, [])

    def test_projeto_errado_nao_executa(self):
        r = Runner()
        self.assertEqual(main([], env={**ENV, "NIVON_BQ_PROJECT": "outro"}, runner=r,
                              registrar=self.registrar), 3)
        self.assertEqual(r.cmds, [])

    def test_falha_de_uma_fonte_nao_bloqueia_as_outras(self):
        r = Runner(falhar={"scripts.ptax_bcb_bigquery_direto"})
        code = main([], env=ENV, runner=r, registrar=self.registrar)
        self.assertEqual(code, 1)
        resultados, kw = self.registros[0]
        self.assertEqual([x["status"] for x in resultados], ["FALHA", "OK", "OK", "OK"])
        self.assertEqual(kw["execucao_id"], "nivon-coletor-abc12")
        self.assertEqual(kw["revisao"], "deadbeef")

    def test_tudo_ok_retorna_zero_e_subconjunto(self):
        self.assertEqual(main(["--fontes", "ptax,maritimo"], env=ENV, runner=Runner(),
                              registrar=self.registrar), 0)
        self.assertEqual([x["fonte"] for x in self.registros[0][0]], ["ptax", "maritimo"])

    def test_fontes_invalidas_ou_duplicadas(self):
        for f in ("cepea", "ptax,ptax", ""):
            with self.subTest(f=f), self.assertRaises(SystemExit):
                main(["--fontes", f], env=ENV, runner=Runner(), registrar=self.registrar)

    def test_plano_nao_executa(self):
        r = Runner()
        self.assertEqual(main(["--plano"], env={}, runner=r, registrar=self.registrar), 0)
        self.assertEqual((r.cmds, self.registros), ([], []))


class Saude(unittest.TestCase):
    def test_merge_parametrizado_por_execucao_e_fonte(self):
        class Job:
            def result(self):
                return []

        class Cliente:
            def __init__(self):
                self.chamadas = []

            def query(self, sql, job_config):
                self.chamadas.append((sql, job_config))
                return Job()

        class SDK:
            class ScalarQueryParameter:
                def __init__(self, nome, tipo, valor):
                    self.nome, self.tipo, self.valor = nome, tipo, valor

            class QueryJobConfig:
                def __init__(self, query_parameters, maximum_bytes_billed):
                    self.params = {p.nome: p.valor for p in query_parameters}
                    self.limite = maximum_bytes_billed

        agora = datetime(2026, 10, 28, 12, tzinfo=timezone.utc).isoformat()
        res = [{"fonte": "ptax", "status": "OK", "etapa_falha": None, "codigo_saida": 0,
                "inicio": agora, "fim": agora, "duracao_s": 1.0}]
        c = Cliente()
        self.assertEqual(registrar_saude(res, execucao_id="e1", revisao="r", projeto="nivon-data",
                                         cliente=c, sdk=SDK), 1)
        sql, cfg = c.chamadas[0]
        self.assertIn("MERGE `nivon-data.nivon_core.saude_fontes`", sql)
        self.assertIn("ON T.execucao_id = S.execucao_id AND T.fonte = S.fonte", sql)
        self.assertNotIn("ptax", sql)  # valores só por parâmetro
        self.assertEqual(cfg.params["fonte"], "ptax")
        self.assertLessEqual(cfg.limite, 100_000_000)


class Artefatos(unittest.TestCase):
    def test_dockerfile_nao_root_e_entrypoint(self):
        t = (RAIZ / "infra/google_cloud/Dockerfile.coletor").read_text()
        self.assertIn("USER 65532:65532", t)
        self.assertIn("COPY scripts ./scripts", t)
        self.assertIn('"nivon.carga.coletor"', t)

    def test_deploy_privado_sem_iam_amplo(self):
        t = (RAIZ / "scripts/deploy_coletor_job.sh").read_text()
        for proibido in ("allUsers", "allAuthenticatedUsers", "roles/owner", "roles/editor",
                         "projects add-iam-policy-binding"):
            self.assertNotIn(proibido, t)
        self.assertIn("NIVON_COLETOR_HABILITADO=true", t)
        self.assertIn("TABELA_SAUDE_AUSENTE", t)


if __name__ == "__main__":
    unittest.main()
