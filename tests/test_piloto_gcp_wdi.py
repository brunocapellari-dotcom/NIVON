"""Contratos do piloto: sem rede por padrão, ordem RAW→manifesto→MERGE→leitura."""
import unittest
from nivon.piloto_gcp_wdi import executar_piloto, GATES, ErroPilotoGCP

GCP={"projeto":"nivon-data","dataset":"nivon_raw","bucket":"nivon-data-raw-2026"}

class PilotoWDITest(unittest.TestCase):
    def _mocks(self,**changes):
        calls=[]
        def preflight(**kw):
            calls.append("preflight")
            self.assertFalse(kw["criar_tabela"])
            return {"tabela_validada":True}
        def coletor(**kw):
            calls.append("http")
            self.assertEqual(kw["pais"],"BRA")
            self.assertEqual((kw["inicio"],kw["fim"]),(2024,2024))
            return {"estado":"NORMALIZED","novas_observacoes":1,
                    "total_observacoes_no_lote":1,"sha256":"a"*64}
        def exportador(**kw):
            calls.append("export")
            return {"observacoes":1,"arquivo":str(kw["destino"])}
        def raw(**kw):
            calls.append("gcs_raw")
            return {"executado":True,"objetos_verificados":1}
        def manifesto(**kw):
            calls.append("gcs_manifesto")
            return {"executado":True,"manifesto_sha256":"b"*64}
        def loader(**kw):
            calls.append("merge")
            self.assertTrue(kw["executar"])
            return {"executado":True,"linhas_enviadas":1}
        def verifier(**kw):
            calls.append("readback")
            return {"executado":True,"amostras_bigquery_confirmadas":1,
                    "objetos_gcs_confirmados":1}
        funcs={"preflight":preflight,"coletor":coletor,"exportador":exportador,
               "raw_uploader":raw,"stage_uploader":manifesto,
               "loader":loader,"verificador":verifier}
        funcs.update(changes)
        return calls,funcs

    def test_sem_executar_nao_acessa_nuvem(self):
        calls,functions=self._mocks()
        ret=executar_piloto(**GCP,**functions)
        self.assertFalse(ret["executado"])
        self.assertEqual(calls,[])

    def test_gates_ausentes_bloqueiam_antes_de_http(self):
        calls,functions=self._mocks()
        for missing in GATES:
            env={name:"true" for name in GATES if name!=missing}
            with self.subTest(missing=missing),self.assertRaises(PermissionError):
                executar_piloto(**GCP,executar=True,env=env,**functions)
        self.assertEqual(calls,[])

    def test_integracao_respeita_ordenacao_e_marcadores(self):
        calls,functions=self._mocks()
        result=executar_piloto(**GCP,executar=True,
            env={k:"true" for k in GATES},**functions)
        self.assertEqual(calls,["preflight","http","export","gcs_raw",
                                "gcs_manifesto","merge","readback"])
        self.assertTrue(result["gcs_confirmado"])
        self.assertTrue(result["bigquery_confirmado"])
        self.assertEqual(result["observacoes_reais"],1)
        self.assertFalse(result["dados_publicados_externamente"])
        self.assertTrue(result["nao_autoriza_coletas_amplas"])

    def test_resposta_incompleta_impede_arquivamento(self):
        calls,functions=self._mocks(coletor=lambda **kw:{
            "estado":"RAW_RECEIVED","novas_observacoes":0,
            "total_observacoes_no_lote":0})
        with self.assertRaises(ErroPilotoGCP):
            executar_piloto(**GCP,executar=True,
                env={k:"true" for k in GATES},**functions)
        self.assertEqual(calls,["preflight"])

    def test_falha_raw_gcs_bloqueia_bigquery(self):
        calls,functions=self._mocks(raw_uploader=lambda **kw:{
            "executado":False,"objetos_verificados":0})
        with self.assertRaises(ErroPilotoGCP):
            executar_piloto(**GCP,executar=True,
                env={k:"true" for k in GATES},**functions)
        self.assertEqual(calls,["preflight","http","export"])

    def test_falha_manifesto_gcs_bloqueia_merge(self):
        calls,functions=self._mocks(stage_uploader=lambda **kw:{
            "executado":False})
        with self.assertRaises(ErroPilotoGCP):
            executar_piloto(**GCP,executar=True,
                env={k:"true" for k in GATES},**functions)
        self.assertEqual(calls,["preflight","http","export","gcs_raw"])

    def test_readback_incompleto_reprova_execucao(self):
        calls,functions=self._mocks(verificador=lambda **kw:{
            "executado":True,"amostras_bigquery_confirmadas":0,
            "objetos_gcs_confirmados":1})
        with self.assertRaises(ErroPilotoGCP):
            executar_piloto(**GCP,executar=True,
                env={k:"true" for k in GATES},**functions)
        self.assertEqual(calls[-2:],["merge"])

if __name__=="__main__":
    unittest.main()
