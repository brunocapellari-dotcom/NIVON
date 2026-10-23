import hashlib
import json
import unittest

from nivon.pipeline_api_dados import (
    abrir_registro,ingerir_json_local,observar_asof_coleta,ErroIngestaoAPI
)
from nivon.sidra_pam import planejar_pam_1612
from nivon.ptax_plano import planejar_consultas_ptax

CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB"},
                 {"id":"IBGE_PAM","source_id":"IBGE"}]}

def ptaxplano():
    return planejar_consultas_ptax(moeda="USD",inicio="2026-10-01",fim="2026-10-02")[0]
def ptaxpayload(val=5.1):
    return json.dumps({"value":[
        {"cotacaoCompra":val,"cotacaoVenda":val+0.02,
         "dataHoraCotacao":"2026-10-01 13:03:00"}]}).encode()
def pamplano():
    return planejar_pam_1612(municipio_ibge="5107925",ano=2024,
                            codigo_variavel="214",codigo_produto_c81="2702")
def pampayload():
    return json.dumps([
      {"D1C":"Município (Código)","D2C":"Variável (Código)",
       "D3C":"Ano (Código)","D4C":"Produto das lavouras temporárias (Código)",
       "MN":"Unidade de Medida","V":"Valor"},
      {"D1C":"5107925","D2C":"214","D3C":"2024","D4C":"2702",
       "MN":"Toneladas","V":"25"}
    ]).encode()

class TestPipelineOficialJSON(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def gravar(self,dataset_id="BCB_PTAX",payload=None,plano=None,coleta="2026-10-19T12:00:00Z",**extras):
        return ingerir_json_local(self.db,CAT,dataset_id=dataset_id,
                   payload=payload if payload is not None else ptaxpayload(),
                   plano=plano if plano is not None else ptaxplano(),
                   coletado_em=coleta,**extras)

    def test_ptax_grava_linhas_e_hash_sem_raw(self):
        r=self.gravar()
        self.assertEqual(r["linhas"],1)
        self.assertEqual(r["sha256"],hashlib.sha256(ptaxpayload()).hexdigest())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_observacoes_api").fetchone()[0],1)
        x=observar_asof_coleta(self.db,dataset_id="BCB_PTAX",
            corte_coleta="2026-10-19T12:00:00Z",incluir_sinteticos=True)
        self.assertEqual(x["registros"][0]["observacao"]["cotacao_compra_brl_por_moeda"],5.1)
        self.assertFalse(x["apto_backtest_por_publicacao"])

    def test_same_payload_second_collect_idempotent(self):
        self.gravar()
        again=self.gravar(coleta="2026-10-19T18:00:00Z")
        self.assertFalse(again["nova_versao"])
        self.assertTrue(again["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_observacoes_api").fetchone()[0],1)

    def test_real_requires_documented_rights(self):
        with self.assertRaises(PermissionError):
            self.gravar(tipo="REAL_AUTORIZADO")
        with self.assertRaises(PermissionError):
            self.gravar(tipo="REAL_AUTORIZADO",
                autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                evidencia_direitos="DOC-2026-001")
        # Catálogo real continua OFF; testar o caminho de aprovação
        # somente em catálogo isolado e sintético desta unidade de teste.
        fixture_cat={"datasets":[{"id":"BCB_PTAX","source_id":"BCB",
                                   "enabled":True,"collection_authorized":True}]}
        ok=ingerir_json_local(self.db,fixture_cat,dataset_id="BCB_PTAX",
                payload=ptaxpayload(),plano=ptaxplano(),
                coletado_em="2026-10-19T12:00:00Z",
                tipo="REAL_AUTORIZADO",
                autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                evidencia_direitos="DOC-2026-001")
        self.assertTrue(ok["nova_versao"])
        x=observar_asof_coleta(self.db,dataset_id="BCB_PTAX",
              corte_coleta="2026-10-19T18:00:00Z")
        self.assertEqual(x["linhas"],1)

    def test_sinteticos_nao_sao_operacionais_default(self):
        self.gravar()
        x=observar_asof_coleta(self.db,dataset_id="BCB_PTAX",
            corte_coleta="2026-10-20T00:00:00Z")
        self.assertEqual(x["linhas"],0)

    def test_pam_guarda_sem_reinterpretar_unidade(self):
        r=self.gravar(dataset_id="IBGE_PAM",payload=pampayload(),plano=pamplano())
        self.assertEqual(r["linhas"],1)
        x=observar_asof_coleta(self.db,dataset_id="IBGE_PAM",
           corte_coleta="2026-10-19T13:00:00Z",incluir_sinteticos=True)
        item=x["registros"][0]["observacao"]
        self.assertEqual((item["ano_civil"],item["variavel_sidra"],item["unidade_original"]),(2024,"214","Toneladas"))

    def test_revisoes_nao_vazam_para_corte_passado(self):
        self.gravar()
        self.gravar(payload=ptaxpayload(5.3),coleta="2026-10-20T12:00:00Z")
        x=observar_asof_coleta(self.db,dataset_id="BCB_PTAX",
            corte_coleta="2026-10-19T18:00:00Z",incluir_sinteticos=True)
        self.assertEqual(x["registros"][0]["observacao"]["cotacao_compra_brl_por_moeda"],5.1)
        y=observar_asof_coleta(self.db,dataset_id="BCB_PTAX",
            corte_coleta="2026-10-20T18:00:00Z",incluir_sinteticos=True)
        self.assertEqual(y["registros"][0]["observacao"]["cotacao_compra_brl_por_moeda"],5.3)

    def test_duplicate_json_keys_blocked(self):
        bad=b'{"value":[],"value":[]}'
        with self.assertRaises(ErroIngestaoAPI):
            self.gravar(payload=bad)

    def test_html_waf_blocked(self):
        with self.assertRaises(ErroIngestaoAPI):
            self.gravar(payload=b"<html>access denied</html>")

    def test_sem_timestamp_na_coleta(self):
        with self.assertRaises(ErroIngestaoAPI):
            self.gravar(coleta="2026-10-19T12:00:00")

    def test_sem_paginacao_oculta(self):
        payload=b'{"value":[],"@odata.nextLink":"https://olinda.bcb.gov.br/next"}'
        with self.assertRaises(Exception):
            self.gravar(payload=payload)

    def test_plano_ptax_adulterado_bloqueado(self):
        plano=ptaxplano()
        plano["url"]="https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/INVENTADO"
        with self.assertRaises(ErroIngestaoAPI):
            self.gravar(plano=plano)

    def test_vintages_conflitantes_mesma_coleta_bloqueadas(self):
        self.gravar(payload=ptaxpayload(5.1))
        self.gravar(payload=ptaxpayload(5.3))
        with self.assertRaises(ErroIngestaoAPI):
            observar_asof_coleta(self.db,dataset_id="BCB_PTAX",
                corte_coleta="2026-10-19T12:00:00Z",incluir_sinteticos=True)

    def test_erro_de_insert_no_normalizado_reverte_proveniencia(self):
        import sqlite3
        from nivon.pipeline_api_dados import preparar_tabelas
        preparar_tabelas(self.db)
        self.db.execute("""CREATE TRIGGER falha_observacoes BEFORE INSERT ON nivon_observacoes_api
                           BEGIN SELECT RAISE(ABORT,'falha sintética de armazenamento'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.gravar()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_coletas").fetchone()[0],0)

    def test_rollback_json_nao_revoga_transacao_externa(self):
        self.db.execute("CREATE TABLE testemunha (v INTEGER)")
        self.db.execute("SAVEPOINT externo")
        self.db.execute("INSERT INTO testemunha VALUES (123)")
        self.gravar()
        self.db.execute("ROLLBACK TO SAVEPOINT externo")
        self.db.execute("RELEASE SAVEPOINT externo")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM testemunha").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
