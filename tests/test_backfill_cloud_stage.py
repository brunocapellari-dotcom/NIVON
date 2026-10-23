"""Regressão orchestration: backfill persiste o recibo GCS antes do MERGE."""
import unittest
from unittest.mock import patch

from scripts import backfill_fontes_cloud as mod


class TestBackfillRecuperavel(unittest.TestCase):
    def test_historico_arquiva_stage_antes_de_bigquery(self):
        eventos=[]

        def arquivar_raw(**kwargs):
            eventos.append("raw")
            return {"executado":True}

        def exportar(**kwargs):
            eventos.append("jsonl")
            return {"observacoes":1,"arquivo":str(kwargs["destino"])}

        def arquivar_stage(**kwargs):
            eventos.append("manifesto")
            self.assertTrue(kwargs["executar"])
            return {"manifesto_sha256":"b"*64}

        def carregar(**kwargs):
            eventos.append("merge")
            self.assertTrue(kwargs["executar"])
            return {"executado":True,"linhas_enviadas":1}

        with (
            patch.object(mod,"planejar_historico",return_value=[2026]),
            patch.object(mod,"verificar_nuvem",return_value={"tabela_validada":True}),
            patch.object(mod,"backfill",return_value={
                "lotes":[{"ano":2026,"estado":"RECEBIDO"}],"falhas":[]}),
            patch.object(mod,"arquivar_gcs",side_effect=arquivar_raw),
            patch.object(mod,"exportar_jsonl",side_effect=exportar),
            patch.object(mod,"arquivar_stage",side_effect=arquivar_stage),
            patch.object(mod,"executar_carga",side_effect=carregar),
        ):
            result=mod.executar_historico(
                fonte="BR_CCEE_PLD",inicio=2026,fim=2026,
                projeto="nivon-data",dataset="agro",bucket="nivon-raw-archive",
                executar=True)
        self.assertEqual(eventos,["raw","jsonl","manifesto","merge"])
        self.assertEqual(result["estado"],"CONCLUIDO")
        self.assertEqual(result["cargas_bigquery"][0]["manifesto_sha256"],"b"*64)

    def test_modo_planejamento_nao_consulta_gcp(self):
        with (patch.object(mod,"planejar_historico",return_value=[2026]),
              patch.object(mod,"verificar_nuvem",side_effect=AssertionError("Cloud foi acessado"))):
            result=mod.executar_historico(
                fonte="BR_CCEE_PLD",inicio=2026,fim=2026,
                projeto="nivon-data",dataset="agro",bucket="nivon-raw-archive")
        self.assertEqual(result["modo"],"SIMULACAO_SEM_REDE")

if __name__=="__main__":
    unittest.main()
