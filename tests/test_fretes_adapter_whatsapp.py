import unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from nivon.fretes_adapter_whatsapp import adaptar_evento_whatsapp, ErroAdaptadorFrete
from nivon.fretes_registros import consolidar_ofertas

CHAVE = b"chave-sintetica-nao-operacional-para-teste-1234567890"


def caso():
    # Envelope fiel aos campos do WhatsApp AI, sem PII ou grupo real.
    evento = {
        "tenant_id": "tenant-a", "event_id": "evt-001", "version": 1,
        "classification": "FREIGHT_OFFER", "truth_classification": "OBSERVADO",
        "source_event_ids": ["msg-001"], "rate_unit": "BRL/t",
        "rate": "150.00", "product": "MILHO",
        "timestamp": "2026-10-19T20:00:00+00:00",
        "origin": {"canonical_id": "mun:5107925", "raw_value": "Sorriso-MT"},
        "destination": {"canonical_id": "mun:5107602", "raw_value": "Rondonopolis-MT"},
        "entities": {
            "company": [{"canonical_id": "transportadora:001", "raw_value": "ALFA"}],
            "loading_point": [{"canonical_id": "fazenda:001", "raw_value": "FAZENDA"}],
        },
        "provenance": {"provider": "fixture",
                       "source_event_id": "msg-001"},
    }
    resolucao = {
        "status": "VERIFICADA", "tenant_id": "tenant-a",
        "event_id": "evt-001", "version": 1, "source_event_id": "msg-001",
        "prova_sha256": "a" * 64, "municipio_ibge": "5107925",
        "destino_ibge": "5107602", "pickup_entity_id": "fazenda:001",
        "transportadora_id": "transportadora:001",
        "descarga_entity_id": "terminal:001",
        "produto": "MILHO", "equipamento": "RODOTREM", "regime": "PJ",
        "rate_role": "BASE", "frete_base_brl_t": "150.00",
        "pedagio_tipo": "ADICIONAL_VALOR", "pedagio_brl_t": "10.00",
    }
    autorizacao = {
        "tenant_id": "tenant-a", "provider": "fixture", "status": "APROVADA",
        "operacoes_permitidas": ["LEITURA", "ANALISE", "ARMAZENAMENTO"],
        "fonte_id": "WHATSAPP_EVENTOS_AUTORIZADOS",
        "comprovante_sha256": "b" * 64,
    }
    coleta = datetime(2026, 10, 19, 20, 1, tzinfo=timezone.utc)
    return evento, resolucao, autorizacao, coleta


def adaptar(ev=None, res=None, auth=None, coleta=None, key=CHAVE):
    evento, resolucao, autorizacao, coletado = caso()
    return adaptar_evento_whatsapp(
        ev if ev is not None else evento,
        resolucao=res if res is not None else resolucao,
        autorizacao=auth if auth is not None else autorizacao,
        data_coleta=coleta if coleta is not None else coletado,
        chave_hmac=key,
    )


class TestPonteWhatsAppFrete(unittest.TestCase):
    def test_oferta_por_estabelecimento_com_proveniencia_pseudonimizada(self):
        x = adaptar()
        self.assertEqual(x.pickup_entity_id, "fazenda:001")
        self.assertEqual(x.transportadora_id, "transportadora:001")
        self.assertEqual(x.frete_base_brl_t, Decimal("150.00"))
        self.assertEqual(x.pedagio_brl_t, Decimal("10.00"))
        self.assertEqual(x.frete_cheio_brl_t, Decimal("160.00"))
        self.assertEqual(x.data_referencia.isoformat(), "2026-10-19")
        self.assertTrue(x.publicacao_id.startswith("wa:"))
        self.assertNotIn("msg-001", str(x))
        self.assertNotIn("Sorriso-MT", str(x))
        self.assertNotIn("ALFA", str(x))
        self.assertEqual(x, adaptar())
        serie = consolidar_ofertas([x])
        self.assertEqual(serie["total_registros_individuais_deduplicados"], 1)
        self.assertNotIn("preco_medio", str(serie))

    def test_pedagio_desconhecido_nao_vira_zero(self):
        _, r, _, _ = caso()
        r["pedagio_tipo"] = "NAO_INFORMADO"
        r["pedagio_brl_t"] = None
        x = adaptar(res=r)
        self.assertIsNone(x.pedagio_brl_t)
        self.assertIsNone(x.frete_cheio_brl_t)

    def test_reajuste_preserva_id_e_nova_versao_sem_contaminacao(self):
        evento, resolucao, _, coleta = caso()
        anterior = adaptar()
        evento.update({
            "version": 2, "classification": "UPDATE",
            "source_event_ids": ["msg-001", "msg-002"],
            "timestamp": "2026-10-20T16:00:00+00:00",
            "rate": "175",
            "rate_change": {
                "current_rate": "175", "previous_rate": "150",
                "changed_at": "2026-10-20T16:00:00+00:00",
            },
        })
        evento["provenance"]["source_event_id"] = "msg-002"
        resolucao.update({"version": 2, "source_event_id": "msg-002",
                          "frete_base_brl_t": "175"})
        coleta = datetime(2026, 10, 20, 16, 1, tzinfo=timezone.utc)
        novo = adaptar(ev=evento, res=resolucao, coleta=coleta)
        self.assertEqual(novo.oferta_id, anterior.oferta_id)
        self.assertNotEqual(novo.registro_id, anterior.registro_id)
        self.assertNotEqual(novo.publicacao_id, anterior.publicacao_id)
        self.assertEqual(novo.frete_cheio_brl_t, Decimal("185"))
        self.assertEqual(consolidar_ofertas([anterior, novo])["total_registros_individuais_deduplicados"], 2)

    def test_mesmo_evento_em_tenants_distintos_nao_colide(self):
        evento, resolucao, autorizacao, _ = caso()
        x = adaptar()
        evento["tenant_id"] = "tenant-b"
        resolucao["tenant_id"] = "tenant-b"
        autorizacao["tenant_id"] = "tenant-b"
        y = adaptar(ev=evento, res=resolucao, auth=autorizacao)
        self.assertNotEqual(x.oferta_id, y.oferta_id)

    def test_autorizacao_negada_e_operacoes_faltantes(self):
        for change in [
            {"status": "PENDENTE"},
            {"tenant_id": "tenant-b"},
            {"provider": "outro"},
            {"operacoes_permitidas": ["LEITURA"]},
            {"comprovante_sha256": None},
        ]:
            with self.subTest(change=change), self.assertRaises(ErroAdaptadorFrete):
                _, _, a, _ = caso()
                a.update(change)
                adaptar(auth=a)

    def test_identidade_de_estabelecimento_e_transportadora_nao_inferida(self):
        for change in [
            {"status": "PENDENTE"},
            {"pickup_entity_id": None},
            {"transportadora_id": ""},
            {"descarga_entity_id": None},
            {"source_event_id": "outra"},
            {"version": 2},
            {"prova_sha256": "a"},
            {"rate_role": "CHEIO"},
            {"pedagio_tipo": "INCLUSO"},
            {"frete_base_brl_t": "149"},
            {"municipio_ibge": "xxxxxxxx"},
            {"regime": "INCERTO"},
        ]:
            with self.subTest(change=change), self.assertRaises(ErroAdaptadorFrete):
                _, r, _, _ = caso()
                r.update(change)
                adaptar(res=r)

    def test_conflito_de_canonical_id_bloqueia(self):
        ev, _, _, _ = caso()
        ev["entities"]["company"][0]["canonical_id"] = "transportadora:999"
        with self.assertRaises(ErroAdaptadorFrete):
            adaptar(ev=ev)
        ev, _, _, _ = caso()
        ev["entities"]["loading_point"] = [
            {"canonical_id": "fazenda:001"},
            {"canonical_id": "fazenda:002"},
        ]
        with self.assertRaises(ErroAdaptadorFrete):
            adaptar(ev=ev)

    def test_nao_converter_cancelamento_ou_pedido_em_oferta(self):
        for classification in ["CANCELLATION", "FREIGHT_REQUEST", "UNKNOWN"]:
            with self.subTest(classification=classification):
                ev, _, _, _ = caso()
                ev["classification"] = classification
                with self.assertRaises(ErroAdaptadorFrete):
                    adaptar(ev=ev)

    def test_nao_aceitar_fonte_sem_unidade_vinculo_ou_observacao(self):
        for change in [
            {"truth_classification": "ESTIMADO"},
            {"rate_unit": "BRL/TRIP"},
            {"rate": "NaN"},
            {"rate": -1},
            {"rate": True},
            {"source_event_ids": ["msg-999"]},
            {"timestamp": "2026-10-20T23:00:00+00:00"},
            {"timestamp": "2026-10-19T20:00:00"},
            {"product": "SOJA"},
            {"version": 0},
            {"classification": "UPDATE"},
        ]:
            with self.subTest(change=change), self.assertRaises(ErroAdaptadorFrete):
                ev, _, _, _ = caso()
                ev.update(change)
                adaptar(ev=ev)

    def test_chave_deve_ser_forte(self):
        with self.assertRaises(ErroAdaptadorFrete):
            adaptar(key=b"segredo-curto")

    def test_horario_mt_preserva_dia_da_publicacao(self):
        ev, _, _, coleta = caso()
        ev["timestamp"] = "2026-10-20T02:00:00+00:00"
        x = adaptar(ev=ev, coleta=coleta + timedelta(days=1))
        self.assertEqual(x.data_referencia.isoformat(), "2026-10-19")


if __name__ == "__main__":
    unittest.main()
