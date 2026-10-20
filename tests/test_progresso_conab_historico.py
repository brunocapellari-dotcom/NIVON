import hashlib
import sqlite3
import unittest
from datetime import datetime,timezone

from nivon.registro_snapshots import abrir_registro
from nivon.conab_agrobr import normalizar_progresso
from nivon.progresso_conab_historico import (
    registrar_progresso_local,consultar_progresso_asof,preparar_esquema,
    ErroProgressoHistorico)

CAT={"datasets":[{"id":"CONAB_PROGRESSO_SEMANAL","source_id":"CONAB",
                  "enabled":False,"collection_authorized":False}]}
T=datetime(2026,10,20,12,0,tzinfo=timezone.utc)
U="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra"
def normal(semana="2026-10-18",pct=.25,uf="MT",n=None):
    raw=[{"cultura":"Soja","safra":"2026/2027","operacao":"Semeadura",
          "uf":uf,"semana_atual":semana,"pct_semana_atual":pct,
          "pct_semana_anterior":.20,"pct_ano_anterior":.30,
          "pct_media_5_anos":.27,
          "n_estados":n,"cobertura_area_pct":.8 if n else None}]
    return normalizar_progresso(raw,fonte_url=U,coletado_em=T)
class TestProgressoConabStore(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro()
        self.addCleanup(self.db.close)
    def gravar(self,rows=None,sha=None,tempo="2026-10-20T12:00:00Z",**kw):
        if rows is None:
            # Nova aquisição da MESMA fonte, com novo timestamp de captura.
            rows=[dict(item,coleta=tempo.replace("Z","+00:00")) for item in normal()]
        sha=sha if sha is not None else hashlib.sha256(b"FONTE_SYNTH").hexdigest()
        return registrar_progresso_local(self.db,CAT,registros=rows,
            sha256_origem=sha,bytes_origem=800,mime_origem="text/plain",
            coletado_em=tempo,**kw)
    def visao(self,at="2026-10-21T00:00:00Z",uf="MT",sim=True):
        return consultar_progresso_asof(self.db,corte_coleta=at,
            cultura="Soja",safra="2026/2027",operacao="Semeadura",uf=uf,
            incluir_sinteticos=sim)
    def test_ingestao_e_asof(self):
        self.gravar()
        self.assertEqual(self.visao()["semanas"][0]["dados"]["pct_semana_atual"],.25)
        self.assertEqual(self.visao(at="2026-10-19T00:00:00Z")["semanas"],[])
    def test_repeticao_sem_novo_snapshot(self):
        self.gravar()
        r=self.gravar(tempo="2026-10-20T14:00:00Z")
        self.assertFalse(r["nova_versao"])
        self.assertTrue(r["nova_coleta"])
    def test_revisionamento_preserva_semana_anterior(self):
        self.gravar()
        r=normal(pct=.35)
        r[0]["coleta"]="2026-10-21T12:00:00+00:00"
        self.gravar(rows=r,sha=hashlib.sha256(b"versao2").hexdigest(),
                    tempo="2026-10-21T12:00:00Z")
        self.assertEqual(self.visao(at="2026-10-20T18:00:00Z")["semanas"][0]["dados"]["pct_semana_atual"],.25)
        self.assertEqual(self.visao(at="2026-10-22T00:00:00Z")["semanas"][0]["dados"]["pct_semana_atual"],.35)
    def test_media_estados_nao_e_brasil(self):
        self.gravar(rows=normal(uf="MEDIA_ESTADOS",n=12))
        x=self.visao(uf="MEDIA_ESTADOS")
        self.assertTrue(x["media_estados_nao_e_brasil"])
        self.assertEqual(self.visao(uf="MT")["semanas"],[])
    def test_brasil_inferido_e_bloqueado(self):
        with self.assertRaises(ErroProgressoHistorico):self.gravar(rows=normal(uf="BR"))
    def test_real_desligado_no_catalogo(self):
        with self.assertRaises(PermissionError):
            self.gravar(tipo="REAL_AUTORIZADO",
                        autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                        evidencia_direitos="DOC-2026-001")
    def test_erro_de_insert_reverte_ledger(self):
        preparar_esquema(self.db)
        self.db.execute("""CREATE TRIGGER falha BEFORE INSERT ON nivon_conab_progresso
            BEGIN SELECT RAISE(ABORT,'falha sintética'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.gravar()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
    def test_mesmo_hash_dados_diferentes_nao_altera_coleta(self):
        self.gravar()
        with self.assertRaises(ErroProgressoHistorico):
            self.gravar(rows=normal(pct=.5),tempo="2026-10-20T14:00:00Z")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_coletas").fetchone()[0],1)
    def test_sintetico_excluido_padroes_operacionais(self):
        self.gravar()
        self.assertEqual(self.visao(sim=False)["semanas"],[])
