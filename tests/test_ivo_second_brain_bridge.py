"""Regressoes sintéticas das exportacoes canônicas Second Brain -> IVO."""
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

from nivon.ivo_second_brain_bridge import (
    AtestacaoCanonicaIVO, ErroProvenienciaIVO, ExportacaoSegundoCerebro,
    normalizar_exportacoes_canonicas,
)
from nivon.ivo_hermes_gateway import (
    EscopoHermesIVO, GatewayHermesIVO, VinculoRecursoIVO,
)

T = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
RAW = b"INMET/CONAB: synthetic immutable fixture"
HASH = sha256(RAW).hexdigest()
URL = "https://www.conab.gov.br"
TOKEN = "synthetic.token.test"
AUD = "https://hermes.example.invalid"


def registro(**changes):
    rec = {
        "contract_version": "1.0",
        "claim_id": "soy-001", "claim": "Seca no Brasil aumenta risco para soja",
        "evidence_id": "ev-001", "source_id": "CONAB",
        "evidence": [
            {"evidence_id": "ev-001", "source_id": "CONAB",
             "uri": "drive://some-fixture", "content_hash": HASH},
        ],
        "dates": {
            "competence_date": "2026-10-01",
            "reference_date": "2026-10-10",
            "publication_date": (T-timedelta(days=9)).isoformat(),
            "collection_date": (T-timedelta(days=8)).isoformat(),
        },
        "valid_from": (T-timedelta(days=7)).isoformat(),
        "valid_to": None, "status": "CANONICO",
        "project": "AGROLOG", "domain": "AGRICULTURA",
        "truth_classification": "ESTIMADO",
        "promotion": {"promoted_by": "knowledge_factory", "audited": True,
                      "validated": True, "decision_id": "KF-001"},
        "supersedes": [], "contradicts": [], "derived_from": [],
    }
    rec.update(changes)
    return rec


def digest(record):
    return sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def export(rec=None, **updates):
    args = dict(registro=rec if rec is not None else registro(),
                evidencia_bruta=RAW, exportado_em=T-timedelta(days=2))
    args.update(updates)
    return ExportacaoSegundoCerebro(**args)


def atestado(rec, tenant="TENANT_A", **kw):
    args = dict(
        claim_id=rec["claim_id"], evidence_id=rec["evidence_id"],
        source_id=rec["source_id"], tenant=tenant, consumidor="NIVON",
        registro_sha256=digest(rec), evidencia_sha256=HASH,
        fonte_url=URL, decision_id=rec["promotion"]["decision_id"],
        auditoria_id="AUD-REVIEW-001",
        aprovado_em=T-timedelta(days=5),
        verificado_em=T-timedelta(days=3),
        promocao_confirmada=True, direito_consultar=True,
        vigente_no_corte=True,
    )
    args.update(kw)
    return AtestacaoCanonicaIVO(**args)


def verifier(rec=None, **updates):
    current = rec if rec is not None else registro()
    def check(claim_id, rec_sha, bytes_sha, cut):
        return atestado(current, **updates)
    return check


def call(ex=None, check=None, **kw):
    ex = ex if ex is not None else export()
    return normalizar_exportacoes_canonicas(
        [ex], corte=T, tenant="TENANT_A",
        verificador=check if check is not None else verifier(ex.registro),
        **kw,
    )


class TestSegundoCerebroBridge(unittest.TestCase):
    def test_claim_canonico_virou_adapter_nao_verdade_certificada(self):
        result = call()
        self.assertEqual(len(result["claims"]), 1)
        c = result["claims"][0]
        self.assertEqual(c.tipo, "ESTIMATIVA")
        self.assertEqual(c.documento_sha256, HASH)
        self.assertEqual(c.fonte_url, URL)
        self.assertEqual(c.competencia, "2026-10-01")
        self.assertEqual(c.referencia_em.date().isoformat(), "2026-10-10")
        self.assertEqual(c.aprovado_por, "KNOWLEDGE_FACTORY_ATTESTATION")
        self.assertEqual(result["metadados"][0]["knowledge_project"], "AGROLOG")
        self.assertFalse(result["llm_executado"])
        self.assertFalse(result["treino_executado"])

    def test_nao_promove_research_package(self):
        r = registro(status="PACKAGED")
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_registro_validado_ainda_nao_canonico(self):
        for state in ("VALIDADO", "PROPOSTO", "SUPERADO", "REJEITADO"):
            with self.subTest(status=state):
                r = registro(status=state)
                with self.assertRaises(ErroProvenienciaIVO):
                    call(export(r), check=verifier(r))

    def test_decisao_sem_auditoria_bloqueada(self):
        r = registro(promotion={"promoted_by": "knowledge_factory",
                                "audited": False, "validated": True,
                                "decision_id": "KF-001"})
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_autopromocao_fora_knowledge_factory_bloqueada(self):
        r = registro(promotion={"promoted_by": "IVO", "audited": True,
                                "validated": True, "decision_id": "KF-001"})
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_hash_evidencia_alterada_bloqueado(self):
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(evidencia_bruta=b"tampered"))

    def test_evidence_hash_fraco_nao_passou(self):
        r = registro(evidence=[{"evidence_id": "ev-001", "source_id": "CONAB",
                                "content_hash": HASH[:8], "uri": "drive://x"}])
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_registro_trocado_depois_de_atestar(self):
        x = registro()
        altered = registro(claim="Seca e soja; texto substituido")
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(altered), check=verifier(x))

    def test_multitenancy_sem_escopo_nao_escapa(self):
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(tenant="TENANT_B"))
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(consumidor="OTHER"))

    def test_direitos_ou_promocao_declarados_negados(self):
        for key in ("direito_consultar", "promocao_confirmada", "vigente_no_corte"):
            with self.subTest(key=key):
                with self.assertRaises(ErroProvenienciaIVO):
                    call(check=verifier(**{key: False}))

    def test_decision_id_divergente_bloqueado(self):
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(decision_id="KF-OTHER"))

    def test_licenca_nao_pode_ser_deduzida_da_url(self):
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(fonte_url="http://example.org/data"))
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(fonte_url="https://user:pw@example.org/secret"))

    def test_atestacao_temporal_futura_bloqueada(self):
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(verificado_em=T+timedelta(minutes=1)))
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=verifier(aprovado_em=T+timedelta(minutes=1)))

    def test_exportacao_futura_nao_vale_retroativamente(self):
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(exportado_em=T+timedelta(minutes=1)))

    def test_publicacao_e_coleta_invertidas_rejeitadas(self):
        r = registro()
        r["dates"]["publication_date"] = T.isoformat()
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_ausencia_de_competencia_ou_referencia(self):
        for field in ("competence_date", "reference_date"):
            r = registro()
            r["dates"][field] = None
            with self.subTest(field=field), self.assertRaises(ErroProvenienciaIVO):
                call(export(r), check=verifier(r))

    def test_atestacao_ausente_bloqueia_sem_fallback(self):
        with self.assertRaises(ErroProvenienciaIVO):
            normalizar_exportacoes_canonicas([export()], corte=T,
                tenant="TENANT_A", verificador=None)

    def test_verificador_indisponivel_bloqueia(self):
        def down(*args):
            raise TimeoutError("registry offline")
        with self.assertRaises(ErroProvenienciaIVO):
            call(check=down)

    def test_snapshot_superseded_bloqueado(self):
        r = registro(valid_to=(T-timedelta(seconds=1)).isoformat())
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_origem_nao_autorizada_bloqueada(self):
        r = registro(project="RESEARCH_AI")
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_fonte_inconsistente_bloqueada(self):
        r = registro(evidence=[{"evidence_id": "ev-001", "source_id": "USDA",
                                "content_hash": HASH, "uri": "drive://x"}])
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(r), check=verifier(r))

    def test_claim_duplicado_lote_atomico_bloqueado(self):
        ex = export()
        with self.assertRaises(ErroProvenienciaIVO):
            normalizar_exportacoes_canonicas([ex, ex], corte=T, tenant="TENANT_A",
                                              verificador=verifier())

    def test_relacoes_persistem_sem_alegar_causalidade(self):
        r = registro(supersedes=["soy-000"], contradicts=["soy-002"],
                     derived_from=["weather-1"])
        out = call(export(r), check=verifier(r))
        self.assertEqual(out["metadados"][0]["relacoes_nao_causais"]["supersedes"], ["soy-000"])
        self.assertEqual(out["metadados"][0]["classificacao_origem"], "ESTIMADO")

    def test_classificacao_observada_preserva_label_nao_treina(self):
        r = registro(truth_classification="OBSERVADO")
        out = call(export(r), check=verifier(r))
        self.assertEqual(out["claims"][0].tipo, "DADO_OBSERVADO")
        self.assertFalse(out["treino_executado"])

    def test_tamanho_limite_e_corte_sem_fuso(self):
        with self.assertRaises(ErroProvenienciaIVO):
            normalizar_exportacoes_canonicas([export()], corte=T.replace(tzinfo=None),
                                              tenant="TENANT_A", verificador=verifier())
        with self.assertRaises(ErroProvenienciaIVO):
            call(export(evidencia_bruta=b"x"*8_000_001))

    def test_e2e_adapter_hermes_falso_nao_prova_oidc_real(self):
        converted = call()["claims"]
        p_requests = []
        class V:
            def verify(self, token):
                if token != TOKEN:
                    raise PermissionError
                return SimpleNamespace(subject="actor-1",
                    audience=AUD, issuer="https://issuer.example.invalid")
        class P:
            external_required = True
            opa = object()
            openfga = object()
            def authorize(self, req):
                p_requests.append(req)
                return SimpleNamespace(allowed=True, requires_approval=False)
        def lookup(c):
            return VinculoRecursoIVO(
                claim_id=c.claim_id, fonte_id=c.fonte_id,
                documento_sha256=c.documento_sha256,
                texto_sha256=sha256(c.texto.encode()).hexdigest(),
                auditoria_id=c.auditoria_id, tenant="TENANT_A",
                projeto="NIVON", direito_consulta=True,
                verificado_em=T-timedelta(minutes=2),
                expira_em=T+timedelta(minutes=2),
            )
        gateway = GatewayHermesIVO(
            identity_verifier=V(),
            scope_lookup=lambda subject: EscopoHermesIVO("TENANT_A", "NIVON", subject),
            resource_lookup=lookup,
            policy_request_factory=lambda **values: SimpleNamespace(**values),
            policy_engine=P(), audience=AUD,
            issuers=frozenset({"https://issuer.example.invalid"}),
            clock=lambda: T+timedelta(seconds=1),
        )
        out = gateway.consultar(token=TOKEN, pergunta="soja seca",
            claims=converted, corte=T, planejador=lambda _: {
                "frentes": [{"id": "SOJA"}], "intencao": "CONSULTA"})
        self.assertEqual(len(out["evidencias"]), 1)
        self.assertEqual(out["evidencias"][0]["documento_sha256"], HASH)
        self.assertEqual(p_requests[0].action, "evidence:read")
        self.assertFalse(out["llm_executado"])
        self.assertFalse(out["escrita_habilitada"])


if __name__ == "__main__":
    unittest.main()
