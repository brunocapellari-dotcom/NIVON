"""Regressões sintéticas: nunca migrar nem confundir hash normalizado com bruto."""
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nivon.conab_agrobr import normalizar_progresso
from nivon.progresso_store import abrir_progresso, gravar_progresso
from nivon.registro_snapshots import abrir_registro
from nivon.progresso_conab_historico import registrar_progresso_local
from nivon.conciliacao_progresso_stores import (
    conciliar_stores_conab, ErroConciliacaoConab, main,
)

URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/boletim-fixture"
STAMP = "2026-10-20T13:00:00+00:00"
PUB = "2026-10-19T12:00:00+00:00"
RAW = [{"cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
        "uf":"MT","semana_atual":"2026-10-18","pct_semana_atual":0.35,
        "pct_semana_anterior":0.25,"pct_ano_anterior":0.32,
        "pct_media_5_anos":0.29}]
CAT = {"datasets":[{"id":"CONAB_PROGRESSO_SEMANAL","source_id":"CONAB",
                    "enabled":False,"collection_authorized":False}]}


def registros(valor=.35, horario=STAMP, pub=PUB, uf="MT"):
    rows = [{**RAW[0],"pct_semana_atual":valor,"uf":uf,
             "n_estados": 12 if uf == "MEDIA_ESTADOS" else None,
             "cobertura_area_pct": 0.8 if uf == "MEDIA_ESTADOS" else None}]
    return normalizar_progresso(rows,fonte_url=URL,
                                coletado_em=datetime.fromisoformat(horario),
                                publicado_em=pub)


class TestConciliacaoStores(unittest.TestCase):
    def setUp(self):
        self.legacy = abrir_progresso()
        self.canonical = abrir_registro()
        self.addCleanup(self.legacy.close)
        self.addCleanup(self.canonical.close)

    def legacy_ingest(self, rows=None):
        gravar_progresso(self.legacy,rows if rows is not None else registros(),
                        evidence_id="FICTICIO_TESTE_NAO_AUTORIZA",direitos_confirmados=True)

    def canonical_ingest(self, rows=None, raw=b"conteudo-bruto-ficticio", horario=STAMP):
        rows = rows if rows is not None else registros(horario=horario)
        registrar_progresso_local(
            self.canonical,CAT,registros=rows,
            sha256_origem=hashlib.sha256(raw).hexdigest(),
            bytes_origem=len(raw),mime_origem="text/plain",coletado_em=horario)

    def run_audit(self, at="2026-10-22T00:00:00Z", pub=None):
        return conciliar_stores_conab(
            self.legacy,self.canonical,corte_coleta=at,corte_publicacao=pub)

    def test_ambos_vazios_nao_inventam_coleta(self):
        result=self.run_audit()
        self.assertEqual(result["estado"],
                         "SEM_REGISTROS_NO_RECORTE_NAO_EQUIVALE_A_ZERO_NA_FONTE")
        self.assertEqual(result["linhas_legado_comparadas"],0)
        self.assertEqual(result["linhas_canonico_comparadas"],0)
        self.assertFalse(result["migration_allowed"])

    def test_valores_equivalentes_sem_provar_mesmo_raw(self):
        self.legacy_ingest()
        self.canonical_ingest()
        result=self.run_audit()
        self.assertEqual(result["contagem_por_situacao"],
                         {"VALORES_IGUAIS_NA_MESMA_CAPTURA_SEM_PROVA_RAW":1})
        self.assertEqual(result["linhas_legado_comparadas"],1)
        self.assertEqual(result["linhas_canonico_comparadas"],1)
        self.assertNotEqual(result["hashes_diferentes_semanticas"][
            "progresso_edicoes.sha256_json"],
            result["hashes_diferentes_semanticas"]["nivon_snapshots.sha256"])
        self.assertFalse(result["origem_raw_comprovada"])
        self.assertFalse(result["publicacao_autorizada"])

    def test_valores_diferentes_bloqueiam_conciliacao(self):
        self.legacy_ingest()
        self.canonical_ingest(rows=registros(valor=.40))
        result=self.run_audit()
        self.assertEqual(result["contagem_por_situacao"],
                         {"DIVERGENCIA_VALORES_MESMA_CAPTURA":1})
        self.assertEqual(result["estado"],"BLOQUEADO_DIVERGENCIA_SEMANTICA")

    def test_somente_legado_nao_conta_como_canonico(self):
        self.legacy_ingest()
        result=self.run_audit()
        self.assertEqual(result["contagem_por_situacao"],
                         {"SOMENTE_LEGADO_NESTA_CAPTURA":1})
        self.assertFalse(result["migration_allowed"])

    def test_somente_canonico_nao_conta_como_legado(self):
        self.canonical_ingest()
        result=self.run_audit()
        self.assertEqual(result["contagem_por_situacao"],
                         {"SOMENTE_CANONICO_NESTA_CAPTURA":1})

    def test_mesma_chave_coletas_diferentes_nao_vira_conflito_de_dados(self):
        self.legacy_ingest()
        horario="2026-10-20T15:00:00+00:00"
        self.canonical_ingest(rows=registros(valor=.40,horario=horario),
                              horario=horario)
        result=self.run_audit()
        self.assertEqual(result["estado"],
                         "SEM_CAPTURAS_PAREADAS_HISTORICO_NAO_CONCILIADO")
        self.assertTrue(result["mesmas_chaves_sem_mesma_captura"])
        self.assertEqual(result["contagem_por_situacao"]["SOMENTE_LEGADO_NESTA_CAPTURA"],1)
        self.assertEqual(result["contagem_por_situacao"]["SOMENTE_CANONICO_NESTA_CAPTURA"],1)

    def test_coleta_apos_corte_nao_vaza(self):
        self.legacy_ingest()
        self.canonical_ingest()
        result=self.run_audit(at="2026-10-20T12:00:00Z")
        self.assertEqual(result["linhas_canonico_comparadas"],0)
        self.assertEqual(result["excluidas_legado"],{"APOS_CORTE_COLETA":1})

    def test_publicacao_ausente_nao_vaza_em_backtest(self):
        rows=registros(pub=None)
        self.legacy_ingest(rows)
        self.canonical_ingest(rows=rows)
        result=self.run_audit(pub="2026-10-20T18:00:00Z")
        self.assertEqual(result["linhas_canonico_comparadas"],0)
        self.assertEqual(result["excluidas_legado"],
                         {"SEM_PUBLICACAO_COMPROVADA_ATE_CORTE":1})
        self.assertFalse(result["migration_allowed"])

    def test_publicacao_apenas_apos_corte_bloqueia(self):
        rows=registros(pub="2026-10-20T12:00:00+00:00")
        self.legacy_ingest(rows)
        self.canonical_ingest(rows=rows)
        result=self.run_audit(pub="2026-10-19T16:00:00Z")
        self.assertEqual(result["linhas_legado_comparadas"],0)
        self.assertEqual(result["linhas_canonico_comparadas"],0)

    def test_corte_publicacao_valido_com_mesma_hora(self):
        self.legacy_ingest()
        self.canonical_ingest()
        result=self.run_audit(pub="2026-10-19T12:00:00Z")
        self.assertEqual(result["linhas_legado_comparadas"],1)

    def test_uf_media_nao_se_confunde_com_mt(self):
        self.legacy_ingest(registros(uf="MEDIA_ESTADOS"))
        self.canonical_ingest(registros(),raw=b"outra-fixture")
        result=self.run_audit()
        self.assertEqual(result["contagem_por_situacao"]["SOMENTE_LEGADO_NESTA_CAPTURA"],1)
        self.assertEqual(result["contagem_por_situacao"]["SOMENTE_CANONICO_NESTA_CAPTURA"],1)

    def test_duplicacao_interna_de_edicoes_mesma_captura_bloqueada(self):
        self.legacy_ingest()
        self.legacy_ingest(registros(valor=.40))
        with self.assertRaises(ErroConciliacaoConab):
            self.run_audit()

    def test_tipo_real_declarado_em_db_nao_autoriza_migracao(self):
        self.canonical_ingest()
        self.canonical.execute(
            "UPDATE nivon_snapshots SET tipo='REAL_AUTORIZADO'")
        self.legacy_ingest()
        result=self.run_audit()
        self.assertFalse(result["migration_allowed"])
        self.assertFalse(result["origem_raw_comprovada"])

    def test_corromper_json_canônico_falha_fechado(self):
        self.canonical_ingest()
        self.canonical.execute("UPDATE nivon_conab_progresso SET observacao_json='{}'")
        with self.assertRaises(ErroConciliacaoConab):
            self.run_audit()

    def test_corromper_chave_canonica_falha_fechado(self):
        self.canonical_ingest()
        self.canonical.execute("UPDATE nivon_conab_progresso SET chave='[]'")
        with self.assertRaises(ErroConciliacaoConab):
            self.run_audit()

    def test_snapshot_canonico_de_outra_fonte_falha_fechado(self):
        self.canonical_ingest()
        self.canonical.execute("UPDATE nivon_snapshots SET fonte_id='ANP'")
        with self.assertRaises(ErroConciliacaoConab):
            self.run_audit()

    def test_nao_aceita_qualquer_schema(self):
        other=sqlite3.connect(":memory:")
        self.addCleanup(other.close)
        with self.assertRaises(ErroConciliacaoConab):
            conciliar_stores_conab(other,self.canonical,
                                   corte_coleta="2026-10-21T00:00:00Z")

    def test_recusa_timestamp_sem_fuso(self):
        with self.assertRaises(ErroConciliacaoConab):
            self.run_audit(at="2026-10-21T00:00:00")

    def test_limite_e_boleano_invalido(self):
        with self.assertRaises(ErroConciliacaoConab):
            conciliar_stores_conab(self.legacy,self.canonical,
                                   corte_coleta="2026-10-21T00:00:00Z",limite=True)

    def test_rejeita_linha_com_numerico_nao_finito(self):
        self.canonical_ingest()
        raw=self.canonical.execute(
            "SELECT observacao_json FROM nivon_conab_progresso").fetchone()[0]
        obj=json.loads(raw)
        obj["pct_semana_atual"]=float("nan")
        self.canonical.execute("UPDATE nivon_conab_progresso SET observacao_json=?",
                               (json.dumps(obj),))
        with self.assertRaises(ErroConciliacaoConab):
            self.run_audit()

    def test_cli_never_creates_missing_db(self):
        with tempfile.TemporaryDirectory() as d:
            x=Path(d)/"legado.db"
            y=Path(d)/"canonico.db"
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(["--legado",str(x),"--canonico",str(y),
                      "--corte-coleta","2026-10-20T00:00:00Z"])
            self.assertFalse(x.exists())
            self.assertFalse(y.exists())

    def test_cli_read_only_and_no_dump(self):
        with tempfile.TemporaryDirectory() as d:
            x=Path(d)/"legado.db"
            y=Path(d)/"canonico.db"
            a=abrir_progresso(x)
            b=abrir_registro(y)
            a.close()
            from nivon.progresso_conab_historico import preparar_esquema
            preparar_esquema(b)
            b.close()
            start=(x.stat().st_size,y.stat().st_size)
            out=io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--legado",str(x),"--canonico",str(y),
                    "--corte-coleta","2026-10-20T00:00:00Z","--resumo"]),0)
            obj=json.loads(out.getvalue())
            self.assertFalse(obj["migration_allowed"])
            self.assertEqual(start,(x.stat().st_size,y.stat().st_size))


if __name__=="__main__":
    unittest.main()
