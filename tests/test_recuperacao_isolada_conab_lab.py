"""Recuperação real de SQLite LAB em diretório isolado, sem rede."""
import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.recuperacao_isolada_conab_lab import (
    ErroRecuperacaoConab,recuperar_backup_isolado,RESTORED_NAME,EVIDENCE_NAME,
)
from nivon.sincronizacao_incremental_conab_lab import sincronizar_incremental_lab

FILE=Path(__file__).parent/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"


class TestRecuperacaoIsoladaLab(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.raw=self.root/"raw"
        self.raw.mkdir(mode=0o700)
        self.backup=self.root/"backup"
        self.backup.mkdir(mode=0o700)
        self.destination=self.root/"restored"
        self.destination.mkdir(mode=0o700)
        self.db=self.root/"lab.sqlite"
        data=base64.b64decode(FILE.read_text().strip(),validate=True)
        self.entry={
            "id":"AGROBR_20260207","arquivo":"agrobr_20260207.xlsx",
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data),
            "competencia":"2026-02-07","captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture",
            "observacoes_esperadas":11,"culturas_esperadas":["Soja","Milho 2ª"],
        }
        self.cat={
            "schema":"NIVON_CONAB_REFERENCIAS_TERCEIRO_V1",
            "fornecedor_referencia":"bruno-portfolio/agrobr",
            "natureza":"REFERENCIAS_PUBLICADAS_POR_TERCEIRO_NAO_CAPTURA_DIRETA_CONAB",
            "edicoes":[self.entry],
        }
        (self.raw/self.entry["arquivo"]).write_bytes(data)
        self.out=sincronizar_incremental_lab(
            self.cat,self.db,self.backup,arquivos_locais=self.raw)
        self.snap=self.backup/self.out["backup"]["arquivo_backup"]
        self.sha=self.out["backup"]["sha256_backup"]

    def recover(self,**kwargs):
        return recuperar_backup_isolado(
            kwargs.pop("file",self.snap),kwargs.pop("sha",self.sha),
            kwargs.pop("catalog",self.cat),kwargs.pop("dest",self.destination),
            banco_vivo=kwargs.pop("live",self.db),
            cortes_coleta=kwargs.pop("cuts",["2026-02-01T00:00:00Z",
                                           "2026-02-24T10:00:00Z"]),
        )

    def test_recuperar_e_reconciliar_integralmente_sem_tocar_fonte(self):
        before=self.db.read_bytes()
        result=self.recover()
        self.assertEqual(result["estado"],"BACKUP_RESTAURADO_EM_AMBIENTE_ISOLADO_LAB")
        self.assertTrue(result["restauracao_integridade_fk_semantica_conferida"])
        self.assertTrue(result["comparacao"]["equivalencia_com_banco_vivo"])
        self.assertEqual(result["resumo_restaurado"]["observacoes_originais"],11)
        self.assertEqual(result["resumo_restaurado"]["retificacoes"],0)
        self.assertIsNone(result["cortes_asof"][0]["versao_sha"])
        self.assertEqual(result["cortes_asof"][1]["versao_sha"],self.entry["sha256"])
        self.assertEqual((self.destination/RESTORED_NAME).stat().st_mode & 0o077,0)
        self.assertEqual((self.destination/EVIDENCE_NAME).stat().st_mode & 0o077,0)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(result["banco_canonico_modificado"])
        self.assertFalse(result["publicacao_permitida"])

    def test_recuperacao_sem_db_vivo_depois_de_perda(self):
        self.db.unlink()
        result=self.recover(live=None)
        self.assertFalse(result["comparacao"]["comparacao_realizada"])
        self.assertIsNone(result["comparacao"]["equivalencia_com_banco_vivo"])
        self.assertEqual(result["resumo_restaurado"]["observacoes_originais"],11)

    def test_sha_de_origem_errado_bloqueia_antes_de_criar_arquivo(self):
        with self.assertRaisesRegex(ErroRecuperacaoConab,"SHA do backup difere"):
            self.recover(sha="0"*64)
        self.assertEqual(list(self.destination.iterdir()),[])

    def test_snap_modificado_bloqueia(self):
        with self.snap.open("ab") as out:
            out.write(b"alteracao")
        with self.assertRaisesRegex(ErroRecuperacaoConab,"SHA do backup difere"):
            self.recover()
        self.assertEqual(list(self.destination.iterdir()),[])

    def test_nao_sobrescreve_restauracao_existente(self):
        self.recover()
        with self.assertRaisesRegex(ErroRecuperacaoConab,"vazio"):
            self.recover()

    def test_destino_symlink_ou_publico_recusado(self):
        if os.name=="posix":
            self.destination.chmod(0o755)
            with self.assertRaisesRegex(ErroRecuperacaoConab,"0700"):
                self.recover()
            self.destination.chmod(0o700)
        other=self.root/"link"
        try:other.symlink_to(self.destination,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest("sem symlink")
        with self.assertRaises(ErroRecuperacaoConab):
            self.recover(dest=other)

    def test_nome_snapshot_inesperado_bloqueia(self):
        another=self.backup/"desconhecido.sqlite"
        another.write_bytes(self.snap.read_bytes())
        another.chmod(0o600)
        with self.assertRaisesRegex(ErroRecuperacaoConab,"nomes LAB"):
            self.recover(file=another)

    def test_corte_sem_fuso_bloqueia_sem_deixar_parcial(self):
        with self.assertRaises(ValueError):
            self.recover(cuts=["2026-02-24T10:00:00"])
        self.assertEqual(list(self.destination.iterdir()),[])

    def test_catalogo_com_sha_divergente_bloqueia(self):
        broken={**self.cat,"edicoes":[{**self.entry,"sha256":"0"*64}]}
        with self.assertRaisesRegex(ErroRecuperacaoConab,"não pertence"):
            self.recover(catalog=broken)
        self.assertEqual(list(self.destination.iterdir()),[])

    def test_backup_comperda_de_observacoes_detectado_apos_hash_declarado(self):
        # Um digest recalculado de arquivo adulterado sozinho não prova
        # integridade semântica: a auditoria deve detectar contagem/anchor.
        corrupt=self.backup/"conab-lab-seq-0099.sqlite"
        corrupt.write_bytes(self.snap.read_bytes())
        corrupt.chmod(0o600)
        with sqlite3.connect(str(corrupt)) as db:
            db.execute("DELETE FROM lab_observacao_conab WHERE rowid=(SELECT MIN(rowid) FROM lab_observacao_conab)")
        fresh=hashlib.sha256(corrupt.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,"adulterado|incompleto"):
            self.recover(file=corrupt,sha=fresh)
        self.assertEqual(list(self.destination.iterdir()),[])


if __name__=="__main__":
    unittest.main()
