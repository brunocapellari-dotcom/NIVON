"""Assinatura do webhook e menções originais em anúncios rotulados."""
from copy import deepcopy
import unittest

from scripts.ensaio_fretes_texto_whatsapp import (
    gerar_fixture, reemitir_pacote, META_SECRET, PSEUDO_KEY,
    ATTEST_KEYS, EMISSORES, ASOF, _adapter
)
from nivon.fretes_adapter_whatsapp import ErroAdaptadorFrete
from nivon.fretes_texto_original_whatsapp import (
    executar_lote_whatsapp_rotulado_offline,
    triar_lote_whatsapp_em_quarentena_offline,
)


class TestTextoWhatsAppOriginal(unittest.TestCase):
    def test_fluxo_inteiro_original_assinado_e_resolucao(self):
        p=gerar_fixture("PJ",0,1)
        res=_adapter(p)
        self.assertEqual(res["oferta"].regime,"PJ")
        self.assertEqual(res["evidencia_textual"]["campos_literais_conferidos"],11)
        self.assertTrue(res["evidencia_textual"]["hmac_meta_validado_sob_chave_runtime"])
        self.assertFalse(res["publicavel"])
        self.assertNotIn("FAZENDA TESTE",str(res["evidencia_textual"]))
        self.assertNotIn("TRANSPORTADORA FICTICIA",str(res["evidencia_textual"]))
        self.assertEqual(len(res["evidencia_textual"]["evidencias_por_campo"]),11)

    def test_lote_rotulado_produz_paineis_e_nao_publica(self):
        batch=[gerar_fixture(regime,d,p)
               for regime in ("PJ","PF") for d in range(7) for p in (1,2)]
        out=executar_lote_whatsapp_rotulado_offline(
            batch,as_of=ASOF,chave_hmac=PSEUDO_KEY,
            chaves_atestacao=ATTEST_KEYS,
            emissores_atestacao=EMISSORES,app_secret=META_SECRET,
        )
        self.assertEqual(out["webhooks_assinados_e_rotulados"],28)
        self.assertEqual(out["n_series_individuais"],4)
        self.assertEqual(out["n_paineis_comerciais"],2)
        self.assertEqual(
            {x["condicoes"]["regime"] for x in out["tendencias_pareadas"]},
            {"PF","PJ"}
        )
        self.assertTrue(all(
            x["resultado"]["status"]=="BLOQUEADO_SHA_EDICAO_AUSENTE"
            for x in out["series_quantitativas"]
        ))
        self.assertFalse(out["uso_preditivo_real_autorizado"])
        self.assertFalse(out["publicavel"])
        self.assertNotIn("media_municipal",str(out))

    def test_meta_hmac_adulteracao_e_timestamps(self):
        p=gerar_fixture("PJ",0,1)
        x=deepcopy(p);x["raw_webhook"]+=b" "
        with self.assertRaises(PermissionError):
            _adapter(x)
        x=reemitir_pacote(p)
        # Conteúdo Meta modificado, assinatura reemitida, evento não altera.
        x=deepcopy(x)
        from scripts.ensaio_fretes_texto_whatsapp import _webhook
        from datetime import datetime,timedelta
        import json
        data=json.loads(x["raw_webhook"])
        msg=data["entry"][0]["changes"][0]["value"]["messages"][0]
        msg["timestamp"]=str(int(msg["timestamp"])+60)
        import hmac
        from hashlib import sha256
        x["raw_webhook"]=json.dumps(data,sort_keys=True).encode()
        x["signature"]="sha256="+hmac.new(
            META_SECRET.encode(),x["raw_webhook"],sha256).hexdigest()
        with self.assertRaisesRegex(ErroAdaptadorFrete,"horário"):
            _adapter(x)

    def test_frete_pedagio_produto_descarga_regime_nao_inferidos(self):
        p=gerar_fixture("PJ",0,1)
        body_opts=[
            lambda t:t.replace("FRETE: R$ 155,00/t","FRETE: R$ 999,00/t"),
            lambda t:t.replace("PEDÁGIO: R$ 10,00/t","PEDÁGIO: NAO INFORMADO"),
            lambda t:t.replace("PRODUTO: MILHO","PRODUTO: SOJA"),
            lambda t:t.replace("DESCARGA: TERMINAL TESTE","DESCARGA: TERMINAL OUTRO"),
            lambda t:t.replace("REGIME: PJ","REGIME: PF"),
            lambda t:t.replace("DATA: 2026-10-12","DATA: 2024-10-12"),
            lambda t:t.replace("TRANSPORTADORA: TRANSPORTADORA FICTICIA 1",
                               "TRANSPORTADORA: TRANSPORTADORA DESCONHECIDA"),
        ]
        for fn in body_opts:
            x=reemitir_pacote(p,alterar_texto=fn)
            with self.subTest(text=x["raw_webhook"][-35:]),self.assertRaises(ErroAdaptadorFrete):
                _adapter(x)

    def test_ausencia_dupla_linha_extra_e_livre(self):
        p=gerar_fixture("PJ",0,1)
        for fn in (
            lambda t:t+"\nREGIME: PJ",
            lambda t:t+"\nPRECO: R$ 999,00/t",
            lambda t:t.replace("PEDÁGIO: R$ 10,00/t\n",""),
            lambda _: "Frete milho Sorriso a Rondonópolis, negociar 155.",
            lambda t:t.replace("PRODUTO: MILHO","PRODUTO:"),
        ):
            x=reemitir_pacote(p,alterar_texto=fn)
            with self.subTest(data=x["raw_webhook"][-50:]),self.assertRaises(ErroAdaptadorFrete):
                _adapter(x)

    def test_entidade_canonica_so_com_atestacao_e_mencao_literal(self):
        p=gerar_fixture("PJ",0,1)
        x=reemitir_pacote(p,alterar_resolucao=lambda d:d.update(
            pickup_entity_id="fazenda:forjada"))
        with self.assertRaises(ErroAdaptadorFrete):
            _adapter(x)
        x=deepcopy(p)
        x["resolucao"]["descarga_raw"]="TERMINAL FRAUDE"
        with self.assertRaises(ErroAdaptadorFrete):
            _adapter(x)

    def test_lote_adulterado_bloqueia_toda_a_batch(self):
        batch=[gerar_fixture("PJ",d,p) for d in range(6) for p in (1,2)]
        batch[5]=reemitir_pacote(
            batch[5],alterar_texto=lambda t:t.replace("PRODUTO: MILHO","PRODUTO: SOJA"))
        with self.assertRaises(ErroAdaptadorFrete):
            executar_lote_whatsapp_rotulado_offline(
                batch,as_of=ASOF,chave_hmac=PSEUDO_KEY,
                chaves_atestacao=ATTEST_KEYS,
                emissores_atestacao=EMISSORES,app_secret=META_SECRET,
            )

    def test_waba_nao_atestada_ou_divergente_bloqueia(self):
        p=gerar_fixture("PJ",0,1)
        x=deepcopy(p)
        x["autorizacao"].pop("waba_id")
        with self.assertRaises(ErroAdaptadorFrete):
            _adapter(x)
        x=deepcopy(p)
        x["autorizacao"]["waba_id"]="waba-outra"
        with self.assertRaises(ErroAdaptadorFrete):
            _adapter(x)
        # Um atestador assinou outra WABA; não há transferência
        # automática de direitos entre contas.
        from scripts.ensaio_fretes_texto_whatsapp import _atestar
        from datetime import datetime
        x=deepcopy(p)
        original={
            k:v for k,v in x["autorizacao"].items()
            if k not in {"versao_atestacao","emissor_id","emitido_em",
                         "valido_ate","assinatura_hmac_sha256"}
        }
        original["waba_id"]="waba-outra"
        x["autorizacao"]=_atestar(
            original,"DIREITOS",datetime.fromisoformat(x["evento"]["timestamp"])
        )
        with self.assertRaisesRegex(ErroAdaptadorFrete,"WABA diferente"):
            _adapter(x)

    def test_replay_da_mesma_mensagem_no_lote_bloqueia(self):
        p=gerar_fixture("PJ",0,1)
        with self.assertRaisesRegex(ErroAdaptadorFrete,"republicação"):
            executar_lote_whatsapp_rotulado_offline(
                [p,deepcopy(p)],as_of=ASOF,chave_hmac=PSEUDO_KEY,
                chaves_atestacao=ATTEST_KEYS,
                emissores_atestacao=EMISSORES,app_secret=META_SECRET,
            )

    def test_quarentena_preserva_somente_validos_sem_pii(self):
        batch=[gerar_fixture(regime,d,p)
               for regime in ("PJ","PF") for d in range(7) for p in (1,2)]
        suspeito=reemitir_pacote(
            batch[0],alterar_texto=lambda _: "Frete milho Sorriso 155. Negociar."
        )
        result=triar_lote_whatsapp_em_quarentena_offline(
            batch+[suspeito,deepcopy(batch[1])],
            as_of=ASOF,chave_hmac=PSEUDO_KEY,
            chaves_atestacao=ATTEST_KEYS,
            emissores_atestacao=EMISSORES,app_secret=META_SECRET,
        )
        self.assertEqual(result["mensagens_recebidas_no_lote"],30)
        self.assertEqual(result["anuncios_rotulados_admitidos"],28)
        self.assertEqual(result["mensagens_em_quarentena"],2)
        self.assertEqual(result["n_series_individuais"],4)
        self.assertEqual(result["n_paineis_comerciais"],2)
        self.assertFalse(result["publicavel"])
        self.assertFalse(result["raw_quarentena_persistido"])
        self.assertFalse(result["rejeitados_incluidos_nas_tendencias"])
        self.assertNotIn("FAZENDA TESTE",str(result["quarentena"]))
        self.assertNotIn("Sorriso-MT",str(result["quarentena"]))

    def test_quarentena_total_nao_cria_paineis_ou_frete_sintetico(self):
        pacote=gerar_fixture("PJ",0,1)
        pacote=reemitir_pacote(
            pacote,alterar_texto=lambda t:"Mensagem livre sem preço verificável."
        )
        out=triar_lote_whatsapp_em_quarentena_offline(
            [pacote],as_of=ASOF,chave_hmac=PSEUDO_KEY,
            chaves_atestacao=ATTEST_KEYS,
            emissores_atestacao=EMISSORES,app_secret=META_SECRET,
        )
        self.assertEqual(out["anuncios_rotulados_admitidos"],0)
        self.assertEqual(out["mensagens_em_quarentena"],1)
        self.assertEqual(out["n_series_individuais"],0)
        self.assertEqual(out["n_paineis_comerciais"],0)
        self.assertFalse(out["publicavel"])

    def test_asof_nunca_usa_coleta_posterior(self):
        p=gerar_fixture("PJ",0,1)
        from datetime import datetime,timezone
        with self.assertRaises(ErroAdaptadorFrete):
            executar_lote_whatsapp_rotulado_offline(
                [p],as_of=datetime(2026,10,11,12,tzinfo=timezone.utc),
                chave_hmac=PSEUDO_KEY,chaves_atestacao=ATTEST_KEYS,
                emissores_atestacao=EMISSORES,app_secret=META_SECRET,
            )


if __name__=="__main__":
    unittest.main()
