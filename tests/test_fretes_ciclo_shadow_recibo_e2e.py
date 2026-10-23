"""Integração E2E offline: SQLite de ofertas -> shadow -> ledger -> recibo.

Sem chaves, timestamps ou canais reais. Inclui falha após COMMIT,
duplicação por dia e recuperação manual do recibo.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.fretes_ciclo_shadow import (
    ErroCicloShadowFrete, executar_ciclo_shadow_frete_local,
)
from nivon.fretes_recibos_ancora import (
    ErroReciboFrete, criar_recibo_local_frete,
    verificar_recibo_local_frete, auditar_ledger_frete_com_recibo,
    salvar_recibo_em_diretorio_local,
)
from nivon.fretes_ofertas_store import (
    GENESIS as STORE_GENESIS, inicializar_store_ofertas_frete,
    anexar_lote_ofertas_frete, verificar_store_ofertas_frete,
)
from nivon.fretes_ledger_persistente import (
    GENESIS as LEDGER_GENESIS, inicializar_ledger_frete,
    verificar_ledger_frete, avaliar_ledger_frete,
)
from nivon.fretes_baseline_shadow import MODELO_BASELINE_ZERO
from test_fretes_previsoes_arquivadas import (
    BASE, KEY, SOURCE, PARAMS, CUTOFF, historico,
)
from test_fretes_ofertas_store import evidencias
from test_fretes_recibos_gcs_contrato import BucketFalso

RECIBO_KEY=b"only-fixture-independent-receipt-key-20261023"
RECIBO_EMISSOR="fixture-anchor-signer"


class TestCicloShadowComRecibo(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.receipts=self.root/"recibos"
        self.receipts.mkdir(mode=0o700)
        self.receipts.chmod(0o700)
        self.filename=self.root/"fretes.sqlite"
        self.db=sqlite3.connect(self.filename)
        self.addCleanup(self.db.close)
        inicializar_store_ofertas_frete(self.db)
        inicializar_ledger_frete(self.db)
        self.dia=BASE+timedelta(days=8)
        self.now=datetime(
            self.dia.year,self.dia.month,self.dia.day,16,
            tzinfo=timezone.utc,
        )
        self.rows=[
            x for x in historico(110)
            if x.data_coleta<=self.now
        ]
        self.store=anexar_lote_ofertas_frete(
            self.db,self.rows,evidencias=evidencias(self.rows),
            cabeca_anterior_sha256=STORE_GENESIS,
        )
        self.store_head=self.store["cabeca_sha256"]

    def ciclo(self, **overrides):
        params={
            "recebido_em":self.now,
            "cabeca_ofertas_esperada":self.store_head,
            "cabeca_previsoes_esperada":LEDGER_GENESIS,
            "condicoes":dict(PARAMS),
            "fonte_id":SOURCE,"emissor_previsao":"fixture-archive",
            "chave_previsao":KEY,
            "emissor_recibo":RECIBO_EMISSOR,
            "chave_recibo":RECIBO_KEY,
            "diretorio_recibos":self.receipts,
        }
        params.update(overrides)
        return executar_ciclo_shadow_frete_local(self.db,**params)

    def ler_recibo(self, caminho):
        return json.loads(Path(caminho).read_text(encoding="utf-8"))

    def test_ciclo_emite_assina_local_grava_tres_e_produz_recibo(self):
        r=self.ciclo()
        self.assertEqual(r["previsoes_gravadas"],3)
        self.assertEqual(r["previsoes_total"],3)
        self.assertTrue(r["recibo_local_emitido"])
        self.assertFalse(r["previsoes_assinadas_por_servico_independente"])
        self.assertFalse(r["timestamp_independente_comprovado"])
        self.assertFalse(r["publicavel"])
        self.assertNotEqual(r["previsoes_cabeca_sha256"],LEDGER_GENESIS)
        recibo=self.ler_recibo(r["recibo_local_caminho"])
        audit=auditar_ledger_frete_com_recibo(
            self.db,recibo,chave_recibo=RECIBO_KEY,
            as_of=self.now+timedelta(seconds=1),
            emissor_recibo=RECIBO_EMISSOR,
            chave_previsao=KEY,emissor_previsao="fixture-archive",
        )
        self.assertEqual(audit["status"],"RECIBO_E_LEDGER_CONFERIDOS_LOCALMENTE")
        self.assertEqual(audit["sequencia"],3)
        self.assertFalse(audit["armazenamento_remoto_worm_comprovado"])
        p=verificar_ledger_frete(
            self.db,cabeca_esperada_sha256=r["previsoes_cabeca_sha256"],
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )
        self.assertEqual(len(p["previsoes"]),3)
        self.assertEqual(
            {x["horizonte_dias_corridos"] for x in p["previsoes"]},
            {7,30,90},
        )
        self.assertTrue(all(x["delta_previsto_brl_t"]=="0" for x in p["previsoes"]))
        self.assertTrue(all(x["data_origem"]==self.dia.isoformat()
                            for x in p["previsoes"]))

    def test_mesma_origem_rota_nao_reemite_previsao(self):
        first=self.ciclo()
        with self.assertRaisesRegex(ErroCicloShadowFrete,"já foi emitida"):
            self.ciclo(
                recebido_em=self.now+timedelta(seconds=1),
                cabeca_previsoes_esperada=first["previsoes_cabeca_sha256"],
            )
        self.assertEqual(verificar_ledger_frete(
            self.db,cabeca_esperada_sha256=first["previsoes_cabeca_sha256"],
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )["quantidade"],3)

    def test_cabeca_store_adulterada_impede_ciclo(self):
        with self.assertRaisesRegex(ValueError,"cabeça"):
            self.ciclo(cabeca_ofertas_esperada=STORE_GENESIS)
        self.assertEqual(verificar_ledger_frete(
            self.db,cabeca_esperada_sha256=LEDGER_GENESIS,
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )["quantidade"],0)

    def test_recibo_adulterado_hmac_bloqueia_verificacao(self):
        result=self.ciclo()
        receipt=self.ler_recibo(result["recibo_local_caminho"])
        receipt["sequencia"]=4
        with self.assertRaisesRegex(ErroReciboFrete,"MAC inválido"):
            auditar_ledger_frete_com_recibo(
                self.db,receipt,chave_recibo=RECIBO_KEY,
                as_of=self.now+timedelta(minutes=1),
                emissor_recibo=RECIBO_EMISSOR,
                chave_previsao=KEY,emissor_previsao="fixture-archive",
            )

    def test_recibo_futuro_rejeitado_por_corte(self):
        r=self.ciclo()
        receipt=self.ler_recibo(r["recibo_local_caminho"])
        with self.assertRaisesRegex(ErroReciboFrete,"posterior ao corte"):
            verificar_recibo_local_frete(
                receipt,chave_recibo=RECIBO_KEY,
                as_of=self.now-timedelta(seconds=1),
                tipo_esperado="PREVISOES",emissor_esperado=RECIBO_EMISSOR,
            )

    def test_falha_de_diretorio_apos_commit_devolve_cabeca_recuperavel(self):
        r=self.ciclo(diretorio_recibos=self.root/"inexistente")
        self.assertEqual(r["status"],"PREVISOES_GRAVADAS_SEM_RECIBO_LOCAL")
        self.assertFalse(r["recibo_local_emitido"])
        self.assertTrue(r["recuperacao_necessaria"])
        self.assertEqual(verificar_ledger_frete(
            self.db,cabeca_esperada_sha256=r["previsoes_cabeca_sha256"],
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )["quantidade"],3)
        # Recuperação NÃO pode retroagir tempo; recibo é emitido agora no
        # runtime simulado e continua classificado como testemunha local.
        receipt=criar_recibo_local_frete(
            tipo_ledger="PREVISOES",emissor_id=RECIBO_EMISSOR,
            cabeca_sha256=r["previsoes_cabeca_sha256"],sequencia=3,
            assinado_em=self.now+timedelta(minutes=1),chave_recibo=RECIBO_KEY,
        )
        info=salvar_recibo_em_diretorio_local(
            receipt,diretorio_privado=self.receipts,
        )
        audit=auditar_ledger_frete_com_recibo(
            self.db,receipt,chave_recibo=RECIBO_KEY,
            as_of=self.now+timedelta(minutes=2),
            emissor_recibo=RECIBO_EMISSOR,
            chave_previsao=KEY,emissor_previsao="fixture-archive",
        )
        self.assertEqual(audit["sequencia"],3)
        self.assertFalse(info["armazenamento_independente_comprovado"])

    def test_mesma_chave_para_previsao_e_recibo_bloqueia(self):
        with self.assertRaisesRegex(ErroCicloShadowFrete,"distintas"):
            self.ciclo(chave_recibo=KEY)

    def test_recibo_nao_sobrescreve_arquivo_exclusivo(self):
        r=self.ciclo()
        receipt=self.ler_recibo(r["recibo_local_caminho"])
        with self.assertRaisesRegex(ErroReciboFrete,"persistir"):
            salvar_recibo_em_diretorio_local(
                receipt,diretorio_privado=self.receipts,
            )
        self.assertEqual(len(list(self.receipts.glob("*.json"))),1)

    def test_dados_futuros_no_store_impedem_falsa_emissao_pit(self):
        # Inserção com prova de dia seguinte em teste, para comprovar
        # bloqueio de emissão retroativa e não downgrade silencioso.
        from nivon.fretes_ofertas_store import anexar_lote_ofertas_frete
        futuro=next(x for x in historico(110)
                    if x.data_referencia==self.dia+timedelta(days=1))
        nova=anexar_lote_ofertas_frete(
            self.db,[futuro],evidencias=evidencias([futuro]),
            cabeca_anterior_sha256=self.store_head,
        )
        with self.assertRaisesRegex(ErroCicloShadowFrete,"posteriores"):
            self.ciclo(cabeca_ofertas_esperada=nova["cabeca_sha256"])

    def test_gcs_desligado_nao_chama_bucket(self):
        bucket=BucketFalso()
        r=self.ciclo(bucket_recibo_gcs=bucket)
        self.assertFalse(r["gcs_upload_executado"])
        self.assertFalse(bucket.uploads)
        self.assertTrue(r["recibo_local_emitido"])

    def test_ciclo_com_gcs_optin_chave_e_readback_exatos(self):
        bucket=BucketFalso()
        r=self.ciclo(
            bucket_recibo_gcs=bucket,autorizar_escrita_gcs=True,
        )
        self.assertEqual(r["status"],"SHADOW_LEDGER_GCS_READBACK_CONFERIDO")
        self.assertEqual(r["previsoes_gravadas"],3)
        self.assertEqual(r["gcs_generation"],1)
        self.assertTrue(r["gcs_upload_executado"])
        self.assertEqual(bucket.uploads[0]["if_generation_match"],0)
        self.assertFalse(r["retencao_worm_comprovada"])
        self.assertFalse(r["timestamp_independente_comprovado"])
        self.assertFalse(r["publicavel"])

    def test_gcs_readback_falhou_ledger_local_continua_integro(self):
        bucket=BucketFalso()
        bucket.forcar_divergencia=True
        r=self.ciclo(
            bucket_recibo_gcs=bucket,autorizar_escrita_gcs=True,
        )
        self.assertEqual(r["status"],"SHADOW_LEDGER_GRAVADO_GCS_NAO_CONFIRMADO")
        self.assertTrue(r["recuperacao_gcs_necessaria"])
        self.assertTrue(r["recibo_local_emitido"])
        self.assertFalse(r["gcs_upload_executado"])
        ledger=verificar_ledger_frete(
            self.db,cabeca_esperada_sha256=r["previsoes_cabeca_sha256"],
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )
        self.assertEqual(ledger["quantidade"],3)

    def test_recibo_local_nao_e_preditivo_ou_worm(self):
        r=self.ciclo()
        receipt=self.ler_recibo(r["recibo_local_caminho"])
        self.assertNotIn("frete_medio_municipio",str(receipt))
        self.assertFalse(r["armazenamento_recibo_cloud_worm"])
        self.assertFalse(r["previsao_homologada"])


if __name__=="__main__":
    unittest.main()
