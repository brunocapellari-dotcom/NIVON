"""Aceitação subprocess: WA atestado -> SQLite -> shadow assinado -> recibo.

Recebimento em processo local, chaves sintéticas. A execução integra dois
CLIs reais, arquivo SQLite em disco e recibo em arquivo exclusivo.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

from nivon.fretes_ledger_persistente import (
    GENESIS as PREV_GENESIS, inicializar_ledger_frete,
    verificar_ledger_frete,
)
from nivon.fretes_ofertas_store import (
    GENESIS as OFERTA_GENESIS, inicializar_store_ofertas_frete,
)
from nivon.fretes_recibos_ancora import auditar_ledger_frete_com_recibo

from test_fretes_ingestao_cli_e2e import gerar
from test_fretes_whatsapp_r01_e2e import PSEUDO, KEYS, EMISSORES
from test_fretes_previsoes_arquivadas import KEY
from test_fretes_ciclo_shadow_recibo_e2e import RECIBO_KEY, RECIBO_EMISSOR

ROOT=Path(__file__).resolve().parents[1]
INGESTAO=ROOT/"scripts"/"ingerir_fretes_atestados_local.py"
CICLO=ROOT/"scripts"/"executar_ciclo_shadow_fretes_local.py"


class TestCicloCLISubprocess(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/"fretes.sqlite"
        with sqlite3.connect(self.db) as con:
            inicializar_store_ofertas_frete(con)
            inicializar_ledger_frete(con)
        self.db.chmod(0o600)
        self.receipts=self.root/"recibos"
        self.receipts.mkdir(mode=0o700)
        self.receipts.chmod(0o700)
        self.envelopes=self.root/"envelopes.jsonl"
        now=datetime.now(timezone.utc)
        self.envelopes.write_text("".join(
            json.dumps(gerar(i,now),ensure_ascii=True,sort_keys=True)+"\n"
            for i in (1,2)
        ),encoding="utf-8")
        self.envelopes.chmod(0o600)
        self.config_ing=self.root/"ingestao.json"
        self.config_ing.write_text(json.dumps({
            "arquivo_ofertas_sqlite":str(self.db),
            "arquivo_envelopes_jsonl":str(self.envelopes),
            "cabeca_anterior_sha256":OFERTA_GENESIS,
            "emissores_atestacao":EMISSORES,
        }),encoding="utf-8")
        self.config_ing.chmod(0o600)
        self.config_ciclo=self.root/"ciclo.json"
        self.settings={
            "arquivo_sqlite":str(self.db),
            "diretorio_recibos":str(self.receipts),
            "cabeca_ofertas_esperada":None,
            "cabeca_previsoes_esperada":PREV_GENESIS,
            "condicoes":{
                "origem_ibge":"5107925",
                "destino_ibge":"5107602",
                "descarga_entity_id":"terminal:001",
                "produto":"SOJA","equipamento":"RODOTREM",
                "regime":"PJ","pedagio":"ADICIONAL",
            },
            "fonte_id":"WHATSAPP_FIXTURE",
            "emissor_previsao":"fixture-archive",
            "emissor_recibo":RECIBO_EMISSOR,
            "horizontes_dias":[7,30,90],
        }
        self.env=dict(os.environ)
        self.env.update({
            "PYTHONPATH":str(ROOT/"src"),
            "NIVON_FRETE_DIREITOS_KEY_HEX":KEYS["DIREITOS"].hex(),
            "NIVON_FRETE_RESOLUCAO_KEY_HEX":KEYS["RESOLUCAO"].hex(),
            "NIVON_FRETE_PSEUDO_KEY_HEX":PSEUDO.hex(),
            "NIVON_FRETE_PREVISAO_KEY_HEX":KEY.hex(),
            "NIVON_FRETE_RECIBO_KEY_HEX":RECIBO_KEY.hex(),
        })

    def run_cli(self,path,config):
        return subprocess.run(
            [sys.executable,str(path),"--config",str(config)],
            cwd=ROOT,env=self.env,capture_output=True,text=True,
            timeout=25,check=False,
        )

    def importar(self):
        run=self.run_cli(INGESTAO,self.config_ing)
        self.assertEqual(run.returncode,0,run.stderr)
        head=json.loads(run.stdout)["nova_cabeca_sha256"]
        self.settings["cabeca_ofertas_esperada"]=head
        self.config_ciclo.write_text(json.dumps(self.settings),encoding="utf-8")
        self.config_ciclo.chmod(0o600)
        return head

    def test_pipeline_cli_real_insere_emite_verifica_recibo(self):
        head=self.importar()
        r=self.run_cli(CICLO,self.config_ciclo)
        self.assertEqual(r.returncode,0,r.stderr)
        report=json.loads(r.stdout)
        self.assertEqual(report["previsoes_gravadas"],3)
        self.assertEqual(report["ofertas_cabeca_sha256"],head)
        self.assertFalse(report["previsoes_assinadas_por_servico_independente"])
        self.assertTrue(report["recibo_local_emitido"])
        self.assertFalse(report["publicavel"])
        recibo=json.loads(Path(report["recibo_local_caminho"]).read_text())
        with sqlite3.connect(self.db) as con:
            audit=auditar_ledger_frete_com_recibo(
                con,recibo,chave_recibo=RECIBO_KEY,
                as_of=datetime.now(timezone.utc),
                emissor_recibo=RECIBO_EMISSOR,
                chave_previsao=KEY,emissor_previsao="fixture-archive",
            )
        self.assertEqual(audit["sequencia"],3)
        self.assertFalse(audit["testemunha_temporal_independente"])
        self.assertNotIn(KEY.hex(),r.stdout)
        self.assertNotIn(PSEUDO.hex(),r.stdout)

    def test_segunda_execucao_mesma_rota_nao_gera_forecast_novo(self):
        self.importar()
        a=self.run_cli(CICLO,self.config_ciclo)
        self.assertEqual(a.returncode,0,a.stderr)
        first=json.loads(a.stdout)
        self.settings["cabeca_previsoes_esperada"]=first["previsoes_cabeca_sha256"]
        self.config_ciclo.write_text(json.dumps(self.settings),encoding="utf-8")
        self.config_ciclo.chmod(0o600)
        r=self.run_cli(CICLO,self.config_ciclo)
        self.assertEqual(r.returncode,2)
        self.assertEqual(json.loads(r.stderr)["status"],"CICLO_SHADOW_BLOQUEADO")
        with sqlite3.connect(self.db) as con:
            result=verificar_ledger_frete(
                con,cabeca_esperada_sha256=first["previsoes_cabeca_sha256"],
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
            )
        self.assertEqual(result["quantidade"],3)

    def test_falha_pos_commit_retorna_cabeca_e_codigo_especifico(self):
        self.importar()
        self.settings["diretorio_recibos"]=str(self.root/"invalid")
        self.config_ciclo.write_text(json.dumps(self.settings),encoding="utf-8")
        self.config_ciclo.chmod(0o600)
        r=self.run_cli(CICLO,self.config_ciclo)
        self.assertEqual(r.returncode,2)
        self.assertEqual(json.loads(r.stderr)["status"],"CICLO_SHADOW_BLOQUEADO")

    def test_chave_de_recibo_ausente_bloqueia_antes_do_append(self):
        self.importar()
        self.env.pop("NIVON_FRETE_RECIBO_KEY_HEX",None)
        run=self.run_cli(CICLO,self.config_ciclo)
        self.assertEqual(run.returncode,2)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(verificar_ledger_frete(
                con,cabeca_esperada_sha256=PREV_GENESIS,
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
            )["quantidade"],0)

    def test_cabeca_ofertas_errada_bloqueia_sem_previsoes(self):
        self.importar()
        self.settings["cabeca_ofertas_esperada"]=OFERTA_GENESIS
        self.config_ciclo.write_text(json.dumps(self.settings),encoding="utf-8")
        self.config_ciclo.chmod(0o600)
        r=self.run_cli(CICLO,self.config_ciclo)
        self.assertEqual(r.returncode,2)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(verificar_ledger_frete(
                con,cabeca_esperada_sha256=PREV_GENESIS,
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
            )["quantidade"],0)


if __name__=="__main__":
    unittest.main()
