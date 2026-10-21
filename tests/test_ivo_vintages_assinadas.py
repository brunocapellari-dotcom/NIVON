"""Testes de replay de vintages Knowledge Factory com HMAC e ancora externa."""
import hmac
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from nivon.ivo_second_brain_bridge import (
    ErroProvenienciaIVO, ExportacaoSegundoCerebro,
    normalizar_exportacoes_canonicas,
)
from nivon.ivo_vintages_assinadas import (
    DOMAIN, GENESIS, EnvelopeAssinadoIVO, RegistroVintagesIVO,
)

T = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
KEY = b"fixture-only-not-a-production-key-" + b"x" * 9
RAW = b"synthetic immutable source bytes"
RAW_HASH = sha256(RAW).hexdigest()
CLAIM_HASH = sha256(b"synthetic canonical record").hexdigest()


def stamp(days=0):
    return (T + timedelta(days=days)).isoformat()


def payload(**extra):
    p = dict(
        seq=1, prev_sha256=GENESIS, evento="PROMOVIDO",
        tenant="TENANT_A", consumidor="NIVON", operacao="CONSULTAR_EVIDENCIA",
        claim_id="SOY-001", evidence_id="EVD-1", source_id="CONAB",
        registro_sha256=CLAIM_HASH, evidencia_sha256=RAW_HASH,
        fonte_url="https://www.conab.gov.br",
        decision_id="KF-1", auditoria_id="AUD-1",
        publicado_em=stamp(-12), coletado_em=stamp(-11),
        aprovado_em=stamp(-10), efetivo_em=stamp(-10),
        gravado_em=stamp(-9), direito_consulta=True,
    )
    p.update(extra)
    return p


def serialized(payload_):
    return json.dumps(payload_, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def signed(p, kid="key-v1", key=KEY):
    mac = hmac.new(key, DOMAIN + serialized(p), sha256).hexdigest()
    return EnvelopeAssinadoIVO(kid, p, mac)


def event_digest(event):
    return sha256(serialized({
        "kid": event.chave_id, "mac_sha256": event.mac_sha256,
        "payload": event.payload,
    })).hexdigest()


def ledger(events=None, anchors=None, resolver=None, head=None):
    events = [signed(payload())] if events is None else events
    anchors = ({event_digest(e): T+timedelta(days=-8+i)
                for i, e in enumerate(events)} if anchors is None else anchors)
    return RegistroVintagesIVO(
        events,
        resolver_chave=(resolver or (lambda k: KEY if k == "key-v1" else None)),
        obter_ancora=lambda digest: anchors[digest],
        obter_cabeca=lambda: (event_digest(events[-1]) if events else GENESIS) if head is None else head,
    )


def check(lgr, cut=T, **kwargs):
    kwargs.setdefault("tenant", "TENANT_A")
    return lgr.autorizador(**kwargs)(
        "SOY-001", CLAIM_HASH, RAW_HASH, cut,
    )


def revoke(e1, **kw):
    p = payload(seq=2, prev_sha256=event_digest(e1), evento="REVOGADO",
                decision_id="KF-2", aprovado_em=stamp(-4),
                efetivo_em=stamp(-4), gravado_em=stamp(-3),
                direito_consulta=False)
    p.update(kw)
    return signed(p)


class TestVintagesAssinadas(unittest.TestCase):
    def test_promocao_assinada_e_ancorada(self):
        a = check(ledger())
        self.assertEqual(a.decision_id, "KF-1")
        self.assertEqual(a.verificado_em, T-timedelta(days=8))
        self.assertEqual(a.evidencia_sha256, RAW_HASH)
        self.assertTrue(a.direito_consultar)

    def test_sem_ancora_externa_falha_fechado(self):
        e = signed(payload())
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e], anchors={}))

    def test_chave_faltante_ou_insuficiente(self):
        for value in (None, b"tiny"):
            with self.subTest(value=value), self.assertRaises(ErroProvenienciaIVO):
                check(ledger(resolver=lambda kid, v=value: v))

    def test_mac_divergente_bloqueado(self):
        e = signed(payload())
        e = replace(e, mac_sha256="f"*64)
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e]))

    def test_mutacao_payload_apos_assinar_bloqueia(self):
        e = signed(payload())
        e.payload["tenant"] = "TENANT_B"
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e]))

    def test_snapshot_copiado_antes_da_mutacao_da_origem(self):
        e = signed(payload())
        lgr = ledger([e])
        e.payload["tenant"] = "OTHER"
        self.assertEqual(check(lgr).tenant, "TENANT_A")

    def test_reordenacao_ou_ausencia_de_evento_detectada(self):
        e1 = signed(payload())
        e2 = revoke(e1)
        for events in ([e2], [e2, e1]):
            with self.subTest(count=len(events)), self.assertRaises(ErroProvenienciaIVO):
                check(ledger(events))

    def test_cadeia_corrompida_e_reassinada_nao_basta(self):
        e1 = signed(payload())
        e2 = revoke(e1, prev_sha256="e"*64)
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e1, e2]))

    def test_sequencia_saltada_com_assinatura_valida(self):
        e1 = signed(payload(seq=2))
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e1]))

    def test_truncamento_da_revogacao_falha_com_cabeca_confiavel(self):
        e1 = signed(payload())
        e2 = revoke(e1)
        # Fonte independente afirma que o head verdadeiro inclui a revogacao.
        with self.assertRaisesRegex(ErroProvenienciaIVO, "incompleta"):
            check(ledger([e1], head=event_digest(e2)))

    def test_cabeca_externa_obrigatoria(self):
        e = signed(payload())
        with self.assertRaises(ErroProvenienciaIVO):
            RegistroVintagesIVO(
                [e], resolver_chave=lambda kid: KEY,
                obter_ancora=lambda _: T-timedelta(days=8),
                obter_cabeca=None,
            )

    def test_cabeca_confiavel_indisponivel(self):
        e = signed(payload())
        lgr = RegistroVintagesIVO(
            [e], resolver_chave=lambda kid: KEY,
            obter_ancora=lambda _: T-timedelta(days=8),
            obter_cabeca=lambda: (_ for _ in ()).throw(TimeoutError()),
        )
        with self.assertRaises(ErroProvenienciaIVO):
            check(lgr)

    def test_revogacao_ancorada_bloqueia_acesso_atual(self):
        e1 = signed(payload())
        e2 = revoke(e1)
        anchors = {event_digest(e1): T-timedelta(days=8),
                   event_digest(e2): T-timedelta(days=2)}
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e1, e2], anchors))

    def test_replay_antes_de_revogacao_retem_estado_que_era_conhecido(self):
        e1 = signed(payload())
        e2 = revoke(e1)
        anchors = {event_digest(e1): T-timedelta(days=8),
                   event_digest(e2): T-timedelta(days=2)}
        self.assertEqual(check(ledger([e1, e2], anchors), T-timedelta(days=6)).decision_id,
                         "KF-1")

    def test_ancora_tardia_impede_retroatividade(self):
        e = signed(payload(gravado_em=stamp(-9)))
        anchors = {event_digest(e): T-timedelta(days=1)}
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e], anchors), T-timedelta(days=2))

    def test_ancora_anterior_a_gravacao_e_rejeitada(self):
        e = signed(payload())
        anchors = {event_digest(e): T-timedelta(days=10)}
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e], anchors))

    def test_ancoras_fora_de_ordem_bloqueiam_cadeia(self):
        e1 = signed(payload())
        e2 = revoke(e1)
        anchors = {event_digest(e1): T-timedelta(days=1),
                   event_digest(e2): T-timedelta(days=2)}
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e1, e2], anchors))

    def test_backdate_de_decisao_nao_antecipa_ancora(self):
        e = signed(payload(aprovado_em=stamp(-11), efetivo_em=stamp(-11)))
        anchors = {event_digest(e): T-timedelta(days=1)}
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e], anchors), T-timedelta(days=2))

    def test_versao_revisada_nao_valida_hash_da_versao_antiga(self):
        e1 = signed(payload())
        e2 = signed(payload(
            seq=2, prev_sha256=event_digest(e1), decision_id="KF-NEW",
            registro_sha256="a"*64, aprovado_em=stamp(-4),
            efetivo_em=stamp(-4), gravado_em=stamp(-3),
        ))
        anchors = {event_digest(e1): T-timedelta(days=8),
                   event_digest(e2): T-timedelta(days=2)}
        lgr = ledger([e1, e2], anchors)
        with self.assertRaises(ErroProvenienciaIVO):
            check(lgr)
        self.assertEqual(check(lgr, T-timedelta(days=6)).decision_id, "KF-1")

    def test_tenant_consumer_operation_escopados(self):
        lgr = ledger()
        for kw in (
            {"tenant": "TENANT_B"}, {"consumidor": "OTHER"},
            {"operacao": "PROMOVER"},
        ):
            with self.subTest(kw=kw), self.assertRaises(ErroProvenienciaIVO):
                check(lgr, **kw)

    def test_decision_id_duplicado_rejeitado(self):
        e1 = signed(payload())
        e2 = revoke(e1, decision_id="KF-1")
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e1, e2]))

    def test_semantica_promovido_nega_direito_incoerente(self):
        e = signed(payload(direito_consulta=False))
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e]))

    def test_schema_inesperado_nao_injeta_politica(self):
        e = signed(payload(permission="root"))
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e]))

    def test_tempo_sem_fuso_rejeitado(self):
        e = signed(payload(gravado_em="2026-10-12T12:00:00"))
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e]))

    def test_corte_sem_fuso_ou_hash_invalido_rejeitado(self):
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger(), T.replace(tzinfo=None))
        with self.assertRaises(ErroProvenienciaIVO):
            ledger().autorizador()("SOY-001", "not-a-hash", RAW_HASH, T)

    def test_revogacao_nao_vira_promocao_so_por_trust_no_texto(self):
        e1 = signed(payload())
        e2 = revoke(e1)
        anchors = {event_digest(e1): T-timedelta(days=8),
                   event_digest(e2): T-timedelta(days=2)}
        with self.assertRaises(ErroProvenienciaIVO):
            check(ledger([e1, e2], anchors))

    def test_vintage_para_bridge_canonica_end_to_end_sintetica(self):
        rec = {
            "contract_version": "1.0",
            "claim_id": "SOY-001",
            "claim": "Soja e seca na regiao agricola",
            "source_id": "CONAB", "evidence_id": "EVD-1",
            "evidence": [{"evidence_id": "EVD-1", "source_id": "CONAB",
                          "uri": "drive://fixture", "content_hash": RAW_HASH}],
            "project": "NIVON", "domain": "AGRICULTURA",
            "status": "CANONICO", "truth_classification": "ESTIMADO",
            "promotion": {"promoted_by": "knowledge_factory", "audited": True,
                          "validated": True, "decision_id": "KF-1"},
            "dates": {"reference_date": "2026-10-10", "competence_date": "2026-10-01",
                      "publication_date": stamp(-12),
                      "collection_date": stamp(-11)},
            "valid_from": stamp(-10), "valid_to": None,
        }
        record_digest = sha256(serialized(rec)).hexdigest()
        e = signed(payload(registro_sha256=record_digest))
        anchors = {event_digest(e): T-timedelta(days=8)}
        result = normalizar_exportacoes_canonicas(
            [ExportacaoSegundoCerebro(rec, RAW, T-timedelta(days=7))],
            corte=T, tenant="TENANT_A",
            verificador=ledger([e], anchors).autorizador(tenant="TENANT_A"),
        )
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(result["claims"][0].tipo, "ESTIMATIVA")
        self.assertEqual(result["metadados"][0]["decision_id"], "KF-1")
        self.assertFalse(result["treino_executado"])


if __name__ == "__main__":
    unittest.main()
