"""E2E XLSX upstream fixture -> parser -> legado -> pré-voo read-only."""
import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from nivon.conab_replay_xlsx import PARSER_ID,reexecutar_xlsx_conab
from nivon.preflight_migracao_conab import (
    planejar_preflight_conab,ErroPreflightConab,
)
from nivon.progresso_store import abrir_progresso,gravar_progresso
from nivon.registro_snapshots import abrir_registro
from nivon.progresso_conab_historico import preparar_esquema

FIXTURE=Path(__file__).parent/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"
URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
AT="2026-02-24T09:59:00+00:00"


class TestXlsxNoPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.legacy=abrir_progresso()
        self.canon=abrir_registro()
        preparar_esquema(self.canon)
        self.addCleanup(self.legacy.close)
        self.addCleanup(self.canon.close)
        self.raw=base64.b64decode(FIXTURE.read_text().strip())
        self.raw_sha=hashlib.sha256(self.raw).hexdigest()
        self.extracted=reexecutar_xlsx_conab(
            self.raw,sha256_origem=self.raw_sha,
            url_origem=URL,coletado_em=AT,publicado_em=None)
        rows=[{**json.loads(x),"coleta":AT} for x in self.extracted["mapa_semantico"].values()]
        gravar_progresso(self.legacy,rows,
                        evidence_id="FIXTURE_AGROBR_TERCEIRO_SEM_HOMOLOGACAO",
                        direitos_confirmados=True)
        ed=self.legacy.execute("SELECT id,sha256_json FROM progresso_edicoes").fetchone()
        raw_path=self.root/"conab.xlsx"
        raw_path.write_bytes(self.raw)
        replay_path=self.root/"replay.json"
        replay_path.write_text(json.dumps(rows,ensure_ascii=False),encoding="utf-8")
        self.doc={"schema":"NIVON_CONAB_PREFLIGHT_V1","edicoes":[{
            "legacy_id":ed["id"],"sha256_json":ed["sha256_json"],
            "url_origem":URL,"raw_path":str(raw_path),
            "raw_sha256":self.raw_sha,"raw_bytes":len(self.raw),
            "raw_mime":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "replay_json_path":str(replay_path),
            "parser_versao":PARSER_ID,
            "direitos_evidencia_id":"FIXTURE_SEM_DIREITOS_VERIFICADOS",
        }]}

    def test_xlsx_passou_bytes_parser_replay_e_legado(self):
        r=planejar_preflight_conab(self.legacy,self.canon,self.doc)
        self.assertEqual(r["edicoes_legadas"],1)
        self.assertEqual(r["replays_xlsx_publicos_executados"],1)
        self.assertEqual(r["por_estado"],{
            "RAW_XLSX_REFERENCIA_PUBLICA_REPROCESSADO_SEM_HOMOLOGACAO":1})
        self.assertEqual(r["itens"][0]["observacoes_replay"],11)
        self.assertTrue(r["itens"][0]["xlsx_reexecutado_localmente_sem_homologacao"])
        self.assertFalse(r["parser_conab_oficial_homologado"])
        self.assertFalse(r["migracao_permitida"])
        self.assertFalse(r["itens"][0]["origem_oficial_comprovada_externamente"])

    def test_xlsx_com_sha_de_outro_arquivo_bloqueia(self):
        self.doc["edicoes"][0]["raw_sha256"]="0"*64
        with self.assertRaises(ErroPreflightConab):
            planejar_preflight_conab(self.legacy,self.canon,self.doc)

    def test_xlsx_declarado_csv_bloqueia(self):
        self.doc["edicoes"][0]["raw_mime"]="text/csv"
        with self.assertRaises(ErroPreflightConab):
            planejar_preflight_conab(self.legacy,self.canon,self.doc)

    def test_replay_modificado_em_relacao_ao_xlsx_bloqueia(self):
        p=Path(self.doc["edicoes"][0]["replay_json_path"])
        data=json.loads(p.read_text())
        data[0]["pct_semana_atual"]=0.5
        p.write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaisesRegex(ErroPreflightConab,"replay declarado diverge"):
            planejar_preflight_conab(self.legacy,self.canon,self.doc)

    def test_teste_nao_modifica_bancos(self):
        self.assertEqual(self.legacy.execute("SELECT COUNT(*) FROM progresso_edicoes").fetchone()[0],1)
        self.assertEqual(self.canon.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        planejar_preflight_conab(self.legacy,self.canon,self.doc)
        self.assertEqual(self.legacy.execute("SELECT COUNT(*) FROM progresso_edicoes").fetchone()[0],1)
        self.assertEqual(self.canon.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
