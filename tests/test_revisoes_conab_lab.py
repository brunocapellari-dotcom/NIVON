"""E2E laboratório: edição de terceiro + duas versões XLSX artificialmente alteradas.

Não são retificações reais, nem licenças de distribuição da CONAB.
"""
import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.fixture_retificacao_conab import alterar_xlsx_apenas_teste
from nivon.sincronizacao_incremental_conab_lab import (
    sincronizar_incremental_lab, abrir_db_lab, ErroIncrementalConab,
)
from nivon.revisoes_conab_lab import aplicar_retificacoes_lab, ErroRetificacaoConab

BASE=Path(__file__).parent/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"


class TestRetificacoesConabLab(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root.chmod(0o700)
        self.rawdir=self.root/"raw"
        self.rawdir.mkdir(mode=0o700)
        self.backups=self.root/"backups"
        self.backups.mkdir(mode=0o700)
        self.dbfile=self.root/"lab.sqlite"
        raw=base64.b64decode(BASE.read_text().strip(),validate=True)
        self.base={
            "id":"AGROBR_20260207","arquivo":"agrobr_20260207.xlsx",
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
            "competencia":"2026-02-07","captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture",
            "observacoes_esperadas":11,"culturas_esperadas":["Soja","Milho 2ª"],
        }
        self.cat={
            "schema":"NIVON_CONAB_REFERENCIAS_TERCEIRO_V1",
            "fornecedor_referencia":"bruno-portfolio/agrobr",
            "natureza":"REFERENCIAS_PUBLICADAS_POR_TERCEIRO_NAO_CAPTURA_DIRETA_CONAB",
            "edicoes":[self.base],
        }
        (self.rawdir/self.base["arquivo"]).write_bytes(raw)
        result=sincronizar_incremental_lab(self.cat,self.dbfile,self.backups,
                                           arquivos_locais=self.rawdir)
        self.assertEqual(result["observacoes_no_lab"],11)
        new1,cell1=alterar_xlsx_apenas_teste(raw)
        new2,cell2=alterar_xlsx_apenas_teste(new1)
        self.assertNotEqual(hashlib.sha256(new1).hexdigest(),hashlib.sha256(new2).hexdigest())
        self.events=[]
        parent=self.base["sha256"]
        for i,body in ((1,new1),(2,new2)):
            file=f"retificacao-20260207-{i:03d}.xlsx"
            (self.rawdir/file).write_bytes(body)
            ref={
                "id":f"RETIF_LAB_20260207_{i:03d}",
                "id_base":self.base["id"],"sha_base":self.base["sha256"],
                "sha_anterior":parent,
                "sha256":hashlib.sha256(body).hexdigest(),
                "arquivo":file,"tamanho":len(body),"competencia":"2026-02-07",
                "coletado_em":f"2026-10-23T15:{i:02d}:00Z",
                "motivo":"SIMULACAO_LAB_NAO_PUBLICADA_PELA_CONAB",
                "evidencia":"XLSX_FIXTURE_ALTERADA_SINTETICAMENTE",
            }
            self.events.append(ref)
            parent=ref["sha256"]

    def apply(self,events):
        return aplicar_retificacoes_lab(self.cat,{
            "schema":"NIVON_CONAB_RETIFICACOES_SINTETICAS_LAB_V1",
            "revisoes":events,
        },self.dbfile,self.rawdir,self.backups)

    def test_duas_retificacoes_encadeadas_preservam_original(self):
        first=self.apply(self.events[:1])
        self.assertEqual(first["retificacoes_novas"],1)
        self.assertEqual(first["deltas"][0]["alterados"],1)
        self.assertEqual(first["deltas"][0]["incluidos"],0)
        self.assertEqual(first["deltas"][0]["excluidos"],0)
        self.assertTrue(first["backup"]["restore_verificado"])
        second=self.apply(self.events[1:])
        self.assertEqual(second["retificacoes_novas"],1)
        self.assertEqual(second["retificacoes_preservadas"],1)
        with sqlite3.connect(str(self.dbfile)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0],11)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_retificacoes_conab").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_retificacao_observacoes").fetchone()[0],22)
            chain=list(db.execute("SELECT sha_anterior FROM lab_retificacoes_conab ORDER BY revisao"))
            self.assertEqual(chain[0][0],self.base["sha256"])
            self.assertEqual(chain[1][0],self.events[0]["sha256"])
        self.assertEqual(len(list(self.backups.glob("conab-retif-*.sqlite"))),2)
        self.assertEqual(len(list(self.backups.glob("conab-lab-*.sqlite"))),1)

    def test_replay_noop_nao_reescreve_ou_cria_backup(self):
        self.apply(self.events[:1])
        again=self.apply(self.events[:1])
        self.assertEqual(again["estado"],"SEM_RETIFICACAO_NOVA")
        self.assertFalse(again["backup_criado"])
        self.assertEqual(len(list(self.backups.glob("conab-retif-*.sqlite"))),1)

    def test_predecessor_errado_nao_revisa_historico(self):
        bad={**self.events[0],"sha_anterior":"0"*64}
        with self.assertRaisesRegex(ErroRetificacaoConab,"predecessor"):
            self.apply([bad])
        with sqlite3.connect(str(self.dbfile)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0],11)

    def test_arquivo_adulterado_falha_antes_da_transacao(self):
        ref=self.events[0]
        (self.rawdir/ref["arquivo"]).write_bytes(b"X"+(self.rawdir/ref["arquivo"]).read_bytes())
        with self.assertRaises(ErroRetificacaoConab):
            self.apply([ref])
        with sqlite3.connect(str(self.dbfile)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_retificacoes_conab").fetchone()[0],0)

    def test_retificacao_sem_diferenca_bloqueada(self):
        ref=self.events[0]
        raw=(self.rawdir/self.base["arquivo"]).read_bytes()
        no_change={**ref,"sha256":hashlib.sha256(raw).hexdigest(),"tamanho":len(raw)}
        (self.rawdir[ref["arquivo"]).write_bytes(raw)
        with self.assertRaises(ErroRetificacaoConab):
            self.apply([no_change])

    def test_duplicar_sha_com_evidencia_mudada_bloqueia(self):
        self.apply(self.events[:1])
        changed={**self.events[0],"coletado_em":"2026-10-23T16:20:00Z"}
        with self.assertRaisesRegex(ErroRetificacaoConab,"evidência"):
            self.apply([changed])

    def test_retificacao_ausencia_de_backup_falha_tambem_no_sync_base(self):
        self.apply(self.events[:1])
        next(self.backups.glob("conab-retif-*.sqlite")).unlink()
        with self.assertRaisesRegex(ErroRetificacaoConab,"backup da retificação ausente"):
            sincronizar_incremental_lab(self.cat,self.dbfile,self.backups,
                                        arquivos_locais=self.rawdir)

    def test_retificacao_corrompida_falha_no_sync_base(self):
        self.apply(self.events[:1])
        with sqlite3.connect(str(self.dbfile)) as db:
            db.execute("""UPDATE lab_retificacao_observacoes SET observacao_json='{"falso":true}'
                          WHERE rowid=(SELECT MIN(rowid) FROM lab_retificacao_observacoes)""")
        with self.assertRaisesRegex(ErroRetificacaoConab,"alterado"):
            sincronizar_incremental_lab(self.cat,self.dbfile,self.backups,
                                        arquivos_locais=self.rawdir)

    def test_retificacoes_em_lote_rollback_se_segunda_raw_ausente(self):
        (self.rawdir/self.events[1]["arquivo"]).unlink()
        with self.assertRaises(ErroRetificacaoConab):
            self.apply(self.events)
        with sqlite3.connect(str(self.dbfile)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lab_retificacoes_conab").fetchone()[0],0)

    def test_revisao_nunca_publicada(self):
        out=self.apply(self.events)
        self.assertEqual(out["retificacoes_novas"],2)
        self.assertFalse(out["dados_conab_retificados_de_fato"])
        self.assertFalse(out["migracao_permitida"])
        self.assertFalse(out["publicacao_permitida"])


if __name__=="__main__":
    unittest.main()
