"""Teste ponta a ponta do dossiê editorial -> outbox sem possibilidade de envio.

Todo conteúdo, direitos e identidade são sintéticos.
"""
import copy
import hashlib
import hmac
import json
import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.autorizacao_envio import conteudo_canonico
from nivon.entrega_whatsapp import preparar_template
from nivon.outbox_whatsapp import consultar_envio, revogar_destinatario
from nivon.pacote_editorial_offline import (
    avaliar_pacote_offline, registrar_pacote_offline,
)
from suporte_provas_outbox import provas_sinteticas, provisionar_teste
from test_outbox_whatsapp import SEGREDO, CHAVE_AUDITORIA
from test_editorial_preflight import dados


def pacote_teste():
    base = dados()
    edicao = base["edicao"]
    gerado_em = base["gerado_em"]
    destino = "5566999999999"
    template = "nivon_briefing_diario"
    resumo = "NIVON: soja, mercados e logística; informação sintética sob revisão."
    link = "https://nivon.example/briefing/2026-10-20"
    modelo = preparar_template(
        destino=destino, template=template, resumo=resumo, link=link,
        gerado_em=gerado_em, opt_in_registrado=True, template_aprovado=True)
    now = datetime.now(timezone.utc)
    sha_payload = hashlib.sha256(json.dumps(
        modelo["payload"], sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()
    doc = {
        "idempotency_key": modelo["idempotency_key"],
        "edicao": "2026-10-20",
        "payload_sha256": sha_payload,
        "sha256_editorial": edicao["sha256"],
        "destinatario_hmac": hmac.new(
            SEGREDO, destino.encode(), hashlib.sha256).hexdigest(),
        "revisao_editorial_id": "REVISAO_EDITORIAL_SINTETICA_001",
        "direitos_publicacao_id": "DIREITOS_PUBLICACAO_SINTETICA_001",
        "consentimento_id": "CONSENTIMENTO_SINTETICO_001",
        "template_aprovado_id": "TEMPLATE_SINTETICO_001",
        "orcamento_id": "ORCAMENTO_SINTETICO_001",
        "aprovador_id": "APROVADOR_SINTETICO_OFFLINE_001",
        "emitido_em": (now - timedelta(minutes=1)).isoformat(),
        "valido_ate": (now + timedelta(hours=1)).isoformat(),
        "revisao_independente": True,
        "direitos_publicacao": True,
        "consentimento_ativo": True,
        "template_aprovado": True,
        "orcamento_aprovado": True,
        "revogado": False,
    }
    signature = "sha256=" + hmac.new(
        CHAVE_AUDITORIA, conteudo_canonico(doc), hashlib.sha256).hexdigest()
    proofs, keys = provas_sinteticas(doc)
    pacote = {
        **base, "destinatario": destino, "nome_template": template,
        "resumo_template": resumo, "url_briefing": link,
        "documento": doc, "assinatura": signature,
        "comprovantes": proofs,
    }
    return pacote, keys


class TestDossieEditorialOfflineE2E(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "outbox.sqlite"
        self.con = sqlite3.connect(self.path)
        self.pacote, self.keys = pacote_teste()

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def registrar(self, pacote=None):
        return registrar_pacote_offline(
            self.con, pacote or self.pacote,
            chave_destinatario=SEGREDO, chave_auditoria=CHAVE_AUDITORIA,
            emissores=self.keys)

    def linhas(self):
        existe = self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nivon_envios'"
        ).fetchone()
        if not existe:
            return 0
        return self.con.execute(
            "SELECT COUNT(*) FROM nivon_envios").fetchone()[0]

    def test_fim_a_fim_registro_unico_sem_envio(self):
        provisionar_teste(self.con, self.keys)
        inicial = avaliar_pacote_offline(self.pacote)
        self.assertEqual(inicial["estado"], "PREVALIDADO_OFFLINE")
        result = self.registrar()
        self.assertEqual(result["estado"], "EDICAO_REGISTRADA_OFFLINE_SEM_ENVIO")
        self.assertEqual(result["estado_outbox"], "PREPARADO")
        self.assertFalse(result["envio_habilitado"])
        self.assertEqual(self.linhas(), 1)
        key = self.pacote["documento"]["idempotency_key"]
        self.assertEqual(consultar_envio(self.con,key)["tentativas"], 0)
        rerun = self.registrar()
        self.assertTrue(rerun["ja_existia"])
        self.assertEqual(self.linhas(),1)
        self.assertNotIn(self.pacote["destinatario"].encode(),self.path.read_bytes())

    def test_sem_registry_comprova_bloqueio_antes_de_escrever(self):
        with self.assertRaises(PermissionError):
            self.registrar()
        self.assertEqual(self.linhas(),0)

    def test_noticia_expirada_nao_registra_nada(self):
        provisionar_teste(self.con,self.keys)
        p = copy.deepcopy(self.pacote)
        p["noticias"][0]["publicado_em"] = "2026-10-17T12:00:00-03:00"
        r = self.registrar(p)
        self.assertEqual(r["estado"],"BLOQUEADO_PREFLIGHT")
        self.assertEqual(self.linhas(),0)

    def test_publicacao_sem_direitos_nao_registra_nada(self):
        provisionar_teste(self.con,self.keys)
        p = copy.deepcopy(self.pacote)
        p["fretes"][0]["direitos_publicacao"]=False
        r = self.registrar(p)
        self.assertEqual(r["estado"],"BLOQUEADO_PREFLIGHT")
        self.assertEqual(self.linhas(),0)

    def test_documento_vinculado_a_outro_destinatario_nao_registra(self):
        provisionar_teste(self.con,self.keys)
        p=copy.deepcopy(self.pacote)
        p["destinatario"]="5566888888888"
        with self.assertRaises(PermissionError):
            self.registrar(p)
        self.assertEqual(self.linhas(),0)

    def test_consentimento_externo_revogado_nao_registra(self):
        provisionar_teste(self.con,self.keys)
        p=copy.deepcopy(self.pacote)
        p["comprovantes"][2]["estado"]="REVOGADA"
        with self.assertRaises(PermissionError):
            self.registrar(p)
        self.assertEqual(self.linhas(),0)

    def test_optout_destinatario_impede_registro_dossie(self):
        provisionar_teste(self.con,self.keys)
        revogar_destinatario(
            self.con, destino=self.pacote["destinatario"],
            chave_destinatario=SEGREDO,
            evidencia_revogacao="OPT_OUT_E2E_DOCUMENTADO_20261023")
        with self.assertRaises(PermissionError):
            self.registrar()
        self.assertEqual(self.linhas(),0)

    def test_cli_avalia_sem_criar_arquivos(self):
        source=Path(self.temp.name)/"pacote.json"
        source.write_text(json.dumps(self.pacote,ensure_ascii=False),encoding="utf-8")
        result=subprocess.run(
            [sys.executable,"scripts/nivon_preparar_pacote.py",str(source)],
            capture_output=True,text=True,timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)
        payload=json.loads(result.stdout)
        self.assertEqual(payload["estado"],"PREVALIDADO_OFFLINE")
        self.assertFalse(payload["envio_habilitado"])
        self.assertNotIn(self.pacote["destinatario"],result.stdout)
        self.assertFalse(self.path.exists() and self.path.stat().st_size)

    def test_lote_registra_sucessos_e_bloqueios_sem_envio(self):
        from nivon.pacote_editorial_offline import registrar_lote_offline
        provisionar_teste(self.con, self.keys)
        invalido = copy.deepcopy(self.pacote)
        invalido["noticias"][0]["direitos_publicacao"] = False
        lote = [self.pacote, invalido, copy.deepcopy(self.pacote)]
        resultado = registrar_lote_offline(
            self.con, lote, chave_destinatario=SEGREDO,
            chave_auditoria=CHAVE_AUDITORIA, emissores=self.keys)
        self.assertEqual(resultado["registrados"], 1)
        self.assertEqual(resultado["bloqueados"], 2)
        self.assertEqual(resultado["resultados"][2]["estado"], "REPETIDO_NO_LOTE")
        self.assertEqual(self.linhas(), 1)
        self.assertEqual(consultar_envio(
            self.con, self.pacote["documento"]["idempotency_key"])["tentativas"], 0)

    def test_lote_nao_perde_valido_apos_corrompido_com_mesmo_id(self):
        from nivon.pacote_editorial_offline import registrar_lote_offline
        provisionar_teste(self.con, self.keys)
        primeiro = copy.deepcopy(self.pacote)
        primeiro["noticias"][0]["direitos_publicacao"] = False
        res = registrar_lote_offline(
            self.con, [primeiro, self.pacote],
            chave_destinatario=SEGREDO, chave_auditoria=CHAVE_AUDITORIA,
            emissores=self.keys)
        self.assertEqual(res["registrados"], 1)
        self.assertEqual(res["bloqueados"], 1)
        self.assertEqual(res["resultados"][1]["estado"], "EDICAO_REGISTRADA_OFFLINE_SEM_ENVIO")
        self.assertEqual(self.linhas(), 1)

    def test_status_temporal_independe_de_validacao_historica(self):
        from unittest.mock import patch
        with patch("nivon.pacote_editorial_offline._relogio_avaliacao_utc",
                   return_value=datetime.fromisoformat("2026-10-20T15:01:00-03:00")):
            ativo = avaliar_pacote_offline(self.pacote)
        self.assertEqual(ativo["estado"], "PREVALIDADO_OFFLINE")
        self.assertEqual(ativo["vigencia"]["estado_temporal"], "DENTRO_DO_PRAZO")
        with patch("nivon.pacote_editorial_offline._relogio_avaliacao_utc",
                   return_value=datetime.fromisoformat("2026-10-21T12:00:00-03:00")):
            velho = avaliar_pacote_offline(self.pacote)
        self.assertEqual(velho["estado"], "PREVALIDADO_OFFLINE")
        self.assertEqual(velho["vigencia"]["estado_temporal"], "EDICAO_VENCIDA")
        self.assertFalse(velho["envio_habilitado"])

    def test_cli_lote_mostra_prazo_sem_expor_destinatario(self):
        entrada=Path(self.temp.name)/"lote_prazos.json"
        entrada.write_text(json.dumps([self.pacote]), encoding="utf-8")
        result=subprocess.run(
            [sys.executable,"scripts/nivon_preparar_pacote.py",str(entrada),"--lote"],
            capture_output=True,text=True,timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)
        d=json.loads(result.stdout)
        self.assertEqual(d["resultados"][0]["vigencia"]["estado_temporal"],"EDICAO_VENCIDA")
        self.assertIsNotNone(d["resultados"][0]["vigencia"]["valido_ate_utc"])
        self.assertNotIn(self.pacote["destinatario"],result.stdout)

    def test_lote_preflight_separa_invalidos_sem_banco(self):
        from nivon.pacote_editorial_offline import avaliar_lote_offline
        invalido = copy.deepcopy(self.pacote)
        invalido["noticias"][0]["publicado_em"] = "2026-10-01T08:00:00-03:00"
        out = avaliar_lote_offline([self.pacote, invalido, {"contrato": "errado"}])
        self.assertEqual(out["prevalidados"], 1)
        self.assertEqual(out["bloqueados"], 2)
        self.assertFalse(out["envio_habilitado"])
        self.assertEqual(self.linhas(), 0)

    def test_cli_em_lote_retorna_estado_sanitizado(self):
        entrada=Path(self.temp.name)/"lote.json"
        invalido=copy.deepcopy(self.pacote)
        invalido["fretes"][0]["direitos_publicacao"]=False
        entrada.write_text(json.dumps([self.pacote,invalido]),encoding="utf-8")
        r=subprocess.run(
            [sys.executable,"scripts/nivon_preparar_pacote.py",str(entrada),"--lote"],
            capture_output=True,text=True,timeout=12)
        self.assertEqual(r.returncode,1,r.stderr)
        d=json.loads(r.stdout)
        self.assertEqual(d["prevalidados"],1)
        self.assertEqual(d["bloqueados"],1)
        self.assertNotIn(self.pacote["destinatario"],r.stdout)
        self.assertNotIn("Plantio de soja avança",r.stdout)

    def test_lote_rejeita_quantidade_excessiva_antes_de_escrever(self):
        from nivon.pacote_editorial_offline import registrar_lote_offline
        with self.assertRaises(ValueError):
            registrar_lote_offline(
                self.con,[{}]*201,chave_destinatario=SEGREDO,
                chave_auditoria=CHAVE_AUDITORIA,emissores=self.keys)
        self.assertEqual(self.linhas(),0)

    def test_cli_reporta_bloqueio_sem_imprimir_dados(self):
        p=copy.deepcopy(self.pacote)
        p["noticias"][0]["publicado_em"]="2026-10-01T00:00:00-03:00"
        source=Path(self.temp.name)/"vencido.json"
        source.write_text(json.dumps(p),encoding="utf-8")
        r=subprocess.run(
            [sys.executable,"scripts/nivon_preparar_pacote.py",str(source)],
            capture_output=True,text=True,timeout=12)
        self.assertEqual(r.returncode,1,r.stderr)
        self.assertEqual(json.loads(r.stdout)["estado"],"BLOQUEADO_PREFLIGHT")
        self.assertNotIn(self.pacote["destinatario"],r.stdout)


if __name__=="__main__":
    unittest.main()
