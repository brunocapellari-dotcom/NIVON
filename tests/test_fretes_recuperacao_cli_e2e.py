"""Processo real: CLI ingestão -> commit sem recibo -> CLI recuperação.

Proveniência, relógio, chaves e dados são artificiais. Nenhum acesso Cloud.
"""
import json
import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.fretes_ciclo_shadow import executar_ciclo_shadow_frete_local
from nivon.fretes_ledger_persistente import (
    GENESIS, verificar_ledger_frete,
)
from test_fretes_ciclo_cli_e2e import TestCicloCLISubprocess
from test_fretes_previsoes_arquivadas import KEY
from test_fretes_ciclo_shadow_recibo_e2e import (
    RECIBO_KEY, RECIBO_EMISSOR,
)

ROOT=Path(__file__).resolve().parents[1]
RECOVERY=ROOT/"scripts"/"recuperar_recibo_fretes_local.py"


class TestRecuperacaoCLIFretes(unittest.TestCase):
    def setUp(self):
        self.fixt=TestCicloCLISubprocess("test_pipeline_cli_real_insere_emite_verifica_recibo")
        self.fixt.setUp()
        self.addCleanup(self.fixt.doCleanups)
        self.head=self.fixt.importar()
        # Simula crash pós-commit ao passar diretório ausente somente no
        # serviço interno: a CLI de emissão normal não permite diretório
        # ausente ANTES do commit.
        with sqlite3.connect(self.fixt.db) as con:
            self.committed=executar_ciclo_shadow_frete_local(
                con,recebido_em=datetime.now(timezone.utc),
                cabeca_ofertas_esperada=self.head,
                cabeca_previsoes_esperada=GENESIS,
                condicoes=self.fixt.settings["condicoes"],
                fonte_id=self.fixt.settings["fonte_id"],
                emissor_previsao=self.fixt.settings["emissor_previsao"],
                chave_previsao=KEY,
                emissor_recibo=RECIBO_EMISSOR,
                chave_recibo=RECIBO_KEY,
                diretorio_recibos=self.fixt.root/"ausente",
            )
        assert self.committed["status"]=="PREVISOES_GRAVADAS_SEM_RECIBO_LOCAL"
        self.config=self.fixt.root/"recuperacao.json"
        self.cfg={
            "arquivo_sqlite":str(self.fixt.db),
            "cabeca_previsoes_anterior_sha256":GENESIS,
            "quantidade_previsoes_anterior":0,
            "cabeca_ofertas_sha256":self.head,
            "condicoes":self.fixt.settings["condicoes"],
            "fonte_id":self.fixt.settings["fonte_id"],
            "emissor_previsao":self.fixt.settings["emissor_previsao"],
            "emissor_recibo":RECIBO_EMISSOR,
            "diretorio_recibos":str(self.fixt.receipts),
            "horizontes_dias":[7,30,90],
        }
        self.gravar_config()

    def gravar_config(self):
        self.config.write_text(json.dumps(self.cfg),encoding="utf-8")
        self.config.chmod(0o600)

    def recuperar(self, *, missing_key=False):
        env=dict(self.fixt.env)
        if missing_key:
            env.pop("NIVON_FRETE_RECIBO_KEY_HEX",None)
        return subprocess.run(
            [sys.executable,str(RECOVERY),"--config",str(self.config)],
            cwd=ROOT,env=env,capture_output=True,text=True,
            timeout=25,check=False,
        )

    def test_cli_repara_recibo_do_ledger_sem_tocar_sqlite(self):
        antes=self.fixt.db.read_bytes()
        r=self.recuperar()
        self.assertEqual(r.returncode,0,r.stderr)
        out=json.loads(r.stdout)
        self.assertEqual(out["total_previsoes"],3)
        self.assertEqual(out["cabeca_sha256"],self.committed["previsoes_cabeca_sha256"])
        self.assertFalse(out["testemunha_independente"])
        self.assertFalse(out["publicavel"])
        self.assertTrue(Path(out["recibo_local_caminho"]).is_file())
        self.assertEqual(self.fixt.db.read_bytes(),antes)
        self.assertNotIn(KEY.hex(),r.stdout)
        with sqlite3.connect(self.fixt.db) as con:
            l=verificar_ledger_frete(
                con,cabeca_esperada_sha256=out["cabeca_sha256"],
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
            )
            self.assertEqual(l["quantidade"],3)

    def test_retry_apenas_valida_recibo_existente(self):
        a=self.recuperar()
        self.assertEqual(a.returncode,0,a.stderr)
        b=self.recuperar()
        self.assertEqual(b.returncode,0,b.stderr)
        self.assertEqual(json.loads(b.stdout)["status"],
                         "RECIBO_JA_EXISTENTE_VALIDADO_LOCALMENTE")
        self.assertEqual(len(list(self.fixt.receipts.glob("*.json"))),1)

    def test_checkpoint_externo_incorreto_bloqueia(self):
        self.cfg["cabeca_previsoes_anterior_sha256"]="f"*64
        self.gravar_config()
        r=self.recuperar()
        self.assertEqual(r.returncode,2)
        self.assertEqual(json.loads(r.stderr)["status"],"RECUPERACAO_BLOQUEADA")
        self.assertFalse(list(self.fixt.receipts.glob("*.json")))

    def test_sem_chave_nao_recupera_nem_imprime_segredos(self):
        r=self.recuperar(missing_key=True)
        self.assertEqual(r.returncode,2)
        self.assertNotIn(KEY.hex(),r.stderr)
        self.assertFalse(list(self.fixt.receipts.glob("*.json")))

    def test_arquivo_de_configuracao_publico_rejeitado(self):
        self.config.chmod(0o644)
        r=self.recuperar()
        self.assertEqual(r.returncode,2)
        self.assertFalse(list(self.fixt.receipts.glob("*.json")))

    def test_reconfigurar_horizonte_nao_gera_falsas_previsoes(self):
        self.cfg["horizontes_dias"]=[7,30]
        self.gravar_config()
        r=self.recuperar()
        self.assertEqual(r.returncode,2)
        with sqlite3.connect(self.fixt.db) as con:
            l=verificar_ledger_frete(
                con,cabeca_esperada_sha256=self.committed["previsoes_cabeca_sha256"],
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
            )
            self.assertEqual(l["quantidade"],3)


if __name__=="__main__":
    unittest.main()
