"""Infraestrutura offline: worker não autoriza coleta, envio ou cloud."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from nivon.infra_preflight import carregar_inventario, InfraError
from nivon.infra_worker import executar_worker, ErroWorker


ROOT=Path(__file__).resolve().parents[1]
DOCKERFILE=ROOT/"infra/docker/Dockerfile.worker"
COMPOSE=ROOT/"infra/compose.offline-worker.yaml"


class TestWorker(unittest.TestCase):
    TIME="2026-10-20T16:30:00-03:00"

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        os.chmod(self.tmp.name,0o700)
        self.env={"NIVON_RUNTIME_ENABLED":"false",
                  "NIVON_OFFLINE_STATE_DIR":self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_self_check_sem_mudar_persistencia(self):
        result=executar_worker(modo="self-check",ambiente=self.env)
        self.assertEqual(result["status"],"OFFLINE_WORKER_CHECK_OK_NOT_OPERATIONAL")
        self.assertFalse(result["live"])
        self.assertFalse(result["storage_mutated"])
        self.assertFalse((Path(self.tmp.name)/"jobs.sqlite").exists())

    def test_ensaio_persistente_reentrante_sem_publicar(self):
        a=executar_worker(modo="synthetic-once",ambiente=self.env,agora=self.TIME)
        b=executar_worker(modo="synthetic-once",ambiente=self.env,agora=self.TIME)
        self.assertEqual(a["status"],"SUCCEEDED")
        self.assertTrue(a["state_written"])
        self.assertFalse(b["state_written"])
        self.assertEqual(b["job_count"],1)
        for r in (a,b):
            self.assertEqual(r["collector_count"],0)
            self.assertFalse(r["live"])
            self.assertFalse(r["publishes"])
            self.assertFalse(r["sends_whatsapp"])

    def test_recusa_toda_flag_operacional(self):
        for k in ("NIVON_RUNTIME_ENABLED","NIVON_BACKUP_ENABLED",
                  "NIVON_COLLECTORS_ENABLED","NIVON_PUBLICATION_ENABLED"):
            with self.subTest(k=k):
                env=dict(self.env)
                env[k]="true"
                with self.assertRaises(ErroWorker):
                    executar_worker(modo="self-check",ambiente=env)

    def test_recusa_modo_inexistente(self):
        with self.assertRaises(ErroWorker):
            executar_worker(modo="run-live",ambiente=self.env)

    def test_sem_fuso_nao_escreve_estado(self):
        with self.assertRaises(ValueError):
            executar_worker(modo="synthetic-once",ambiente=self.env,
                            agora="2026-10-20T16:30:00")
        self.assertFalse((Path(self.tmp.name)/"jobs.sqlite").exists())

    def test_sem_diretorio_privado_nao_escreve(self):
        env=dict(self.env,NIVON_OFFLINE_STATE_DIR="/missing/directory/nivon")
        with self.assertRaises(ErroWorker):
            executar_worker(modo="synthetic-once",ambiente=env,agora=self.TIME)

    def test_pasta_insegura_rejeitada_pelo_ledger(self):
        os.chmod(self.tmp.name,0o755)
        with self.assertRaises(ValueError):
            executar_worker(modo="synthetic-once",ambiente=self.env,
                            agora=self.TIME)

    def test_preflight_alterado_bloqueia(self):
        doc=copy.deepcopy(carregar_inventario())
        doc["release_gates"]["DURABILITY"]=True
        with self.assertRaises(InfraError):
            executar_worker(modo="self-check",ambiente=self.env,inventario=doc)

    def test_cli_sem_estado_ou_rede(self):
        env=dict(os.environ,PYTHONPATH=str(ROOT/"src"))
        p=subprocess.run([sys.executable,"-m","nivon.infra_worker"],
                        cwd=ROOT,env=env,capture_output=True,text=True,
                        check=False,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        obj=json.loads(p.stdout)
        self.assertFalse(obj["live"])
        self.assertEqual(obj["status"],"OFFLINE_WORKER_CHECK_OK_NOT_OPERATIONAL")


class TestWorkerCompose(unittest.TestCase):
    def test_container_sem_permissoes_ou_rede(self):
        docker=DOCKERFILE.read_text(encoding="utf-8")
        yml=COMPOSE.read_text(encoding="utf-8")
        self.assertIn("USER 65532:65532",docker)
        self.assertIn("nivon.infra_worker",docker)
        self.assertNotIn("EXPOSE ",docker)
        self.assertNotIn("RUN pip",docker)
        for k in ('profiles: ["offline-worker"]','network_mode: "none"',
                  'read_only: true','no-new-privileges:true','cap_drop:',
                  'restart: "no"','NIVON_RUNTIME_ENABLED: "false"',
                  'NIVON_OFFLINE_STATE_DIR_HOST:?', 'read_only: false'):
            self.assertIn(k,yml)
        for bad in ('privileged: true','network_mode: host',
                    'ports:', 'docker.sock','secrets:', 'restart: always',
                    "deploy:", "docker buildx build --push"):
            self.assertNotIn(bad,yml)

    def test_base_e_contexto_sem_material_restrito(self):
        docker=DOCKERFILE.read_text(encoding="utf-8")
        ignore=(ROOT/".dockerignore").read_text(encoding="utf-8")
        self.assertRegex(docker,r"FROM python:3\.11-slim-bookworm@sha256:[0-9a-f]{64}")
        self.assertNotIn("COPY . ",docker)
        self.assertIn("!infra/docker/Dockerfile.worker",ignore)
        for excluded in ("**/.env*", "**/*.sqlite*", "**/*.key"):
            self.assertIn(excluded,ignore)

    def test_compose_schema_quando_disponivel(self):
        docker=shutil.which("docker")
        if not docker:
            self.skipTest("Docker ausente")
        p=subprocess.run([docker,"compose","version"],capture_output=True,
                         text=True,check=False,timeout=12)
        if p.returncode:
            self.skipTest("Docker Compose indisponível")
        with tempfile.TemporaryDirectory() as folder:
            e=dict(os.environ,NIVON_OFFLINE_STATE_DIR_HOST=folder)
            run=subprocess.run(
                [docker,"compose","-f",str(COMPOSE),"--profile","offline-worker",
                 "config","--quiet"],cwd=ROOT,env=e,
                capture_output=True,text=True,check=False,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=="__main__":
    unittest.main()
