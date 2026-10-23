"""R13: prova de frescor, RAW imutável e quarantine para CEPEA/IMEA/CONAB."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.auditoria_frescor_agro import auditar_fontes_agro, ErroFrescorAgro
from nivon.ingestao_fontes_reais import gravar_lote
from nivon.cepea_web_primario import consultar_pagina_primaria, URL_SOJA
from nivon.maritimo_pipeline import baixar_html

NOW=datetime(2026,10,23,18,tzinfo=timezone.utc)
DATASET="CEPEA_PRECOS_FISICOS"


class TestAuditoriaFrescorR13(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/"fontes.sqlite"
        self.raw=self.root/"raw"

    def store(self,dataset=DATASET,estado="NORMALIZED",
              coletado="2026-10-23T16:00:00+00:00",
              referencia="2026-10-22"):
        payload=("{\"teste\":\"R13 sintético\",\"ds\":\""+dataset+"\"}").encode()
        return gravar_lote(
            banco=self.db,diretorio_bruto=self.raw,
            dataset_id=dataset,origem="https://www.cepea.org.br/br/indicador/soja.aspx",
            raw=payload,tipo="application/json",
            coletado_em=coletado,estado=estado,
            registros=[{"identidade":"soja_paranagua|"+referencia,
                        "referencia":referencia,"natureza":"INFORMADO",
                        "competencia":referencia[:7],"publicacao":None,
                        "valor":"150.00","unidade":"BRL/sc60kg",
                        "campos":{"origem":"SINTETICO","data_referencia":
                                  referencia if dataset==DATASET else None}}],
        )

    def audit(self):
        return auditar_fontes_agro(banco=self.db,agora=NOW,diretorio_raw=self.raw)

    def test_egress_cepea_e_maritimo_bloqueados_sem_gateway(self):
        with self.assertRaisesRegex(PermissionError,"EGRESS_CEPEA_NAO_HOMOLOGADO"):
            consultar_pagina_primaria(URL_SOJA)
        with self.assertRaisesRegex(PermissionError,"EGRESS_MARITIMO_NAO_HOMOLOGADO"):
            baixar_html("suape",habilitar_rede=True)

    def test_sem_banco_nao_inventa_dado_ou_cria_sqlite(self):
        result=self.audit()
        self.assertEqual(result["estado"],"SEM_BANCO_LOCAL")
        self.assertEqual(result["datasets"][DATASET]["estado"],"SOURCE_LAG")
        self.assertFalse(self.db.exists())

    def test_cepea_raw_idempotente_recente_nao_se_torna_publicavel(self):
        self.store()
        x=self.audit()
        cepea=x["datasets"][DATASET]
        self.assertEqual(cepea["estado"],"CANDIDATO_RECENTE_SEM_LICENCA_HOMOLOGADA")
        self.assertEqual((cepea["snapshots"],cepea["observacoes"]),(1,1))
        self.assertTrue(cepea["raw_sha256_confere"])
        self.assertTrue(cepea["referencia_verificada"])
        self.assertFalse(cepea["publicavel"])
        self.assertFalse(x["persistencia_cloud_verificada"])
        self.assertNotIn("150.00",json.dumps(x))
        self.assertNotIn("soja_paranagua",json.dumps(x))

    def test_publicacao_imea_conab_nunca_promovida_como_referencia(self):
        for ds in ("IMEA_PUBLICACOES_STAGING","CONAB_SAFRAS_STAGING"):
            with self.subTest(dataset=ds):
                self.store(dataset=ds,estado="QUARANTINED")
        x=self.audit()
        for ds in ("IMEA_PUBLICACOES_STAGING","CONAB_SAFRAS_STAGING"):
            z=x["datasets"][ds]
            self.assertEqual(z["estado"],"QUARENTENA_NAO_PUBLICAVEL")
            self.assertFalse(z["referencia_verificada"])
            self.assertFalse(z["publicavel"])

    def test_frescor_de_coleta_nao_repara_referencia_antiga(self):
        self.store(referencia="2026-09-01")
        result=self.audit()["datasets"][DATASET]
        self.assertEqual(result["estado"],"REFERENCIA_DEFASADA_OU_FUTURA")
        self.assertTrue(result["coleta_recente"])
        self.assertFalse(result["referencia_verificada"])
        self.assertFalse(result["publicavel"])

    def test_recoleta_de_mesmo_raw_atualiza_frescor_sem_inventar_precos_novos(self):
        antigo=self.store(coletado="2026-10-11T12:00:00+00:00",
                          referencia="2026-10-10")
        self.assertEqual(self.audit()["datasets"][DATASET]["estado"],"SOURCE_LAG")
        novo=self.store(coletado="2026-10-23T16:00:00+00:00",
                        referencia="2026-10-10")
        self.assertEqual(antigo["snapshot_id"],novo["snapshot_id"])
        self.assertTrue(novo["captura_nova"])
        self.assertTrue(novo["snapshot_ja_existente"])
        self.assertEqual(novo["novas_observacoes"],0)
        again=self.store(coletado="2026-10-23T16:00:00+00:00",
                         referencia="2026-10-10")
        self.assertFalse(again["captura_nova"])
        z=self.audit()["datasets"][DATASET]
        self.assertEqual(z["snapshots"],1)
        self.assertEqual(z["observacoes"],1)
        self.assertEqual(z["capturas_verificadas"],2)
        self.assertTrue(z["coleta_recente"])
        self.assertEqual(z["estado"],"REFERENCIA_DEFASADA_OU_FUTURA")
        self.assertFalse(z["publicavel"])

    def test_coleta_antiga_e_sinal_lag(self):
        self.store(coletado="2026-10-11T12:00:00+00:00")
        self.assertEqual(self.audit()["datasets"][DATASET]["estado"],"SOURCE_LAG")

    def test_raw_adulterado_gera_alerta_sem_gravar_ou_promover(self):
        s=self.store()
        p=Path(s["arquivo_raw"])
        p.write_bytes(b"conteudo adulterado")
        x=self.audit()["datasets"][DATASET]
        self.assertFalse(x["raw_sha256_confere"])
        self.assertEqual(x["estado"],"RAW_NAO_VERIFICADO")
        self.assertFalse(x["publicavel"])

    def test_coleta_futura_nao_pode_ser_recente(self):
        self.store(coletado="2026-10-24T12:00:00+00:00")
        x=self.audit()["datasets"][DATASET]
        self.assertEqual(x["estado"],"COLETA_FUTURA_INCONSISTENTE")
        self.assertFalse(x["coleta_recente"])

if __name__=="__main__":
    unittest.main()
