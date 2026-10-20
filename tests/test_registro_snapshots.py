import hashlib
import unittest

from nivon.registro_snapshots import (ErroSnapshot, abrir_registro,
                                     registrar_snapshot, visao_asof)

D = "IBGE_CODIGOS_MUNICIPIOS"
CAT = {"datasets": [{"id": D, "source_id": "IBGE"}]}


class TestRegistroSnapshots(unittest.TestCase):
    def setUp(self):
        self.db = abrir_registro()
        self.addCleanup(self.db.close)
        self.a = dict(dataset_id=D, sha256=hashlib.sha256(b"A").hexdigest(),
                      tamanho=100, mime="application/json", schema_versao="IBGE.1",
                      coletado_em="2026-10-19T12:00:00-04:00",
                      competencia="2026-10", referencia="2026-10-18",
                      publicacao="2026-10-18")

    def registrar(self, **kwargs):
        return registrar_snapshot(self.db, CAT, **(self.a | kwargs))

    def test_primeiro_snapshot_e_repeticao_idempotente(self):
        a = self.registrar()
        b = self.registrar()
        self.assertTrue(a["nova_versao"] and a["nova_coleta"])
        self.assertFalse(b["nova_versao"] or b["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_coletas").fetchone()[0],1)

    def test_mesma_versao_em_outro_horario_preservada(self):
        self.registrar()
        r=self.registrar(coletado_em="2026-10-20T00:00:00Z")
        self.assertFalse(r["nova_versao"])
        self.assertTrue(r["nova_coleta"])

    def test_edicao_nova_nao_sobrescreve_antiga(self):
        self.registrar()
        self.registrar(sha256=hashlib.sha256(b"B").hexdigest(), publicacao="2026-10-19")
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],2)

    def test_mesmo_hash_meta_diferente_e_conflito(self):
        self.registrar()
        with self.assertRaises(ErroSnapshot): self.registrar(publicacao="2026-10-17")
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],1)

    def test_asof_nao_vaza_revisao_futura(self):
        self.registrar()
        self.registrar(sha256=hashlib.sha256(b"B").hexdigest(), publicacao="2026-10-19",
                       coletado_em="2026-10-19T14:00:00-04:00")
        antigo=visao_asof(self.db,dataset_id=D,corte_coleta="2026-10-19T16:30:00Z",
                          corte_publicacao="2026-10-18")
        self.assertEqual(antigo["sha256"],self.a["sha256"])
        novo=visao_asof(self.db,dataset_id=D,corte_coleta="2026-10-19T19:00:00Z",
                          corte_publicacao="2026-10-19")
        self.assertNotEqual(antigo["sha256"],novo["sha256"])

    def test_publicacao_desconhecida_nao_entra_no_asof(self):
        self.registrar(publicacao=None)
        self.assertIsNone(visao_asof(self.db,dataset_id=D,corte_coleta="2026-10-20T00:00:00Z",
                                   corte_publicacao="2026-10-20"))

    def test_real_sem_direitos_rejeitado(self):
        with self.assertRaises(PermissionError): self.registrar(tipo="REAL_AUTORIZADO")
        self.assertEqual(self.db.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_real_com_autorizacao_documentada(self):
        r=self.registrar(tipo="REAL_AUTORIZADO",autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                         evidencia_direitos="DOC-2026-001")
        self.assertEqual(r["tipo"],"REAL_AUTORIZADO")

    def test_sintetico_nao_pode_se_disfarcar_de_licenciado(self):
        with self.assertRaises(ErroSnapshot):
            self.registrar(evidencia_direitos="DOC-2026-001")

    def test_payload_fora_dos_limites(self):
        for v in (-1,0,20_000_001,True):
            with self.assertRaises(ErroSnapshot):self.registrar(tamanho=v)
        with self.assertRaises(ErroSnapshot):self.registrar(sha256="abc")

    def test_dataset_nao_cadastrado_rejeitado(self):
        with self.assertRaises(ErroSnapshot): self.registrar(dataset_id="INVENTADO")

    def test_temporalidade_invalida(self):
        with self.assertRaises(ErroSnapshot):self.registrar(coletado_em="2026-10-19T12:00:00")
        with self.assertRaises(ErroSnapshot):self.registrar(publicacao="2026-10-20")

    def test_schema_inadequado(self):
        with self.assertRaises(ErroSnapshot):self.registrar(mime="text/html")
        with self.assertRaises(ErroSnapshot):self.registrar(schema_versao="../x")

    def test_limite_maior_restrito_a_conab_sicarm(self):
        cat={"datasets":[{"id":"CONAB_ARMAZENS_CAPACIDADE","source_id":"CONAB"}]}
        x=registrar_snapshot(
            self.db,cat,dataset_id="CONAB_ARMAZENS_CAPACIDADE",
            sha256=hashlib.sha256(b"SICARM").hexdigest(),
            tamanho=60_000_000,mime="text/plain",schema_versao="SICARM_header_v1",
            coletado_em="2026-10-19T12:00:00Z")
        self.assertTrue(x["nova_versao"])
        with self.assertRaises(ErroSnapshot):
            self.registrar(tamanho=60_000_000)
        with self.assertRaises(ErroSnapshot):
            registrar_snapshot(
                self.db,cat,dataset_id="CONAB_ARMAZENS_CAPACIDADE",
                sha256=hashlib.sha256(b"SICARM-2").hexdigest(),
                tamanho=120_000_001,mime="text/plain",schema_versao="SICARM_header_v1",
                coletado_em="2026-10-19T12:00:00Z")


    def test_limite_csv_mdic_apenas_para_metadados_dataset_especifico(self):
        for dataset in ("MDIC_COMEX_NCM","MDIC_COMEX_MUNICIPIO_SH4"):
            cat={"datasets":[{"id":dataset,"source_id":"MDIC"}]}
            result=registrar_snapshot(self.db,cat,dataset_id=dataset,
                sha256=hashlib.sha256(dataset.encode()).hexdigest(),
                tamanho=850_000_000,mime="text/csv",schema_versao="MDIC_ANUAL_1",
                coletado_em="2026-10-20T12:00:00Z")
            self.assertTrue(result["nova_versao"])
            with self.assertRaises(ErroSnapshot):
                registrar_snapshot(self.db,cat,dataset_id=dataset,
                    sha256=hashlib.sha256((dataset+"2").encode()).hexdigest(),
                    tamanho=1_500_000_001,mime="text/csv",schema_versao="MDIC_ANUAL_1",
                    coletado_em="2026-10-20T12:00:00Z")
        with self.assertRaises(ErroSnapshot):
            self.registrar(tamanho=850_000_000)

    def test_ledger_preserva_savepoint_de_transacao_externa(self):
        self.db.execute("SAVEPOINT teste_externo")
        self.registrar()
        self.db.execute("ROLLBACK TO SAVEPOINT teste_externo")
        self.db.execute("RELEASE SAVEPOINT teste_externo")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_coletas").fetchone()[0],0)
