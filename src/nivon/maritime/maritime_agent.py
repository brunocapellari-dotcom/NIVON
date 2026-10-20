"""Direcao de agentes de inteligencia maritima: deterministicamente segura e read-only."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from nivon.agentes_nivon import SolicitacaoAgente, consultar_ia
from .intelligence import MaritimeAnalysisRequest, MaritimeIntelligenceCoordinator


@dataclass(frozen=True)
class MaritimeDirector:
    """Nao libera IA como fonte canonica, auditor, decisor, despachante ou publicador."""
    coordinator: MaritimeIntelligenceCoordinator = MaritimeIntelligenceCoordinator()

    def evaluate(self, request: MaritimeAnalysisRequest,
                 *, model_executor: Callable | None = None) -> dict:
        report = self.coordinator.run(request)
        evidence = report["evidence"]
        # Minimizar contexto: sem payload AIS, identidade individual ou coordenadas.
        context = {
            "engine": report["engine"],
            "port": report["port_id"],
            "as_of": report["calculated_at"],
            "source_health": evidence["source_health"]["status"],
            "trusted_positions": evidence["ais_trusted_in_port"],
            "quality_flags": sorted({
                flag for x in evidence["ais_quality"] for flag in x["quality"]["flags"]
            }),
            "lineup_analyzed": evidence["lineup_analyzed"],
            "queue": {"status": report["queue"]["status"],
                      "vqi": report["queue"]["vqi"]} if report["queue"] else None,
            "queue_forecast_status": (
                report["queue_forecast"]["status"]
                if report["queue_forecast"] else None
            ),
            "anomaly_types": [x["anomaly_type"] for x in report["anomalies"]],
            "release_blocked": report["release"]["status"] != "FINAL_READY",
            "caution": "AIS nao comprova carga; resultados SHADOW nao podem ser publicados",
        }
        serialized = json.dumps(context, sort_keys=True, ensure_ascii=False)
        evidence_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        suggestion = consultar_ia(
            SolicitacaoAgente("EDITOR", "SUGERIR_TEXTO", evidence_id, serialized),
            executor=model_executor,
        )
        audit = {
            "status": "NOT_AUTHORIZED_TO_PUBLISH",
            "reason": "no verified operational evidence, deterministic final gate blocked",
            "canonical_evidence_id": evidence_id,
            "prohibit_raw_ais_to_model": True,
            "prohibit_ai_external_actions": True,
            "publications_authorized": False,
        }
        return {
            "roles": {
                "DATA_QUALITY": "DETERMINISTIC",
                "PHYSICAL_MARITIME": "DETERMINISTIC",
                "FORECAST": "DATA_GATED",
                "RESEARCH": "READ_ONLY_OPTIONAL",
                "ANALYST_EDITOR": "READ_ONLY_OPTIONAL",
                "AUDITOR": "DETERMINISTIC_FAIL_CLOSED",
                "DELIVERY": "DISABLED",
            },
            "report": report, "evidence_summary": context,
            "editor_suggestion": suggestion, "auditor_verdict": audit,
        }
