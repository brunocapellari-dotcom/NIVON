import copy
import hashlib
import sqlite3
import unittest
from nivon.registro_snapshots import abrir_registro
from nivon.lineup_nacional import carregar_escopo
from nivon.lineup_historico import (guardar_edicao_lineup,edicao_lineup_asof,
                                   preparar_historico,ErroHistoricoPortos)

SCOPE=carregar_escopo()
CAT={"datasets":[{"id":"LINEUP_ITAQUI","source_id":"PORTOS",
                  "enabled":False,"collection_authorized":False}]}
URL="https://fonte.oficial.example/portos/itaqui"
def registro(ton=800,coleta="2026-10-20T12:00:00Z",status="PROGRAMADO",
             evid="LINEUP_INFORMADO"):
    return {"porto_id":"ITAQUI","navio":"SHIP TESTE","duv":"DUV-101",
      "lote_id":"LOTE-7","produto":"SOJA","situacao":status,
      "classe_evidencia":evid,"toneladas_programadas":ton,
      "toneladas_realizadas":None,"fonte_url":URL,
      "publicado_em":"2026-10-19T18:00:00Z","coletado_em":coleta}
class TestHistoricoLineup(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)
    def salvar(self,rows=None,coleta="2026-10-20T12:00:00Z",sha=None,**kw):
        rows=rows if rows is not None else [registro(coleta=coleta)]
        return guardar_edicao_lineup(self.db,CAT,SCOPE,porto_id="ITAQUI",
            registros=rows,sha256_origem=sha or hashlib.sha256(b"LINEUP_A").hexdigest(),
            bytes_origem=1000,mime_origem="application/pdf",
            coletado_em=coleta,**kw)
    def visao(self,coleta="2026-10-20T20:00:00Z",**kw):
        return edicao_lineup_asof(self.db,porto_id="ITAQUI",
                                  corte_coleta=coleta,incluir_sinteticos=True,**kw)
    def test_grava_uma_edicao_sem_falar_em_realizado(self):
        x=self.salvar()
        self.assertTrue(x["nova_versao"])
        r=self.visao()
        self.assertEqual(len(r["linhas"]),1)
        self.assertEqual(r["linhas"][0]["situacao"],"PROGRAMADO")
        self.assertFalse(r["evidencia_realizacao_validada"])
    def test_repetir_bytes_nova_coleta_mesma_edicao(self):
        self.salvar()
        x=self.salvar(coleta="2026-10-20T14:00:00Z")
        self.assertFalse(x["nova_versao"])
        self.assertTrue(x["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_lineup_linhas").fetchone()[0],1)
    def test_edicao_mais_nova_substitui_a_lista_antiga_no_asof(self):
        self.salvar()
        self.salvar(rows=[registro(ton=900,coleta="2026-10-21T08:00:00Z")],
                   coleta="2026-10-21T08:00:00Z",
                   sha=hashlib.sha256(b"LINEUP_B").hexdigest())
        old=self.visao(coleta="2026-10-20T20:00:00Z")
        new=self.visao(coleta="2026-10-21T09:00:00Z")
        self.assertEqual(old["linhas"][0]["toneladas_programadas"],800)
        self.assertEqual(new["linhas"][0]["toneladas_programadas"],900)
        self.assertEqual(len(new["linhas"]),1)
    def test_sha_igual_linhas_diferentes_rejeita_sem_nova_coleta(self):
        self.salvar()
        with self.assertRaises(ErroHistoricoPortos):
            self.salvar(rows=[registro(ton=900,coleta="2026-10-20T14:00:00Z")],
                       coleta="2026-10-20T14:00:00Z")
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_coletas").fetchone()[0],1)
    def test_real_sem_homologacao_bloqueado(self):
        with self.assertRaises(PermissionError):
            self.salvar(tipo="REAL_AUTORIZADO",
                autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                evidencia_direitos="DOC-2026-001")
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],0)
    def test_mock_documento_hash_verdadeiro_mas_nao_homologado(self):
        raw=b"%PDF-1.7\nFONTE FAKE, NAO VERIFICADA"
        x=guardar_edicao_lineup(self.db,CAT,SCOPE,porto_id="ITAQUI",
             registros=[registro()],sha256_origem=hashlib.sha256(raw).hexdigest(),
             bytes_origem=len(raw),mime_origem="application/pdf",
             coletado_em="2026-10-20T12:00:00Z",arquivo_origem=raw)
        self.assertTrue(x["hash_comprovado_por_bytes"])
        self.assertFalse(self.visao()["licenca_publicacao_homologada"])
    def test_mime_html_permitido_somente_lineup(self):
        html=b"<html><table><tr><td>SIMULADO</td></tr></table></html>"
        x=guardar_edicao_lineup(self.db,CAT,SCOPE,porto_id="ITAQUI",
             registros=[registro()],sha256_origem=hashlib.sha256(html).hexdigest(),
             bytes_origem=len(html),mime_origem="text/html",
             coletado_em="2026-10-20T12:00:00Z",arquivo_origem=html)
        self.assertTrue(x["hash_comprovado_por_bytes"])
    def test_pdf_adulterado_bloqueado(self):
        with self.assertRaises(ErroHistoricoPortos):
            self.salvar(arquivo_origem=b"%PDF-1.7")
    def test_erro_sqlite_reverte_ledger(self):
        preparar_historico(self.db)
        self.db.execute("""CREATE TRIGGER falha_lineup BEFORE INSERT ON nivon_lineup_linhas
                    BEGIN SELECT RAISE(ABORT,'falha simulada'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.salvar()
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],0)
    def test_sem_duv_nao_inventa_escala_realizada(self):
        r=registro()
        r["duv"]=None
        self.salvar(rows=[r])
        self.assertIsNone(self.visao()["linhas"][0]["duv"])
    def test_programacao_nao_pode_ser_realizacao(self):
        with self.assertRaises(Exception):
            self.salvar(rows=[registro(status="REALIZADO")])
    def test_sintetico_oculto_padrao(self):
        self.salvar()
        self.assertIsNone(edicao_lineup_asof(self.db,porto_id="ITAQUI",
           corte_coleta="2026-10-20T20:00:00Z"))

    def test_45_fontes_catalogadas_com_store_inativo(self):
        import json
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        cats=json.loads((root/"config/fontes_nivon_master.v1.json").read_text())
        routes=json.loads((root/"config/rotas_coleta.v1.json").read_text())
        dataset=[x for x in cats["datasets"] if x["id"].startswith("LINEUP_")]
        entries=[x for x in routes["entries"] if x["dataset_id"].startswith("LINEUP_")]
        self.assertEqual(len(dataset),45)
        self.assertEqual(len(entries),45)
        self.assertTrue(all("lineup_historico.py" in x["existing_module"]
             and not x["enabled"] and not x["collection_authorized"] for x in dataset))
        self.assertTrue(all("lineup_historico.py" in x["implementation_scope"]
             and not x["runtime_enabled"] and not x["scheduled_enabled"] for x in entries))
