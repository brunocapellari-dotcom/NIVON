"""E2E R11 -> estágio RAW canônico -> manifesto GCS (somente cliente falso).

Nenhum HTTP, GCP, custo ou autorização real. Referência CONAB é terceiro agrobr.
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.argentina_agricultura import CAMPOS
from nivon.sincronizacao_incremental_argentina_local import (
    SCHEMA as SCHEMA_AR, sincronizar_raw_argentina_local,
)
from nivon.sincronizacao_incremental_conab_lab import sincronizar_incremental_lab
from nivon.ponte_incremental_raw_gcs import (
    ErroPonteRaw, estagiar_raw_incremental,
)
from nivon.arquivo_raw_gcs import preparar_manifesto, arquivar_gcs
from nivon.ingestao_fontes_reais import exportar_jsonl
from nivon.carga_bigquery_fontes import planejar_carga, ErroCargaBigQuery
from test_arquivo_raw_gcs import Client

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "conab_progresso_agrobr_20260207.xlsx.b64"
_ARG_URL = "https://datos.magyp.gob.ar/dataset/estimaciones.csv"


def _raw_csv(producao="200"):
    row = ["Soja", "2025", "2024/25", "Cordoba", "14", "Rio Cuarto",
           "14001", "100", "90", producao, "2222"]
    return (";".join(CAMPOS) + "\n" + ";".join(row) + "\n").encode()


class TestPonteR11GcsE2E(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="nivon-r12-")
        self.addCleanup(td.cleanup)
        self.base = Path(td.name)
        self.base.chmod(0o700)
        for sub in ("ar_raw", "conab_raw", "conab_backup", "stage"):
            p = self.base / sub
            p.mkdir(mode=0o700)
            p.chmod(0o700)
        self.stage = self.base / "stage" / "quarentena.sqlite"
        self.argdb = self.base / "argentina.sqlite"
        self.conabdb = self.base / "conab.sqlite"
        self.ar_entries = []
        self.conab_doc = None

    def add_arg(self, value):
        data = _raw_csv(value)
        digest = hashlib.sha256(data).hexdigest()
        p = self.base / "ar_raw" / (digest + ".csv")
        p.write_bytes(data)
        p.chmod(0o600)
        item = {"recurso":"soja","sha256":digest,"arquivo":p.name,
                "origem_url":_ARG_URL,
                "coletado_em":"2026-10-20T12:00:00-03:00"}
        self.ar_entries.append(item)
        return item

    def sync_arg(self):
        cat = {"schema":SCHEMA_AR, "edicoes": self.ar_entries}
        result = sincronizar_raw_argentina_local(
            cat, banco=self.argdb, pasta_raw=self.base/"ar_raw",
            direitos_armazenamento_verificados=True,
        )
        return cat,result

    def sync_conab(self):
        raw = base64.b64decode(_FIXTURE.read_text().strip(), validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        ref = {
            "id":"AGROBR_20260207", "arquivo":"agrobr_20260207.xlsx",
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":digest,"bytes":len(raw),
            "competencia":"2026-02-07",
            "captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture",
            "observacoes_esperadas":11, "culturas_esperadas":["Soja","Milho 2ª"],
        }
        cat = {
            "schema":"NIVON_CONAB_REFERENCIAS_TERCEIRO_V1",
            "fornecedor_referencia":"bruno-portfolio/agrobr",
            "natureza":"REFERENCIAS_PUBLICADAS_POR_TERCEIRO_NAO_CAPTURA_DIRETA_CONAB",
            "edicoes":[ref],
        }
        p = self.base / "conab_raw" / ref["arquivo"]
        p.write_bytes(raw)
        p.chmod(0o600)
        sincronizar_incremental_lab(
            cat, self.conabdb, self.base/"conab_backup",
            arquivos_locais=self.base/"conab_raw",
        )
        self.conab_doc = cat
        return cat

    def conf_ar(self, catalogo):
        return {"catalogo":catalogo, "banco":self.argdb,
                "raw_dir":self.base/"ar_raw"}

    def conf_conab(self, catalogo):
        return {"catalogo":catalogo, "banco":self.conabdb,
                "raw_dir":self.base/"conab_raw"}

    def bridge(self, *, argentina=None, conab=None, executar=True, direitos=True):
        return estagiar_raw_incremental(
            banco_stage=self.stage,pasta_stage=self.base/"stage",
            argentina=argentina,conab=conab,
            executar=executar,direitos_arquivamento_verificados=direitos,
            bucket="nivon-raw-archive",
        )

    def test_end_to_end_duas_fontes_snapshot_gcs_mock_idempotente(self):
        self.add_arg("200")
        ar,_ = self.sync_arg()
        cb = self.sync_conab()
        kw = {"argentina":self.conf_ar(ar),"conab":self.conf_conab(cb)}
        first=self.bridge(**kw)
        self.assertEqual(first["estado"],"RAW_QUARENTENA_STAGE_LOCAL")
        self.assertEqual(first["quantidade"],2)
        self.assertFalse(first["upload_gcs"])
        self.assertFalse(first["bigquery_executado"])
        self.assertFalse(first["origem_conab_direta"])
        again=self.bridge(**kw)
        self.assertEqual(again["quantidade"],2)
        with sqlite3.connect(self.stage) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observacoes").fetchone()[0],0)
            state=set(db.execute("SELECT dataset_id,estado FROM snapshots"))
            self.assertEqual(state,{
                ("CONAB_AGROBR_TERCEIRO","QUARANTINED"),
                ("ARG_SAGYP_QUARENTENA","QUARANTINED"),
            })
            conaburl=db.execute(
                "SELECT url_publica FROM snapshots WHERE dataset_id=?",
                ("CONAB_AGROBR_TERCEIRO",),
            ).fetchone()[0]
            self.assertIn("raw.githubusercontent.com/bruno-portfolio/agrobr/",conaburl)
        client=Client()
        a=arquivar_gcs(banco=self.stage, raw_dir=self.base/"stage",
                       bucket="nivon-raw-archive",executar=True,client=client)
        b=arquivar_gcs(banco=self.stage, raw_dir=self.base/"stage",
                       bucket="nivon-raw-archive",executar=True,client=client)
        self.assertEqual(a["novos"],2)
        self.assertEqual(b["ja_existiam"],2)
        self.assertEqual(len(client.value.existing),2)
        jsonl=self.base/"observacoes.jsonl"
        e=exportar_jsonl(banco=self.stage,destino=jsonl)
        self.assertEqual(e["observacoes"],0)
        with self.assertRaises(ErroCargaBigQuery):
            planejar_carga(arquivo=jsonl,project_id="nivon-lab-001",dataset_id="NIVON_STAGING")

    def test_revisao_argentina_cria_novo_raw_preserva_vintage(self):
        self.add_arg("200")
        ar,_=self.sync_arg()
        conf=self.conf_ar(ar)
        self.bridge(argentina=conf)
        self.add_arg("250")
        ar,_=self.sync_arg()
        out=self.bridge(argentina=self.conf_ar(ar))
        self.assertEqual(out["quantidade"],2)
        with sqlite3.connect(self.stage) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observacoes").fetchone()[0],0)

    def test_direitos_ou_execucao_off_nao_criam_banco(self):
        self.add_arg("200")
        ar,_=self.sync_arg()
        conf=self.conf_ar(ar)
        dry=self.bridge(argentina=conf,executar=False)
        self.assertFalse(dry["executado"])
        with self.assertRaises(PermissionError):
            self.bridge(argentina=conf,direitos=False)
        self.assertFalse(self.stage.exists())

    def test_raw_adulterado_nao_cria_stage(self):
        a=self.add_arg("200")
        cat,_=self.sync_arg()
        (self.base/"ar_raw"/a["arquivo"]).write_bytes(b"adulterado")
        with self.assertRaises(ErroPonteRaw):
            self.bridge(argentina=self.conf_ar(cat))
        self.assertFalse(self.stage.exists())

    def test_lab_conab_adulterado_bloqueia_exportacao(self):
        cat=self.sync_conab()
        with sqlite3.connect(self.conabdb) as db:
            db.execute("UPDATE lab_observacao_conab SET observacao_json='{}' "
                       "WHERE rowid=(SELECT MIN(rowid) FROM lab_observacao_conab)")
        with self.assertRaisesRegex(Exception,"adulterado"):
            self.bridge(conab=self.conf_conab(cat))
        self.assertFalse(self.stage.exists())

    def test_preflight_multifonte_sem_escrita_parcial(self):
        self.add_arg("200")
        ar,_=self.sync_arg()
        cb=self.sync_conab()
        missing=self.base/"conab_raw"/"agrobr_20260207.xlsx"
        missing.unlink()
        with self.assertRaises(ErroPonteRaw):
            self.bridge(argentina=self.conf_ar(ar),conab=self.conf_conab(cb))
        self.assertFalse(self.stage.exists())

    def test_snapshot_promovido_externamente_nao_e_aceito_no_replay(self):
        self.add_arg("200")
        ar,_=self.sync_arg()
        self.bridge(argentina=self.conf_ar(ar))
        with sqlite3.connect(self.stage) as db:
            db.execute("UPDATE snapshots SET estado='NORMALIZED'")
        with self.assertRaisesRegex(ErroPonteRaw, "promovido"):
            self.bridge(argentina=self.conf_ar(ar))

    def test_stage_contaminado_por_observacao_analitica_e_recusado(self):
        self.add_arg("200")
        ar,_ = self.sync_arg()
        self.bridge(argentina=self.conf_ar(ar))
        with sqlite3.connect(self.stage) as db:
            db.execute("""INSERT INTO observacoes (
                 dataset_id,identidade,fingerprint,referencia,competencia,
                 publicacao,coletado_em,unidade,valor,campos_json,snapshot_id,natureza
                 ) SELECT dataset_id,'EVIDENCIA_TESTE',printf('%064d',0),
                   '2026-10-20',NULL,NULL,coletado_em,NULL,NULL,'{}',snapshot_id,
                   'ESTIMADO' FROM snapshots LIMIT 1""")
        with self.assertRaisesRegex(ErroPonteRaw, "observações analíticas"):
            self.bridge(argentina=self.conf_ar(ar))

    def test_stage_com_dataset_estranho_e_recusado_antes_de_novo_raw(self):
        self.add_arg("200")
        ar,_=self.sync_arg()
        self.bridge(argentina=self.conf_ar(ar))
        with sqlite3.connect(self.stage) as db:
            db.execute("UPDATE snapshots SET dataset_id='FONTE_DESCONHECIDA'")
        with self.assertRaisesRegex(ErroPonteRaw, "não autorizado"):
            self.bridge(argentina=self.conf_ar(ar))

    def test_privacidade_da_pasta_stage(self):
        self.add_arg("200")
        ar,_=self.sync_arg()
        if hasattr(__import__("os"),"chmod"):
            (self.base/"stage").chmod(0o755)
            with self.assertRaisesRegex(ErroPonteRaw,"0700"):
                self.bridge(argentina=self.conf_ar(ar))
        self.assertFalse(self.stage.exists())


if __name__=="__main__":
    unittest.main()
