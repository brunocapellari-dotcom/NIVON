"""Ponta a ponta: crash após commit -> checkpoint -> revalidar PIT -> recibo.

Fixtures sintéticas HMAC local, sem WORM/GCS real, sem forecasts reais.
"""
import json
import sqlite3
import unittest
from datetime import timedelta
from pathlib import Path

from nivon.fretes_recuperacao_poscommit import (
    ErroRecuperacaoFrete, recuperar_recibo_poscommit_frete,
)
from nivon.fretes_ledger_persistente import GENESIS, verificar_ledger_frete
from test_fretes_ciclo_shadow_recibo_e2e import (
    TestCicloShadowComRecibo, RECIBO_KEY, RECIBO_EMISSOR,
)
from test_fretes_previsoes_arquivadas import KEY, SOURCE, PARAMS


class TestRecuperacaoCrashFretesE2E(unittest.TestCase):
    def setUp(self):
        # Reutiliza o setup sintético da integração anterior, sem
        # herdar/duplicar todos os testes da classe existente.
        self.f = TestCicloShadowComRecibo("test_ciclo_emite_assina_local_grava_tres_e_produz_recibo")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def ciclo_sem_recibo(self):
        result=self.f.ciclo(diretorio_recibos=self.f.root/"nao-existe")
        self.assertEqual(result["status"],"PREVISOES_GRAVADAS_SEM_RECIBO_LOCAL")
        self.assertTrue(result["recuperacao_necessaria"])
        self.assertEqual(len(list(self.f.receipts.iterdir())),0)
        return result

    def recuperar(self, **kwargs):
        opts={
            "cabeca_previsoes_anterior_sha256":GENESIS,
            "quantidade_previsoes_anterior":0,
            "cabeca_ofertas_sha256":self.f.store_head,
            "condicoes":dict(PARAMS),
            "fonte_id":SOURCE, "emissor_previsao":"fixture-archive",
            "chave_previsao":KEY,"emissor_recibo":RECIBO_EMISSOR,
            "chave_recibo":RECIBO_KEY,
            "instante_recuperacao":self.f.now+timedelta(minutes=2),
            "diretorio_recibos":self.f.receipts,
        }
        opts.update(kwargs)
        return recuperar_recibo_poscommit_frete(self.f.db,**opts)

    def test_recupera_apos_commit_sem_regravar_previsoes(self):
        first=self.ciclo_sem_recibo()
        result=self.recuperar()
        self.assertEqual(
            result["status"],
            "RECIBO_RECUPERADO_LOCALMENTE_SEM_PROVA_TEMPORAL_EXTERNA",
        )
        self.assertEqual(result["total_previsoes"],3)
        self.assertEqual(result["cabeca_sha256"],first["previsoes_cabeca_sha256"])
        self.assertFalse(result["testemunha_independente"])
        self.assertFalse(result["armazenamento_worm_comprovado"])
        self.assertFalse(result["publicavel"])
        ver=verificar_ledger_frete(
            self.f.db,cabeca_esperada_sha256=result["cabeca_sha256"],
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )
        self.assertEqual(ver["quantidade"],3)
        self.assertEqual(len(list(self.f.receipts.glob("*.json"))),1)

    def test_rodar_duas_vezes_reusa_recibo_sem_regravar(self):
        self.ciclo_sem_recibo()
        a=self.recuperar()
        b=self.recuperar()
        self.assertEqual(b["status"],"RECIBO_JA_EXISTENTE_VALIDADO_LOCALMENTE")
        self.assertEqual(b["recibo_local_caminho"],a["recibo_local_caminho"])
        self.assertEqual(len(list(self.f.receipts.glob("*.json"))),1)
        self.assertFalse(b["recuperacao_do_ledger_reexecutada"])

    def test_recibo_original_valido_nao_e_duplicado(self):
        normal=self.f.ciclo()
        b=self.recuperar()
        self.assertEqual(b["status"],"RECIBO_JA_EXISTENTE_VALIDADO_LOCALMENTE")
        self.assertEqual(b["recibo_local_caminho"],normal["recibo_local_caminho"])
        self.assertEqual(len(list(self.f.receipts.glob("*.json"))),1)

    def test_head_prefix_stale_bloqueia(self):
        self.ciclo_sem_recibo()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"checkpoint"):
            self.recuperar(cabeca_previsoes_anterior_sha256="f"*64)
        self.assertEqual(len(list(self.f.receipts.iterdir())),0)

    def test_prefix_count_falso_bloqueia(self):
        self.ciclo_sem_recibo()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"quantidade"):
            self.recuperar(quantidade_previsoes_anterior=1)

    def test_recuperacao_outro_dia_nao_retrodata_recibo(self):
        self.ciclo_sem_recibo()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"tardia"):
            self.recuperar(
                instante_recuperacao=self.f.now+timedelta(days=1),
            )
        self.assertEqual(len(list(self.f.receipts.iterdir())),0)

    def test_cabeca_de_ofertas_nao_confiavel_recusa(self):
        self.ciclo_sem_recibo()
        with self.assertRaisesRegex(ValueError,"cabeça"):
            self.recuperar(cabeca_ofertas_sha256="0"*64)

    def test_atacante_apaga_ou_troca_conteudo_do_forecast_bloqueia(self):
        self.ciclo_sem_recibo()
        self.f.db.execute("DROP TRIGGER nivon_frete_previsoes_sem_update")
        self.f.db.execute(
            "UPDATE nivon_frete_previsoes_v1 SET previsao_json='{}' WHERE sequencia=2"
        )
        self.f.db.commit()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"HMAC|cadeia"):
            self.recuperar()
        self.assertEqual(len(list(self.f.receipts.iterdir())),0)

    def test_recibo_assinado_mas_adulterado_recusa_novo(self):
        self.ciclo_sem_recibo()
        ok=self.recuperar()
        p=Path(ok["recibo_local_caminho"])
        doc=json.loads(p.read_text())
        doc["sequencia"]=99
        p.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"adulterado"):
            self.recuperar()
        self.assertEqual(len(list(self.f.receipts.iterdir())),1)

    def test_emissao_incompleta_nao_emite_recibo(self):
        self.ciclo_sem_recibo()
        self.f.db.execute("DROP TRIGGER nivon_frete_previsoes_sem_delete")
        self.f.db.execute("DELETE FROM nivon_frete_previsoes_v1 WHERE sequencia=3")
        self.f.db.commit()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"quantidade"):
            self.recuperar()
        self.assertFalse(list(self.f.receipts.iterdir()))

    def test_diretorio_nao_configurado_nao_inventa_recibo(self):
        self.ciclo_sem_recibo()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"diretório"):
            self.recuperar(diretorio_recibos=self.f.root/"nao-existe")
        self.assertEqual(len(list(self.f.receipts.iterdir())),0)

    def test_recuperacao_nao_fabrica_previsao_retroativa(self):
        self.ciclo_sem_recibo()
        wrong=dict(PARAMS)
        wrong["produto"]="SOJA"
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"condições"):
            self.recuperar(condicoes=wrong)

    def test_horizonte_distinto_de_lote_nao_e_aceito(self):
        self.ciclo_sem_recibo()
        with self.assertRaisesRegex(ErroRecuperacaoFrete,"quantidade|horizontes"):
            self.recuperar(horizontes_dias=(7,30))


if __name__=="__main__":
    unittest.main()
