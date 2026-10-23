"""Integração: export JSONL -> SQLite assinado -> CLI somente leitura -> JSON."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from nivon.fretes_entrada_jsonl import carregar_ofertas_frete_jsonl
from nivon.fretes_registros import ErroRegistroFrete
from nivon.fretes_ledger_persistente import (
    GENESIS, inicializar_ledger_frete, anexar_lote_previsoes_frete,
)
from test_fretes_ledger_persistente import recebido
from test_fretes_previsoes_arquivadas import (
    KEY, CUTOFF, PARAMS, SOURCE, MODEL, historico, emissao,
)

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/"scripts"/"auditar_fretes_ledger_local.py"


def oferta_exportada(row):
    o={
        k:getattr(row,k) for k in row.__dataclass_fields__
    }
    for key in ("frete_base_brl_t","pedagio_brl_t","frete_cheio_brl_t"):
        o[key]=str(o[key]) if o[key] is not None else None
    o["data_referencia"]=o["data_referencia"].isoformat()
    o["data_publicacao"]=o["data_publicacao"].isoformat()
    o["data_coleta"]=o["data_coleta"].isoformat()
    return o


class TestPipelineRealistaOffline(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.ofertas=self.dir/"ofertas.jsonl"
        self.db=self.dir/"previsoes.sqlite3"
        self.config=self.dir/"auditoria.json"
        self.rows=historico(110)
        self.ofertas.write_text("".join(
            json.dumps(oferta_exportada(o),sort_keys=True)+"\n"
            for o in self.rows
        ),encoding="utf-8")
        previsoes=sorted([
            emissao(self.rows,j,h)
            for j in range(1,6) for h in (7,30,90)
        ],key=lambda p:(p["registrado_em"],p["horizonte_dias_corridos"]))
        with sqlite3.connect(self.db) as db:
            inicializar_ledger_frete(db)
            commit=anexar_lote_previsoes_frete(
                db,previsoes,recebimentos=[recebido(p) for p in previsoes],
                cabeca_anterior_sha256=GENESIS,chave_verificacao=KEY,
                emissor_esperado="fixture-archive",
            )
        self.cabeca=commit["cabeca_sha256"]
        self.settings={
            "arquivo_sqlite":str(self.db),
            "arquivo_ofertas":str(self.ofertas),
            "cabeca_externa_sha256":self.cabeca,
            "as_of":CUTOFF.isoformat(),
            "emissor_esperado":"fixture-archive",
            "modelo_versao":MODEL,"fonte_id":SOURCE,
            "horizontes_dias":[7,30,90],
            "condicoes":dict(PARAMS),
        }
        self.config.write_text(json.dumps(self.settings),encoding="utf-8")

    def rodar(self, *, senha=True):
        env=dict(os.environ)
        env["PYTHONPATH"]=str(ROOT/"src")
        if senha:
            env["NIVON_FRETE_HMAC_KEY_HEX"]=KEY.hex()
        else:
            env.pop("NIVON_FRETE_HMAC_KEY_HEX",None)
        return subprocess.run(
            [sys.executable,str(CLI),"--config",str(self.config)],
            cwd=ROOT,env=env,capture_output=True,text=True,timeout=25,
            check=False,
        )

    def test_aceitacao_integral_ledger_jsonl_cli_tres_horizontes(self):
        r=self.rodar()
        self.assertEqual(r.returncode,0,r.stderr)
        doc=json.loads(r.stdout)
        self.assertEqual(doc["registros_ledger"],15)
        self.assertEqual(doc["dias_com_ofertas"],110)
        self.assertEqual(
            [x["dias"] for x in doc["cobertura_horizontes"]],
            [7,30,90],
        )
        for h in ("7","30","90"):
            self.assertEqual(doc["avaliacoes"][h]["n"],5)
            self.assertEqual(doc["avaliacoes"][h]["mae"],0)
            self.assertEqual(doc["avaliacoes"][h]["mae_baseline_zero"],int(h))
            self.assertFalse(doc["avaliacoes"][h]["publicavel"])
        self.assertFalse(doc["dados_originais_autenticados"])
        self.assertFalse(doc["direitos_de_uso_homologados"])
        self.assertFalse(doc["prova_temporal_externa_autenticada"])
        self.assertNotIn(KEY.hex(),r.stdout)

    def test_configuracao_sem_chave_nao_revela_documentos(self):
        r=self.rodar(senha=False)
        self.assertEqual(r.returncode,2)
        self.assertNotIn("previsao_id",r.stderr)
        self.assertEqual(json.loads(r.stderr)["status"],"BLOQUEADO")

    def test_ancora_alterada_bloqueia_saida(self):
        self.settings["cabeca_externa_sha256"]="f"*64
        self.config.write_text(json.dumps(self.settings),encoding="utf-8")
        r=self.rodar()
        self.assertEqual(r.returncode,2)
        self.assertFalse(json.loads(r.stderr)["publicavel"])

    def test_jsonl_com_numero_float_rejeita(self):
        obj=oferta_exportada(self.rows[0])
        obj["frete_base_brl_t"]=123.5
        self.ofertas.write_text(json.dumps(obj)+"\n",encoding="utf-8")
        with self.assertRaisesRegex(ErroRegistroFrete,"linha JSONL"):
            carregar_ofertas_frete_jsonl(self.ofertas)

    def test_jsonl_com_campos_inesperados_rejeita(self):
        obj=oferta_exportada(self.rows[0])
        obj["licenca_aprovada"]=True
        self.ofertas.write_text(json.dumps(obj)+"\n",encoding="utf-8")
        with self.assertRaises(ErroRegistroFrete):
            carregar_ofertas_frete_jsonl(self.ofertas)

    def test_cli_nao_modifica_sqlite_de_evidencias(self):
        antes=self.db.read_bytes()
        r=self.rodar()
        self.assertEqual(r.returncode,0)
        self.assertEqual(antes,self.db.read_bytes())

    def test_configuracao_inclui_campo_ativar_producao_rejeita(self):
        self.settings["ativar_producao"]=True
        self.config.write_text(json.dumps(self.settings),encoding="utf-8")
        self.assertEqual(self.rodar().returncode,2)

    def test_sem_banco_nao_gera_snapshot_automatico(self):
        self.db.unlink()
        r=self.rodar()
        self.assertEqual(r.returncode,2)
        self.assertFalse(self.db.exists())


if __name__=="__main__":
    unittest.main()
