"""Persistência incremental LAB CONAB, execução por ciclos e falhas atômicas.

Sem rede, fonte oficial ou credenciais. A fixture é do agrobr.
"""
import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.sincronizacao_incremental_conab_lab import (
    ErroIncrementalConab, abrir_db_lab, planejar_delta,
    sincronizar_incremental_lab, backup_restore_lab,
)

ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"config"/"conab_referencias_multivintage_20261021.json"
SAMPLE=ROOT/"tests"/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"


class TestIncrementalLabConab(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root.chmod(0o700)
        self.source=self.root/"arquivos"
        self.source.mkdir(mode=0o700)
        self.backups=self.root/"backups"
        self.backups.mkdir(mode=0o700)
        self.db=self.root/"lab.sqlite"
        self.raw=base64.b64decode(SAMPLE.read_text().strip(),validate=True)
        self.ref={
            "id":"AGROBR_20260207","arquivo":"agrobr_20260207.xlsx",
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":hashlib.sha256(self.raw).hexdigest(),"bytes":len(self.raw),
            "competencia":"2026-02-07","captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture",
            "observacoes_esperadas":11,"culturas_esperadas":["Soja","Milho 2ª"],
        }
        self.cat={
            "schema":"NIVON_CONAB_REFERENCIAS_TERCEIRO_V1",
            "fornecedor_referencia":"bruno-portfolio/agrobr",
            "natureza":"REFERENCIAS_PUBLICADAS_POR_TERCEIRO_NAO_CAPTURA_DIRETA_CONAB",
            "edicoes":[self.ref],
        }
        (self.source/self.ref["arquivo"]).write_bytes(self.raw)

    def sync(self,catalogo=None):
        return sincronizar_incremental_lab(
            catalogo or self.cat,self.db,self.backups,
            arquivos_locais=self.source)

    def test_primeira_execucao_persiste_11_e_prova_backup_duravel_lab(self):
        out=self.sync()
        self.assertEqual(out["edicoes_novas"],1)
        self.assertEqual(out["observacoes_novas"],11)
        self.assertEqual(out["observacoes_no_lab"],11)
        self.assertTrue(out["backup"]["backup_restaurado_e_conferido"])
        self.assertFalse(out["backup"]["backup_de_producao"])
        self.assertEqual(len(out["backup"]["sha256_backup"]),64)
        self.assertTrue((self.backups/out["backup"]["arquivo_backup"]).is_file())
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0],11)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_eventos_incrementais").fetchone()[0],1)
        if os.name=="posix":
            self.assertEqual(self.db.stat().st_mode&0o077,0)
            self.assertEqual((self.backups/out["backup"]["arquivo_backup"]).stat().st_mode&0o077,0)

    def test_segunda_execucao_processos_diferentes_sem_download_ou_backup(self):
        first=self.sync()
        (self.source/self.ref["arquivo"]).unlink()
        out=self.sync()
        self.assertEqual(out["estado"],"SEM_DELTA_NENHUM_DOWNLOAD_OU_GRAVACAO")
        self.assertEqual(out["edicoes_novas"],0)
        self.assertEqual(out["edicoes_inalteradas"],1)
        self.assertEqual(out["requisicoes_previstas"],0)
        self.assertFalse(out["backup_criado"])
        self.assertEqual(len(list(self.backups.iterdir())),1)
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_eventos_incrementais").fetchone()[0],1)

    def test_revisao_da_mesma_edicao_quarentena_e_sem_escrita(self):
        self.sync()
        changed={**self.ref,"sha256":"0"*64}
        with self.assertRaisesRegex(ErroIncrementalConab,"EDICAO_MUDOU"):
            self.sync({**self.cat,"edicoes":[changed]})
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_eventos_incrementais").fetchone()[0],1)

    def test_nova_edicao_mesma_competencia_bloqueia(self):
        self.sync()
        other={**self.ref,"id":"AGROBR_20260208","arquivo":"agrobr_20260208.xlsx",
               "sha256":"0"*64}
        # O catálogo de uma rodada não aceita duas entradas da mesma
        # competência; apresentar somente a revisão contra a edição já
        # persistida para exercitar a quarentena incremental.
        with self.assertRaisesRegex(ErroIncrementalConab,"REVISAO_DA_SEMANA"):
            self.sync({**self.cat,"edicoes":[other]})

    def test_backup_nao_sobrescreve_documento_existente(self):
        self.sync()
        with abrir_db_lab(self.db) as db:
            with self.assertRaisesRegex(ErroIncrementalConab,"backup do lote já existe"):
                backup_restore_lab(db,self.backups)

    def test_falha_transacao_reverte_todas_linhas(self):
        with abrir_db_lab(self.db) as db:
            db.execute("""CREATE TRIGGER falha_sync BEFORE INSERT ON lab_eventos_incrementais
                           BEGIN SELECT RAISE(ABORT,'falha proposital'); END""")
        with self.assertRaisesRegex(ErroIncrementalConab,"transação"):
            self.sync()
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0],0)
        self.assertEqual(list(self.backups.iterdir()),[])

    def test_raw_sha_incorreto_impede_nova_versao(self):
        (self.source/self.ref["arquivo"]).write_bytes(self.raw+b"!")
        with self.assertRaises(ErroIncrementalConab):
            self.sync()
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0],0)

    def test_diretorio_publico_bloqueia(self):
        if os.name!="posix":self.skipTest("POSIX")
        self.backups.chmod(0o755)
        with self.assertRaisesRegex(ErroIncrementalConab,"0700"):
            self.sync()

    def test_sem_tipo_entrada_bloqueia(self):
        with self.assertRaises(ErroIncrementalConab):
            sincronizar_incremental_lab(self.cat,self.db,self.backups)

    def test_historico_alterado_mesma_quantidade_bloqueia_noop(self):
        self.sync()
        with sqlite3.connect(str(self.db)) as db:
            db.execute("""UPDATE lab_observacao_conab SET observacao_json='{"falso":true}'
                          WHERE rowid=(SELECT MIN(rowid) FROM lab_observacao_conab)""")
        with self.assertRaisesRegex(ErroIncrementalConab,"adulterado"):
            self.sync()

    def test_uma_linha_excluida_do_historico_bloqueia_noop(self):
        self.sync()
        with sqlite3.connect(str(self.db)) as db:
            db.execute("DELETE FROM lab_observacao_conab WHERE rowid=(SELECT MIN(rowid) FROM lab_observacao_conab)")
        with self.assertRaisesRegex(ErroIncrementalConab,"adulterado"):
            self.sync()

    def test_backup_atual_corrompido_bloqueia_noop(self):
        self.sync()
        only=next(self.backups.glob("*.sqlite"))
        with only.open("ab") as f:
            f.write(b"adulterado")
        # SQLite às vezes tolera bytes após EOF; testar contra divergência
        # real de linhas, sem confiar somente no formato do arquivo.
        with sqlite3.connect(str(only)) as db:
            db.execute("DELETE FROM lab_observacao_conab WHERE rowid=(SELECT MIN(rowid) FROM lab_observacao_conab)")
        with self.assertRaisesRegex(ErroIncrementalConab,"backup atual diverge"):
            self.sync()

    def test_backup_ausente_nao_equivale_a_sincronizacao_verde(self):
        self.sync()
        next(self.backups.glob("*.sqlite")).unlink()
        with self.assertRaisesRegex(ErroIncrementalConab,"backup da última execução ausente"):
            self.sync()

    def test_catalogo_original_tres_novos_sem_simular_bytes(self):
        doc=json.loads(CAT.read_text())
        with abrir_db_lab(self.db) as db:
            plan=planejar_delta(db,doc)
            self.assertEqual(len(plan["novas"]),3)
            self.assertEqual(len(plan["inalteradas"]),0)
            self.assertEqual(len(plan["conflitos"]),0)


if __name__=="__main__":
    unittest.main()
