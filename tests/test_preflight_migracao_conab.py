"""Pré-voo migratório CONAB: fixtures, direitos não afirmados e zero escrita."""
import copy
import csv
import io
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr,redirect_stdout
from datetime import datetime
from pathlib import Path

from nivon.conab_agrobr import normalizar_progresso
from nivon.progresso_store import abrir_progresso,gravar_progresso
from nivon.registro_snapshots import abrir_registro
from nivon.progresso_conab_historico import registrar_progresso_local,preparar_esquema
from nivon.conciliacao_progresso_stores import ErroConciliacaoConab
from nivon.conab_replay_raw import CAMPOS_CSV, PARSER_ID
from nivon.preflight_migracao_conab import (
    ErroPreflightConab,planejar_preflight_conab,main,
)

URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
PUB="2026-10-19T11:00:00+00:00"
STAMP="2026-10-20T12:00:00+00:00"
BYTES=b"linha csv falsa de teste"
CAT={"datasets":[{"id":"CONAB_PROGRESSO_SEMANAL","source_id":"CONAB",
                  "enabled":False,"collection_authorized":False}]}


def normalizar(pct=.35,hora=STAMP,semana="2026-10-18"):
    return normalizar_progresso(
        [{"cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
          "uf":"MT","semana_atual":semana,"pct_semana_atual":pct,
          "pct_semana_anterior":.27,"pct_ano_anterior":.32,
          "pct_media_5_anos":.30}],
        fonte_url=URL,coletado_em=datetime.fromisoformat(hora),
        publicado_em=PUB)


class TestPreflightMigracaoConab(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.legado=abrir_progresso()
        self.canonico=abrir_registro()
        preparar_esquema(self.canonico)
        self.addCleanup(self.legado.close)
        self.addCleanup(self.canonico.close)
        self.manifesto={"schema":"NIVON_CONAB_PREFLIGHT_V1","edicoes":[]}

    def salvar_legado(self,pct=.35,semana="2026-10-18"):
        gravar_progresso(self.legado,normalizar(pct=pct,semana=semana),
                        evidence_id="TESTE_SEM_LICENCA",direitos_confirmados=True)
        return self.legado.execute(
            "SELECT id,sha256_json FROM progresso_edicoes ORDER BY id DESC LIMIT 1").fetchone()

    def adicionar_evidencia(self,sid,sha,raw=BYTES,rows=None):
        original=self.root/f"fonte-{sid}.txt"
        replay=self.root/f"replay-{sid}.json"
        original.write_bytes(raw)
        replay.write_text(json.dumps(normalizar() if rows is None else rows),encoding="utf-8")
        entry={
            "legacy_id":sid,"sha256_json":sha,
            "url_origem":URL,"raw_path":str(original),
            "raw_sha256":hashlib.sha256(raw).hexdigest(),
            "raw_bytes":len(raw),"raw_mime":"text/plain",
            "replay_json_path":str(replay),
            "parser_versao":"TEST_ONLY_V1",
            "direitos_evidencia_id":"NAO_HOMOLOGADO_TESTE",
        }
        self.manifesto["edicoes"].append(entry)
        return entry


    def usar_parser_csv(self, evidence):
        original=normalizar()[0]
        def cell(k):
            if k=="semana_atual":return original["competencia"]
            v=original.get(k)
            if v is None:return ""
            if isinstance(v,bool):return "true" if v else "false"
            return str(v)
        target=io.StringIO(newline="")
        w=csv.writer(target)
        w.writerow(CAMPOS_CSV)
        w.writerow([cell(k) for k in CAMPOS_CSV])
        raw=target.getvalue().encode("utf-8")
        Path(evidence["raw_path"]).write_bytes(raw)
        evidence["raw_sha256"]=hashlib.sha256(raw).hexdigest()
        evidence["raw_bytes"]=len(raw)
        evidence["raw_mime"]="text/csv"
        evidence["parser_versao"]=PARSER_ID
        return raw

    def test_preflight_executa_bytes_csv_sem_homologar(self):
        sid,sha=self.salvar_legado()
        proof=self.adicionar_evidencia(sid,sha)
        self.usar_parser_csv(proof)
        r=self.plano()
        self.assertEqual(r["replays_csv_intercambio_executados"],1)
        self.assertEqual(r["por_estado"],{
            "RAW_CSV_INTERCAMBIO_REPROCESSADO_SEM_HOMOLOGACAO_CONAB":1})
        self.assertTrue(r["itens"][0]["csv_intercambio_reexecutado_localmente"])
        self.assertEqual(len(r["itens"][0]["parser_codigo_sha256"]),64)
        self.assertFalse(r["itens"][0]["parser_raw_reprodutivel_auditado"])
        self.assertFalse(r["parser_conab_oficial_homologado"])
        self.assertFalse(r["migracao_permitida"])

    def test_preflight_bytes_alterados_com_hash_novo_mas_replay_velho(self):
        sid,sha=self.salvar_legado()
        proof=self.adicionar_evidencia(sid,sha)
        raw=self.usar_parser_csv(proof)
        edited=raw.replace(b"0.35",b"0.36")
        Path(proof["raw_path"]).write_bytes(edited)
        proof["raw_sha256"]=hashlib.sha256(edited).hexdigest()
        proof["raw_bytes"]=len(edited)
        with self.assertRaisesRegex(ErroPreflightConab,"RAW reprocessado diverge"):
            self.plano()

    def test_preflight_parser_csv_nao_e_parser_xlsx(self):
        sid,sha=self.salvar_legado()
        proof=self.adicionar_evidencia(sid,sha)
        self.usar_parser_csv(proof)
        proof["raw_mime"]="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_preflight_parser_legado_nao_executavel_resta_nao_verificado(self):
        sid,sha=self.salvar_legado()
        self.adicionar_evidencia(sid,sha)
        r=self.plano()
        self.assertEqual(r["replays_csv_intercambio_executados"],0)
        self.assertIsNone(r["itens"][0]["parser_codigo_sha256"])
        self.assertFalse(r["migracao_permitida"])

    def test_preflight_csv_adulterado_sem_atualizar_sha_rejeitado(self):
        sid,sha=self.salvar_legado()
        proof=self.adicionar_evidencia(sid,sha)
        raw=self.usar_parser_csv(proof)
        Path(proof["raw_path"]).write_bytes(raw+b"adulterado")
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def plano(self,doc=None):
        return planejar_preflight_conab(self.legado,self.canonico,
                   self.manifesto if doc is None else doc)

    def test_bancos_vazios_retorna_zero_legado_sem_liberar_migracao(self):
        r=self.plano()
        self.assertEqual(r["edicoes_legadas"],0)
        self.assertEqual(r["edicoes_com_evidencia"],0)
        self.assertFalse(r["migracao_permitida"])
        self.assertFalse(r["backup_verificado"])
        self.assertFalse(r["restauracao_testada"])

    def test_edicao_sem_manifesto_bloqueada(self):
        self.salvar_legado()
        r=self.plano()
        self.assertEqual(r["por_estado"],{"SEM_MANIFESTO_RAW":1})
        self.assertEqual(r["edicoes_com_evidencia"],0)
        self.assertFalse(r["itens"][0]["pronto_para_migracao"])

    def test_raw_e_replay_locais_corretos_ainda_nao_comprovam_parser(self):
        sid,sha=self.salvar_legado()
        self.adicionar_evidencia(sid,sha)
        r=self.plano()
        self.assertEqual(r["por_estado"],
            {"RAW_E_REPLAY_LOCAIS_CONFERIDOS_SEM_PROVA_DO_PARSER":1})
        self.assertEqual(r["itens"][0]["observacoes_replay"],1)
        self.assertEqual(r["itens"][0]["hashes"]["normalizado_sha256"],sha)
        self.assertFalse(r["itens"][0]["parser_raw_reprodutivel_auditado"])
        self.assertFalse(r["itens"][0]["direitos_validados_externamente"])
        self.assertFalse(r["arquivo_bruto_para_parser_reexecutado_pelo_modulo"])
        self.assertFalse(r["migracao_permitida"])

    def test_raw_reexistente_canonicamente_nao_duplica(self):
        sid,sha=self.salvar_legado()
        self.adicionar_evidencia(sid,sha)
        registrar_progresso_local(
            self.canonico,CAT,registros=normalizar(),
            sha256_origem=hashlib.sha256(BYTES).hexdigest(),
            bytes_origem=len(BYTES),mime_origem="text/plain",
            coletado_em=STAMP)
        r=self.plano()
        self.assertEqual(r["por_estado"],{"SHA_RAW_PRESENTE_NO_CANONICO_CONFERIR_CAPTURAS":1})
        self.assertFalse(r["snapshot_canonico_compatibilizado"])
        self.assertFalse(r["migracao_permitida"])

    def test_raw_sha_canônico_com_valores_divergentes_bloqueia(self):
        sid,sha=self.salvar_legado()
        self.adicionar_evidencia(sid,sha)
        registrar_progresso_local(
            self.canonico,CAT,registros=normalizar(pct=.40),
            sha256_origem=hashlib.sha256(BYTES).hexdigest(),
            bytes_origem=len(BYTES),mime_origem="text/plain",
            coletado_em=STAMP)
        with self.assertRaisesRegex(ErroPreflightConab,"conflito"):
            self.plano()

    def test_tampering_do_raw_falha_fechado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        Path(row["raw_path"]).write_bytes(b"mudou bytes sem atualizar prova")
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_raw_hash_errado_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["raw_sha256"]="0"*64
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_replay_divergente_do_legado_bloqueado(self):
        sid,sha=self.salvar_legado()
        self.adicionar_evidencia(sid,sha,rows=normalizar(pct=.41))
        with self.assertRaisesRegex(ErroPreflightConab,"replay declarado diverge"):
            self.plano()

    def test_schema_manifesto_diferente_bloqueado(self):
        self.manifesto["schema"]="V2"
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_hash_normalizado_errado_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["sha256_json"]="0"*64
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_url_diferente_do_legado_bloqueada(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["url_origem"]="https://www.conab.gov.br/outra"
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_manifesto_duplicado_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        self.manifesto["edicoes"].append(copy.deepcopy(row))
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_edicao_inexistente_bloqueada(self):
        self.manifesto["edicoes"]=[{"legacy_id":100}]
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_path_relativo_de_raw_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["raw_path"]="relativo.txt"
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_symlink_de_raw_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        link=self.root/"fonte-symlink.txt"
        try:
            link.symlink_to(row["raw_path"])
        except (OSError,NotImplementedError):
            self.skipTest("ambiente sem suporte a symlink")
        row["raw_path"]=str(link)
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_symlink_de_replay_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        link=self.root/"replay-symlink.json"
        try:
            link.symlink_to(row["replay_json_path"])
        except (OSError,NotImplementedError):
            self.skipTest("ambiente sem suporte a symlink")
        row["replay_json_path"]=str(link)
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_mime_inesperado_bloqueia(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["raw_mime"]="text/html"
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_prova_direitos_vazia_bloqueia(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["direitos_evidencia_id"]=""
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_evidencia_de_parser_vazia_bloqueia(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        row["parser_versao"]=""
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_replay_json_com_chave_duplicada_bloqueado(self):
        sid,sha=self.salvar_legado()
        row=self.adicionar_evidencia(sid,sha)
        Path(row["replay_json_path"]).write_text('[{"a":1,"a":2}]',encoding="utf-8")
        with self.assertRaises(ErroPreflightConab):
            self.plano()

    def test_two_editions_mismo_raw_sha_bloqueia(self):
        sid,sha=self.salvar_legado()
        self.adicionar_evidencia(sid,sha)
        sid2,sha2=self.salvar_legado(pct=.42)
        self.adicionar_evidencia(sid2,sha2,rows=normalizar(pct=.42))
        with self.assertRaisesRegex(ErroPreflightConab,"mesmo RAW"):
            self.plano()

    def test_hash_legado_corrompido_bloqueado_antes_de_plano(self):
        sid,sha=self.salvar_legado()
        self.legado.execute("UPDATE progresso_edicoes SET sha256_json='0'")
        with self.assertRaises(ErroConciliacaoConab):
            self.plano()

    def test_cli_em_bancos_readonly_nao_grava_nem_exibe_paths(self):
        lpath=self.root/"legacy.db"
        cpath=self.root/"canonical.db"
        l=abrir_progresso(lpath)
        c=abrir_registro(cpath)
        preparar_esquema(c)
        gravar_progresso(l,normalizar(),evidence_id="TESTE",direitos_confirmados=True)
        l.close()
        c.close()
        docpath=self.root/"manifesto.json"
        docpath.write_text(json.dumps(self.manifesto),encoding="utf-8")
        size=(lpath.stat().st_size,cpath.stat().st_size)
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--legado",str(lpath),"--canonico",str(cpath),
                                   "--manifesto",str(docpath),"--resumo"]),0)
        r=json.loads(output.getvalue())
        self.assertEqual(r["por_estado"],{"SEM_MANIFESTO_RAW":1})
        self.assertFalse(r["migracao_permitida"])
        self.assertNotIn(str(self.root),output.getvalue())
        self.assertEqual(size,(lpath.stat().st_size,cpath.stat().st_size))

    def test_cli_banco_inexistente_nao_cria_arquivo(self):
        legacy=self.root/"notyet.db"
        canon=self.root/"none.db"
        manifest=self.root/"manifest.json"
        manifest.write_text(json.dumps(self.manifesto),encoding="utf-8")
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as err:
            main(["--legado",str(legacy),"--canonico",str(canon),
                  "--manifesto",str(manifest)])
        self.assertEqual(err.exception.code,2)
        self.assertFalse(legacy.exists())
        self.assertFalse(canon.exists())


if __name__ == "__main__":
    unittest.main()
