"""Aceitação subprocess: lote realista serializado + CLI + store SQLite.

Fixtures assinadas localmente com chaves de TESTE; não há ligação com
provedor WhatsApp, consentimento ou âncora independente.
"""
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

from nivon.fretes_atestacoes import hash_evento
from nivon.fretes_ofertas_store import (
    GENESIS,inicializar_store_ofertas_frete,verificar_store_ofertas_frete,
)
from test_fretes_whatsapp_r01_e2e import (
    PSEUDO,KEYS,EMISSORES,evento_sintetico,assinar,
)

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/"scripts"/"ingerir_fretes_atestados_local.py"


def _reassinar(fields,domain,col):
    return assinar({
        k:v for k,v in fields.items()
        if k not in {"versao_atestacao","emissor_id","emitido_em",
                     "valido_ate","assinatura_hmac_sha256"}
    },domain,col)


def gerar(i,now):
    pub=now-timedelta(seconds=35)
    col=pub+timedelta(seconds=5)
    dia=pub.astimezone(ZoneInfo("America/Cuiaba")).date()
    ev,res,rights,_=evento_sintetico(dia,i,150+i*10)
    ev["timestamp"]=pub.isoformat()
    raw=f"Anuncio privado sintético {dia} ponto {i}".encode()
    res["evento_sha256"]=hash_evento(ev)
    res["raw_sha256"]=sha256(raw).hexdigest()
    rights=_reassinar(rights,"DIREITOS",col)
    res=_reassinar(res,"RESOLUCAO",col)
    return {
        "evento":ev,"resolucao":res,"autorizacao":rights,
        "data_coleta":col.isoformat(),
        "raw_base64":base64.b64encode(raw).decode(),
    }


class TestCLILoteAtestado(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p=Path(self.temp.name)
        self.db=self.p/"fretes.sqlite"
        self.jsonl=self.p/"recebidos.jsonl"
        self.config=self.p/"config.json"
        with sqlite3.connect(self.db) as con:
            inicializar_store_ofertas_frete(con)
        self.db.chmod(0o600)
        self.now=datetime.now(timezone.utc)
        self.envs=[gerar(i,self.now) for i in (1,2)]
        self.preparar()

    def preparar(self,head=GENESIS):
        self.jsonl.write_text("".join(
            json.dumps(x,sort_keys=True,ensure_ascii=True)+"\n"
            for x in self.envs
        ),encoding="utf-8")
        self.jsonl.chmod(0o600)
        self.config.write_text(json.dumps({
            "arquivo_ofertas_sqlite":str(self.db),
            "arquivo_envelopes_jsonl":str(self.jsonl),
            "cabeca_anterior_sha256":head,
            "emissores_atestacao":EMISSORES,
        }),encoding="utf-8")
        self.config.chmod(0o600)

    def cli(self,missing_key=False):
        environ=dict(os.environ)
        environ.update({
            "PYTHONPATH":str(ROOT/"src"),
            "NIVON_FRETE_DIREITOS_KEY_HEX":KEYS["DIREITOS"].hex(),
            "NIVON_FRETE_RESOLUCAO_KEY_HEX":KEYS["RESOLUCAO"].hex(),
            "NIVON_FRETE_PSEUDO_KEY_HEX":PSEUDO.hex(),
        })
        if missing_key:
            environ.pop("NIVON_FRETE_RESOLUCAO_KEY_HEX",None)
        return subprocess.run(
            [sys.executable,str(CLI),"--config",str(self.config)],
            cwd=ROOT,env=environ,text=True,capture_output=True,
            timeout=25,check=False,
        )

    def test_aceitacao_arquivo_assinado_para_store_e_recibo(self):
        run=self.cli()
        self.assertEqual(run.returncode,0,run.stderr)
        r=json.loads(run.stdout)
        self.assertEqual(r["publicacoes_recebidas"],2)
        self.assertEqual(r["registros_individuais_inseridos"],2)
        self.assertFalse(r["raw_armazenado_neste_store"])
        self.assertFalse(r["coleta_whatsapp_live_conectada"])
        self.assertFalse(r["publicavel"])
        with sqlite3.connect(self.db) as con:
            l=verificar_store_ofertas_frete(
                con,cabeca_esperada_sha256=r["nova_cabeca_sha256"])
        self.assertEqual(l["registros"],2)
        self.assertNotIn("Anuncio privado",str(l))
        self.assertNotIn(PSEUDO.hex(),run.stdout)

    def _shadow(self,head):
        shadow_config=self.p/"shadow.json"
        shadow_config.write_text(json.dumps({
            "arquivo_ofertas_sqlite":str(self.db),
            "cabeca_ofertas_sha256":head,
            "condicoes":{
                "origem_ibge":"5107925",
                "destino_ibge":"5107602",
                "descarga_entity_id":"terminal:001",
                "produto":"SOJA","equipamento":"RODOTREM",
                "regime":"PJ","pedagio":"ADICIONAL",
            },
            "fonte_id":"WHATSAPP_FIXTURE",
            "emissor_id":"fixture-archive",
            "horizontes_dias":[7,30,90],
        }),encoding="utf-8")
        shadow_config.chmod(0o600)
        env=dict(os.environ)
        env["PYTHONPATH"]=str(ROOT/"src")
        return subprocess.run([
            sys.executable,str(ROOT/"scripts"/"preparar_shadow_fretes_local.py"),
            "--config",str(shadow_config),
        ],cwd=ROOT,env=env,capture_output=True,text=True,timeout=25,
            check=False)

    def test_entrada_whatsapp_sqlite_prepara_tres_intencoes_shadow(self):
        r=self.cli()
        self.assertEqual(r.returncode,0,r.stderr)
        head=json.loads(r.stdout)["nova_cabeca_sha256"]
        antes=self.db.read_bytes()
        output=self._shadow(head)
        self.assertEqual(output.returncode,0,output.stderr)
        result=json.loads(output.stdout)
        self.assertEqual(result["executor"],"CLI_READONLY_SHADOW")
        self.assertEqual(result["pares_origem"],2)
        self.assertEqual(result["horizontes_dias_corridos"],[7,30,90])
        self.assertEqual(result["ofertas_elegiveis_nesta_rota"],2)
        self.assertEqual(len(result["previsoes_para_assinatura_externa"]),3)
        for proposta in result["previsoes_para_assinatura_externa"]:
            self.assertEqual(proposta["delta_previsto_brl_t"],"0")
            self.assertNotIn("registrado_em",proposta)
            self.assertNotIn("assinatura_hmac_sha256",proposta)
        self.assertFalse(result["persistencia_realizada"])
        self.assertFalse(result["publicavel"])
        self.assertEqual(antes,self.db.read_bytes())

    def test_shadow_recusa_ancora_incorreta(self):
        r=self.cli()
        self.assertEqual(r.returncode,0,r.stderr)
        output=self._shadow(GENESIS)
        self.assertEqual(output.returncode,2)
        self.assertEqual(
            json.loads(output.stderr)["status"],"EMISSAO_SHADOW_BLOQUEADA"
        )

    def test_repeticao_arquivo_nao_regrava_ofertas(self):
        primeiro=json.loads(self.cli().stdout)
        self.preparar(head=primeiro["nova_cabeca_sha256"])
        second=self.cli()
        self.assertEqual(second.returncode,0,second.stderr)
        r=json.loads(second.stdout)
        self.assertEqual(r["registros_individuais_inseridos"],0)
        self.assertEqual(r["republicacoes_idempotentes"],2)
        self.assertEqual(r["nova_cabeca_sha256"],primeiro["nova_cabeca_sha256"])

    def test_lote_assinatura_falsa_nao_insere_primeiro_registro(self):
        self.envs[1]["resolucao"]["raw_sha256"]="f"*64
        self.preparar()
        r=self.cli()
        self.assertEqual(r.returncode,2)
        self.assertEqual(json.loads(r.stderr)["status"],"INGESTAO_BLOQUEADA")
        with sqlite3.connect(self.db) as con:
            self.assertEqual(verificar_store_ofertas_frete(
                con,cabeca_esperada_sha256=GENESIS)["registros"],0)
        self.assertNotIn("Anuncio privado",r.stderr)

    def test_raw_em_arquivo_publicamente_legivel_e_bloqueado(self):
        self.jsonl.chmod(0o644)
        self.assertEqual(self.cli().returncode,2)

    def test_chave_ausente_falha_fechada(self):
        r=self.cli(missing_key=True)
        self.assertEqual(r.returncode,2)
        self.assertNotIn("KEY",r.stderr)

    def test_jsonl_com_raw_malformado_e_bloqueado(self):
        self.envs[0]["raw_base64"]="invalido!@@"
        self.preparar()
        self.assertEqual(self.cli().returncode,2)

    def test_cabeca_nao_autenticada_impede_segunda_ingestao(self):
        a=json.loads(self.cli().stdout)
        r=self.cli()
        self.assertEqual(r.returncode,2)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(verificar_store_ofertas_frete(
                con,cabeca_esperada_sha256=a["nova_cabeca_sha256"])["registros"],2)


if __name__=="__main__":
    unittest.main()
