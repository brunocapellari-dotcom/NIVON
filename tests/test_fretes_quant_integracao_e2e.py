"""Integração offline real de código: Fretes PR #18 -> Quant PR #20.

Não sintetiza SHA RAW como prova autêntica. Ensaio matemático com edições
explícitas de fixture é permitido, mas NUNCA autoriza previsão operacional.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from nivon.fretes_registros import OfertaFrete, consolidar_ofertas
from nivon.fretes_integracao_r01 import tendencia_ofertas_pareadas
from nivon.fretes_painel_pr30 import ErroPainelFrete, preparar_painel_pr30
from nivon.integracao_frete_quant import preparar_serie_frete_anunciado
from nivon.rolling_origin import executar_rolling_origin_asof
from nivon.quant_core import ErroQuantitativo

BASE = date(2026, 10, 1)
FONTE = "WHATSAPP_SINTETICO_OFFLINE"
CHAVE = {
    "municipio_ibge": "5107925", "pickup_entity_id": "fazenda:001",
    "transportadora_id": "transp:001", "destino_ibge": "5107602",
    "descarga_entity_id": "terminal:001", "produto": "MILHO",
    "equipamento": "RODOTREM", "regime": "PJ",
}


def ofertas(dias=13):
    out = []
    for j in range(dias):
        dia = BASE + timedelta(days=j)
        pub = datetime(dia.year, dia.month, dia.day, 16, tzinfo=timezone.utc)
        for carrier in (1, 2):
            base = Decimal(150 + 15 * carrier + j * 3)
            out.append(OfertaFrete(
                publicacao_id=f"publicacao:{dia}:{carrier}",
                registro_id=f"registro:{dia}:{carrier}",
                oferta_id=f"oferta:{dia}:{carrier}",
                municipio_ibge=CHAVE["municipio_ibge"],
                pickup_entity_id=f"fazenda:{carrier:03}",
                transportadora_id=f"transp:{carrier:03}",
                destino_ibge=CHAVE["destino_ibge"],
                descarga_entity_id=CHAVE["descarga_entity_id"],
                produto=CHAVE["produto"], equipamento=CHAVE["equipamento"],
                regime=CHAVE["regime"],
                frete_base_brl_t=base, pedagio_brl_t=Decimal("10"),
                frete_cheio_brl_t=base + Decimal("10"),
                data_referencia=dia, data_publicacao=pub,
                data_coleta=pub + timedelta(hours=1), fonte_id=FONTE,
            ))
    return out


def preparar(registros, **kw):
    opts = dict(
        chave=CHAVE, fonte_id=FONTE, tipo_valor="CHEIO",
        as_of="2026-10-21T20:00:00Z",
    )
    opts.update(kw)
    return preparar_serie_frete_anunciado(registros, **opts)


class TestIntegracaoRealDeCodigoFreteQuant(unittest.TestCase):
    def test_registros_reais_de_codigo_sem_sha_raw_fail_closed(self):
        rows = ofertas()
        consolidado = consolidar_ofertas(rows)
        self.assertEqual(len(consolidado["registros"]), 26)
        self.assertEqual(consolidado["natureza"], "FRETE_ANUNCIADO_NAO_CONTRATADO")
        self.assertNotIn("media_municipal", consolidado)
        primeiro = [
            r for r in consolidado["registros"]
            if r["pickup_entity_id"] == CHAVE["pickup_entity_id"]
            and r["transportadora_id"] == CHAVE["transportadora_id"]
        ]
        self.assertEqual(len(primeiro), 13)
        self.assertTrue(all("edicao_sha256" not in x for x in primeiro))
        saida = preparar(primeiro)
        self.assertEqual(saida["status"], "BLOQUEADO_SHA_EDICAO_AUSENTE")
        self.assertEqual(saida["observacoes_asof"], [])
        self.assertEqual(saida["edicoes_sem_sha"], 13)
        self.assertFalse(saida["asof_pronto"])
        self.assertFalse(saida["uso_preditivo_real_autorizado"])
        self.assertFalse(saida["publicavel"])

    def test_mistura_de_estabelecimentos_nao_vira_preco_municipal(self):
        rows = consolidar_ofertas(ofertas())["registros"]
        with self.assertRaisesRegex(ErroQuantitativo, "heterogeneas"):
            preparar(rows)

    def test_sha_derivado_do_painel_nao_deve_ser_promovido_a_sha_raw(self):
        rows = ofertas()
        painel = preparar_painel_pr30(
            rows, origem_ibge=CHAVE["municipio_ibge"],
            destino_ibge=CHAVE["destino_ibge"],
            descarga_entity_id=CHAVE["descarga_entity_id"],
            produto=CHAVE["produto"], equipamento=CHAVE["equipamento"],
            regime=CHAVE["regime"], pedagio="ADICIONAL",
            as_of=datetime(2026, 10, 21, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(
            painel["edicao_sha256_classe"], "DIGEST_DERIVADO_NAO_PROVA_RAW")
        self.assertFalse(painel["publicavel"])
        self.assertIsNone(painel["probabilidades_calibradas"])
        # O consolidado original segue sem o raw SHA, mesmo depois
        # de um painel descritivo ter gerado um digest DERIVADO.
        linha = consolidar_ofertas(rows)["registros"][0]
        self.assertNotIn("edicao_sha256", linha)
        self.assertEqual(preparar([
            x for x in consolidar_ofertas(rows)["registros"]
            if x["pickup_entity_id"] == CHAVE["pickup_entity_id"]
        ])["status"], "BLOQUEADO_SHA_EDICAO_AUSENTE")

    def test_modelo_r01_descritivo_nao_abre_gate_quant(self):
        rows = ofertas()
        desc = tendencia_ofertas_pareadas(
            rows, origem_ibge=CHAVE["municipio_ibge"],
            destino_ibge=CHAVE["destino_ibge"],
            descarga_entity_id=CHAVE["descarga_entity_id"],
            produto=CHAVE["produto"], equipamento=CHAVE["equipamento"],
            regime=CHAVE["regime"], pedagio="ADICIONAL",
            as_of=datetime(2026, 10, 21, 20, tzinfo=timezone.utc),
            janela=6, minimo_pares=2, tolerancia_absoluta=2,
        )
        self.assertEqual(desc["tendencia"], "ALTA")
        self.assertFalse(desc["publicavel"])
        self.assertEqual(desc["direitos_publicacao_verificados"], False)
        self.assertIsNone(desc["probabilidades_calibradas"])
        consolidated = consolidar_ofertas(rows)
        raw = [x for x in consolidated["registros"]
               if x["transportadora_id"] == CHAVE["transportadora_id"]]
        self.assertFalse(preparar(raw)["asof_pronto"])

    def test_regime_ou_descarga_alterados_bloqueiam_do_painel_ao_quant(self):
        for field, value in (
            ("regime", "PF"),
            ("descarga_entity_id", "terminal:002"),
        ):
            with self.subTest(field=field):
                original = ofertas()
                alterado = replace(original[0], **{field: value})
                original[0] = alterado
                consol = consolidar_ofertas(original)
                with self.assertRaisesRegex(ErroQuantitativo, "heterogeneas"):
                    preparar([
                        x for x in consol["registros"]
                        if x["pickup_entity_id"] == CHAVE["pickup_entity_id"]
                    ])
                with self.assertRaisesRegex(ErroPainelFrete, "mistura"):
                    preparar_painel_pr30(
                        original, origem_ibge=CHAVE["municipio_ibge"],
                        destino_ibge=CHAVE["destino_ibge"],
                        descarga_entity_id=CHAVE["descarga_entity_id"],
                        produto=CHAVE["produto"], equipamento=CHAVE["equipamento"],
                        regime=CHAVE["regime"], pedagio="ADICIONAL",
                        as_of=datetime(2026, 10, 21, 20, tzinfo=timezone.utc),
                    )

    def test_raw_sha_sintetico_permite_apenas_teste_rolling_offline(self):
        # SHA fornecido SOMENTE como fixture; jamais assinado/autenticado.
        consolidado = consolidar_ofertas(ofertas())["registros"]
        primeiro = [
            {**x, "edicao_sha256": "a" * 64}
            for x in consolidado if x["pickup_entity_id"] == CHAVE["pickup_entity_id"]
        ]
        saida = preparar(primeiro)
        self.assertTrue(saida["preparacao_offline_possivel"])
        self.assertFalse(saida["asof_pronto"])
        self.assertFalse(saida["edicao_raw_externamente_verificada"])
        self.assertFalse(saida["uso_preditivo_real_autorizado"])
        calendario = [
            (BASE + timedelta(days=j)).isoformat() for j in range(13)
        ]
        origens = {
            calendario[j]: calendario[j] + "T20:00:00Z"
            for j in range(5, 10)
        }
        ensaio = executar_rolling_origin_asof(
            saida["observacoes_asof"], calendario=calendario,
            origens_em=origens, as_of_avaliacao="2026-10-21T20:00:00Z",
            serie_id=saida["serie_id"], unidade="BRL/T", fonte_id=FONTE,
            modelo_id="TESTE_PERSISTENCIA",
            horizonte_periodos=1, tamanho_treino=4,
            modelo=lambda treino, contexto: treino[-1]["valor"],
            min_folds=5,
        )
        self.assertEqual(ensaio["n_folds"], 5)
        self.assertAlmostEqual(ensaio["metricas"]["ganho_mae_baseline"], 0)
        self.assertFalse(ensaio["publicavel"])
        self.assertTrue(ensaio["prova_integridade_externa_pendente"])


if __name__ == "__main__":
    unittest.main()
