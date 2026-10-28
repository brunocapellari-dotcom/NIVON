"""Coletor nivon-coletor: orquestração, fail-closed e saúde idempotente (offline)."""
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.carga.coletor import (executar_fonte, fontes_vencidas, main, registrar_saude,
                                 ultimas_execucoes_ok)
from nivon.carga.registro_fontes import FONTES, Contexto

RAIZ = Path(__file__).resolve().parents[1]
ENV = {"NIVON_COLETOR_HABILITADO": "true", "NIVON_BQ_PROJECT": "nivon-data",
       "NIVON_BQ_DATASET": "nivon_raw", "NIVON_GCS_BUCKET": "nivon-data-raw-2026",
       "CLOUD_RUN_EXECUTION": "nivon-coletor-abc12", "NIVON_REVISAO": "deadbeef"}
_TMP = tempfile.TemporaryDirectory(prefix="nivon-teste-coletor-")
CTX = Contexto("nivon-data", "nivon_raw", "nivon-data-raw-2026", Path(_TMP.name), 2026)


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


    def test_conab_cria_pasta_raw_privada_antes_das_etapas(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Contexto("nivon-data", "nivon_raw", "nivon-data-raw-2026", Path(tmp), 2026)
            etapas = FONTES["conab"].etapas(ctx)
            raw = Path(tmp) / "conab_raw"
            self.assertTrue(raw.is_dir() and not raw.is_symlink())
            self.assertEqual(stat.S_IMODE(raw.stat().st_mode), 0o700)
            self.assertIn(str(raw), etapas[1])  # --pasta-raw do conab_incremental
            os.chmod(raw, 0o755)  # pasta já existente com modo aberto volta a 0700
            FONTES["conab"].etapas(ctx)
            self.assertEqual(stat.S_IMODE(raw.stat().st_mode), 0o700)

    def test_conab_pasta_passa_na_verificacao_do_modulo(self):
        from nivon.conab_execucao_edicao import _privado
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Contexto("nivon-data", "nivon_raw", "nivon-data-raw-2026", Path(tmp), 2026)
            FONTES["conab"].etapas(ctx)
            _privado(Path(tmp) / "conab_raw")  # não levanta ErroExecucaoConab

    def test_gates_de_carga_so_na_ptax(self):
        gates = {"NIVON_GCP_WRITE_APPROVED": "true", "NIVON_GCP_COST_REVIEWED": "true"}
        self.assertEqual(FONTES["ptax"].env, gates)
        for nome in ("antt_ferrovia", "conab", "maritimo"):
            self.assertFalse(set(gates) & set(FONTES[nome].env), nome)


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


AGORA = datetime(2026, 10, 28, 17, 15, tzinfo=timezone.utc)


def sem_historico(projeto):
    return {}


class Main(unittest.TestCase):
    def setUp(self):
        self.registros = []

    def registrar(self, resultados, **kw):
        self.registros.append((resultados, kw))

    def rodar(self, argv, env=ENV, runner=None, consultar=sem_historico):
        return main(argv, env=env, runner=runner or Runner(), registrar=self.registrar,
                    consultar_ultimas=consultar, agora=lambda: AGORA)

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
        code = self.rodar([], runner=r)
        self.assertEqual(code, 1)
        resultados, kw = self.registros[0]
        self.assertEqual([x["status"] for x in resultados], ["FALHA", "OK", "OK", "OK"])
        self.assertEqual(kw["execucao_id"], "nivon-coletor-abc12")
        self.assertEqual(kw["revisao"], "deadbeef")

    def test_tudo_ok_retorna_zero_e_subconjunto(self):
        self.assertEqual(self.rodar(["--fontes", "ptax,maritimo"]), 0)
        self.assertEqual([x["fonte"] for x in self.registros[0][0]], ["ptax", "maritimo"])

    def test_fontes_invalidas_ou_duplicadas(self):
        for f in ("cepea", "ptax,ptax", ""):
            with self.subTest(f=f), self.assertRaises(SystemExit):
                self.rodar(["--fontes", f])

    def test_plano_nao_executa(self):
        r = Runner()
        self.assertEqual(main(["--plano"], env={}, runner=r, registrar=self.registrar), 0)
        self.assertEqual((r.cmds, self.registros), ([], []))


    def test_so_roda_fontes_vencidas(self):
        ultimas = {"ptax": AGORA - timedelta(hours=6, minutes=1),     # 11:14 -> vencida
                   "maritimo": AGORA - timedelta(hours=2),            # não vencida
                   "conab": AGORA - timedelta(hours=23),              # não vencida
                   "antt_ferrovia": AGORA - timedelta(days=8)}        # vencida
        r = Runner()
        self.assertEqual(self.rodar([], runner=r, consultar=lambda p: ultimas), 0)
        self.assertEqual([x["fonte"] for x in self.registros[0][0]], ["ptax", "antt_ferrovia"])
        self.assertEqual({c[0][2] for c in r.cmds},
                         {"scripts.ptax_bcb_bigquery_direto", "nivon.antt_gcp_pipeline"})

    def test_nada_vencido_nao_executa_nem_registra(self):
        ultimas = {n: AGORA for n in FONTES}
        r = Runner()
        self.assertEqual(self.rodar([], runner=r, consultar=lambda p: ultimas), 0)
        self.assertEqual((r.cmds, self.registros), ([], []))

    def test_consulta_falha_roda_todas(self):
        def quebrada(projeto):
            raise RuntimeError("BigQuery indisponível")
        self.assertEqual(self.rodar([], consultar=quebrada), 0)
        self.assertEqual(len(self.registros[0][0]), 4)

    def test_forcar_ignora_intervalo(self):
        ultimas = {n: AGORA for n in FONTES}
        self.assertEqual(self.rodar(["--forcar"], consultar=lambda p: ultimas), 0)
        self.assertEqual(len(self.registros[0][0]), 4)


class Vencimento(unittest.TestCase):
    def test_intervalos_pedidos(self):
        self.assertEqual({n: f.intervalo for n, f in FONTES.items()},
                         {"ptax": timedelta(hours=6), "maritimo": timedelta(hours=6),
                          "conab": timedelta(hours=24), "antt_ferrovia": timedelta(days=7)})

    def test_folga_da_agenda_tres_vezes_ao_dia(self):
        # Execução anterior começou 11:15:40; a próxima checagem é 17:15:10.
        anterior = datetime(2026, 10, 28, 11, 15, 40, tzinfo=timezone.utc)
        agora = datetime(2026, 10, 28, 17, 15, 10, tzinfo=timezone.utc)
        self.assertEqual(fontes_vencidas(["ptax"], {"ptax": anterior}, agora), ["ptax"])
        self.assertEqual(fontes_vencidas(["ptax"], {"ptax": agora - timedelta(hours=5)}, agora), [])

    def test_consulta_de_ultimas_limitada(self):
        class Cfg:
            def __init__(self, maximum_bytes_billed):
                self.limite = maximum_bytes_billed

        class SDK:
            QueryJobConfig = Cfg

        class Cliente:
            def query(self, sql, job_config):
                self.sql, self.cfg = sql, job_config
                return type("J", (), {"result": lambda _: [{"fonte": "ptax", "ultima": AGORA}]})()

        c = Cliente()
        self.assertEqual(ultimas_execucoes_ok("nivon-data", cliente=c, sdk=SDK), {"ptax": AGORA})
        self.assertIn("status = 'OK'", c.sql)
        self.assertIn("INTERVAL 8 DAY", c.sql)
        self.assertLessEqual(c.cfg.limite, 100_000_000)


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
        self.assertIn('CRON="${NIVON_COLETOR_CRON:-15 11,17,23 * * *}"', t)

    def test_preparacao_minima_e_idempotente(self):
        t = (RAIZ / "scripts/preparar_coletor_gcp.sh").read_text()
        self.assertIn("set -euo pipefail", t)
        for proibido in ("allUsers", "allAuthenticatedUsers", "roles/owner", "roles/editor"):
            self.assertNotIn(proibido, t)
        papeis_projeto = [l.split("--role=")[1].split()[0] for l in t.splitlines()
                          if "--role=" in l and "projects add-iam-policy-binding" in
                          t.splitlines()[t.splitlines().index(l) - 1]]
        self.assertEqual(sorted(papeis_projeto), ["roles/bigquery.jobUser", "roles/logging.logWriter"])
        self.assertIn("DATASETS=(nivon_core nivon_raw)", t)
        self.assertIn('"keepCount": 3', t)
        for recurso in ("repositories describe", "service-accounts describe"):
            self.assertIn(recurso, t)  # consulta antes de criar
        self.assertIn("run.googleapis.com cloudbuild.googleapis.com", t)
        self.assertIn("cloudscheduler.googleapis.com bigquery.googleapis.com", t)
        self.assertIn("bash scripts/deploy_coletor_job.sh", t)
        # datasets ausentes (ex.: nivon_core) criados na localização lida do nivon_raw
        self.assertIn('bq show --format=json "$P:nivon_raw"', t)
        self.assertIn('bq mk --dataset --location="$LOCAL_BQ"', t)
        self.assertIn('bq query --project_id="$P" --location="$LOCAL_BQ"', t)
        self.assertLess(t.index("bq mk --dataset"), t.index("roles/bigquery.dataEditor"))
        self.assertNotIn("bq add-iam-policy-binding", t)
        self.assertIn("GRANT \\`roles/bigquery.dataEditor\\` ON SCHEMA", t)
        for sql, tabela in (("database/bigquery/nivon_saude_fontes.sql", "nivon_core.saude_fontes"),
                            ("database/bigquery/nivon_ptax_schema.sql", "nivon_core.ptax_quotes"),
                            ("sql/bigquery/002_agro_fontes_staging.sql", "nivon_raw.agro_fonte_stage")):
            self.assertIn(f"criar_tabela {sql} {tabela}", t)
            self.assertTrue((RAIZ / sql).is_file(), sql)

    def test_fontes_fica_vazio_para_a_f2(self):
        self.assertEqual((RAIZ / "src/nivon/fontes/__init__.py").read_text(), "")


if __name__ == "__main__":
    unittest.main()
