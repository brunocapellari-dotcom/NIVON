"""NIVON Maritime local-only staging API.

Pure route model plus optional loopback HTTP server, no database/network provider required.
Neither this server nor a shadow snapshot confers operational readiness or data rights.
"""
from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

PORTS = (
    ("SANTOS", "Santos"),
    ("PARANAGUA", "Paranaguá"),
    ("BARCARENA_VILA_DO_CONDE", "Barcarena / Vila do Conde"),
    ("SANTAREM", "Santarém"),
    ("ITAQUI", "Itaqui"),
)
PORT_IDS = frozenset(k for k, _ in PORTS)
MMSI_RE = re.compile(r"^[0-9]{9}$")
_ALLOWED_QUERY = {
    "/v1/maritime/config": frozenset(),
    "/v1/maritime/vessels": frozenset({"port_id", "hours", "limit"}),
    "/v1/maritime/lineup": frozenset({"port_id", "past_hours", "future_hours", "limit"}),
    "/v1/maritime/summary": frozenset({"port_id", "hours", "future_hours"}),
    "/v1/maritime/status": frozenset(),
}
_HEADERS = (
    ("Content-Type", "application/json; charset=utf-8"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
)


def _parameter(params: dict[str, list[str]], name: str, *, default: int,
               minimum: int, maximum: int) -> int:
    raw = params.get(name, [str(default)])
    if len(raw) != 1 or not re.fullmatch(r"[0-9]{1,8}", raw[0]):
        raise ValueError(f"{name}: inteiro positivo obrigatorio")
    result = int(raw[0])
    if not minimum <= result <= maximum:
        raise ValueError(f"{name}: fora dos limites")
    return result


def _port(params: dict[str, list[str]]) -> str | None:
    raw = params.get("port_id")
    if not raw:
        return None
    if len(raw) != 1:
        raise ValueError("port_id duplicado")
    value = raw[0].strip().upper()
    if value not in PORT_IDS:
        raise ValueError("port_id nao homologado no cockpit piloto")
    return value


@dataclass(frozen=True)
class MaritimeShadowFixture:
    """Injection for synthetic tests only; data is never relabeled as live."""
    vessel_rows: tuple[dict, ...] = ()
    lineup_rows: tuple[dict, ...] = ()
    replay_rows: tuple[dict, ...] = ()
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not self.synthetic:
            raise ValueError("staging fixture must be explicitly synthetic")


@dataclass(frozen=True)
class MaritimeInternalSnapshot:
    """Only audit-produced nonpublishable results, never a public/live source."""
    vessel_rows: tuple[dict, ...]
    lineup_rows: tuple[dict, ...]
    replay_rows: tuple[dict, ...]

    @classmethod
    def from_analysis(cls, report: dict, *, lineup_calls: tuple = ()) -> "MaritimeInternalSnapshot":
        if (
            report.get("engine") != "NIVON_MARITIME_INTELLIGENCE_V1"
            or report.get("status") != "SHADOW_DIAGNOSTIC"
            or report.get("publication_allowed") is not False
            or report.get("external_actions_allowed") is not False
            or report.get("release", {}).get("status") != "BLOCKED"
        ):
            raise ValueError("analise sem bloqueio deterministico; nao exportar")
        port = report.get("port_id")
        positions = report.get("trusted_positions_internal_only") or []
        if not isinstance(positions, list):
            raise ValueError("formato AIS interno invalido")
        for x in positions:
            if x.get("port_id") != port or x.get("quality_status") != "CONFIRMED_SEQUENCE":
                raise ValueError("posicao AIS nao corroborada ou porto incorreto")
        reconciled = {x["call_id"]: x for x in report.get("reconciliation", [])}
        lineup: list[dict] = []
        if lineup_calls and report.get("evidence", {}).get("lineup_analyzed") != len(lineup_calls):
            raise ValueError("line-up nao aprovado no coordenador")
        for call in lineup_calls:
            if call.port_id != port:
                raise ValueError("line-up fora do escopo")
            match = reconciled.get(call.call_id, {})
            lineup.append({
                "port_id": port, "call_id": call.call_id,
                "vessel_name": call.vessel_name, "imo": call.imo, "mmsi": call.mmsi,
                "eta": str(call.eta), "collected_at": str(call.collected_at),
                "product": call.product, "planned_volume_t": call.planned_volume_t,
                "reconciled_state": match.get("state", "PROGRAMMED"),
                "evidence_class": "INFORMADO_LINEUP",
                "match_method": match.get("match_method"),
                "match_confidence": match.get("match_confidence"),
                "flags_json": "[]",
                "calculated_at": report.get("calculated_at"),
            })
        return cls(
            vessel_rows=tuple(dict(x) for x in positions),
            lineup_rows=tuple(lineup),
            replay_rows=tuple(dict(x) for x in positions),
        )


class MaritimeReadAPI:
    def __init__(self, *, fixture: MaritimeShadowFixture | None = None,
                 internal: MaritimeInternalSnapshot | None = None) -> None:
        if fixture is not None and internal is not None:
            raise ValueError("nao misturar simulacao e evidencia interna")
        self.fixture = fixture
        self.internal = internal
        self.mode = ("SHADOW_INTERNAL" if internal is not None else
                     "SYNTHETIC_TEST_ONLY" if fixture is not None else "DATA_GATED")

    def resolve(self, path: str, query: str = "") -> tuple[int, dict]:
        if len(path) > 200 or len(query) > 512:
            return 400, {"error": "request_too_large"}
        replay = re.fullmatch(r"/v1/maritime/vessels/([0-9]{9})/replay", path)
        if path not in _ALLOWED_QUERY and not replay:
            return 404, {"error": "route_not_found"}
        try:
            params = parse_qs(query, keep_blank_values=True, max_num_fields=8)
            fields = (frozenset({"hours", "limit"}) if replay
                      else _ALLOWED_QUERY[path])
            if any(k not in fields for k in params):
                raise ValueError("parametro nao permitido")
            for key, values in params.items():
                if len(values) != 1 or not values[0]:
                    raise ValueError("parametro ausente ou repetido")
            return 200, self._read(path, params, replay)
        except ValueError as exc:
            return 400, {"error": "invalid_query", "detail": str(exc)}

    def _read(self, path: str, p: dict[str, list[str]], replay) -> dict:
        meta = {
            "status": self.mode,
            "publication_allowed": False,
            "data_origin": ("AUDITED_INTERNAL_NOT_PUBLISHED" if self.internal is not None else
                            "SYNTHETIC_FIXTURE" if self.fixture is not None else "NO_SOURCE"),
            "evidence_class": ("DIAGNOSTICO_INTERNO" if self.internal is not None else
                               "SIMULADO" if self.fixture is not None else "SEM_DADO"),
            "warning": "Staging local: nenhum dado ou operacao real homologados",
        }
        if path == "/v1/maritime/config":
            return {**meta, "pilot_ports": [{"port_id": key, "name": label} for key, label in PORTS]}
        if path == "/v1/maritime/status":
            return {**meta, "ais_live": False, "lineup_live": False,
                    "forecast_validated": False, "storage_operational": False}
        if replay:
            mmsi = replay.group(1)
            if not MMSI_RE.fullmatch(mmsi) or mmsi == "000000000":
                raise ValueError("mmsi invalido")
            hours = _parameter(p, "hours", default=24, minimum=1, maximum=168)
            limit = _parameter(p, "limit", default=2000, minimum=1, maximum=20000)
            cutoff = datetime.now(timezone.utc).timestamp() - 3600 * hours
            rows = [x for x in self._rows("replay_rows") if x.get("mmsi") == mmsi
                    and self._timestamp(x.get("observed_at")) >= cutoff]
            rows = sorted(rows, key=lambda x: x["observed_at"])[:limit]
            return {**meta, "data": rows}
        port = _port(p)
        if path.endswith("/vessels"):
            hours = _parameter(p, "hours", default=6, minimum=1, maximum=168)
            limit = _parameter(p, "limit", default=500, minimum=1, maximum=5000)
            cutoff = datetime.now(timezone.utc).timestamp() - 3600 * hours
            rows = [x for x in self._rows("vessel_rows")
                    if (port is None or x.get("port_id") == port)
                    and self._timestamp(x.get("observed_at")) >= cutoff]
            rows = sorted(rows, key=lambda x: x["observed_at"], reverse=True)
            newest = {}
            for x in rows:
                key = x.get("mmsi")
                if key and key not in newest:
                    newest[key] = x
            return {**meta, "data": list(newest.values())[:limit]}
        if path.endswith("/lineup"):
            _parameter(p, "past_hours", default=24, minimum=0, maximum=168)
            _parameter(p, "future_hours", default=336, minimum=1, maximum=1080)
            limit = _parameter(p, "limit", default=500, minimum=1, maximum=2000)
            rows = [x for x in self._rows("lineup_rows") if port is None or x.get("port_id") == port]
            return {**meta, "data": rows[:limit]}
        _parameter(p, "hours", default=24, minimum=1, maximum=168)
        _parameter(p, "future_hours", default=336, minimum=1, maximum=1080)
        if self.fixture is None and self.internal is None:
            return {**meta, "data": {
                "vessels_live": None, "vessels_approaching": None,
                "vessels_waiting": None, "vessels_berthed": None,
                "lineup_calls": None, "waiting_p50_hours": None,
                "waiting_p90_hours": None, "eta_mae_hours": None,
                "berth_avg_hours": None,
            }}
        vessel_rows = [r for r in self._rows("vessel_rows") if port is None or r.get("port_id") == port]
        by_mmsi = {r.get("mmsi"): r for r in vessel_rows if r.get("mmsi")}
        zones = [r.get("zone") for r in by_mmsi.values()]
        return {**meta, "data": {
            "vessels_live": len(by_mmsi), "vessels_approaching": zones.count("APPROACH"),
            "vessels_waiting": zones.count("ANCHORAGE"),
            "vessels_berthed": zones.count("BERTH"),
            "lineup_calls": sum(1 for r in self._rows("lineup_rows") if port is None or r.get("port_id") == port),
            "waiting_p50_hours": None, "waiting_p90_hours": None,
            "eta_mae_hours": None, "berth_avg_hours": None,
        }}

    @staticmethod
    def _timestamp(value: object) -> float:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.timestamp() if dt.tzinfo is not None else float("-inf")
        except (ValueError, TypeError, OverflowError):
            return float("-inf")

    def _rows(self, name: str) -> tuple[dict, ...]:
        obj = self.internal if self.internal is not None else self.fixture
        return getattr(obj, name) if obj is not None else ()


class MaritimeLocalWSGI:
    """GET/HEAD only; host allowlist, no CORS, no static path traversal."""

    def __init__(self, api: MaritimeReadAPI | None = None,
                 static_root: str | Path | None = None) -> None:
        self.api = api or MaritimeReadAPI()
        self.static_root = Path(static_root).resolve() if static_root is not None else None

    def __call__(self, environ: dict, start_response):
        method = environ.get("REQUEST_METHOD", "")
        host = environ.get("HTTP_HOST", "").split(":")[0].lower()
        if host not in {"127.0.0.1", "localhost"}:
            return self._json(start_response, "403 Forbidden", {"error": "untrusted_host"}, method)
        if method not in {"GET", "HEAD"}:
            return self._json(start_response, "405 Method Not Allowed", {"error": "read_only"}, method)
        path = environ.get("PATH_INFO", "")
        if self.static_root is not None and (path == "/maritime/" or path.startswith("/assets/")):
            return self._static(start_response, method, path)
        code, payload = self.api.resolve(path, environ.get("QUERY_STRING", ""))
        status = {200: "200 OK", 400: "400 Bad Request", 404: "404 Not Found"}[code]
        return self._json(start_response, status, payload, method)

    @staticmethod
    def _json(start_response, status: str, payload: dict, method: str):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        start_response(status, list(_HEADERS) + [("Content-Length", str(len(data)))])
        return [data] if method != "HEAD" else [b""]

    def _static(self, start_response, method: str, path: str):
        """Staging same-origin frontend; reject traversal/symlink and arbitrary files."""
        assert self.static_root is not None
        relative = ("index.html" if path == "/maritime/" else path.lstrip("/"))
        candidate = self.static_root / relative
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.static_root) or candidate.is_symlink() or not candidate.is_file():
            return self._json(start_response, "404 Not Found", {"error": "asset_not_found"}, method)
        if candidate.stat().st_size > 8 * 1024 * 1024:
            return self._json(start_response, "413 Content Too Large", {"error": "asset_too_large"}, method)
        content = candidate.read_bytes()
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if mime in {"text/html", "text/javascript", "application/javascript", "text/css"}:
            mime += "; charset=utf-8"
        headers = [
            ("Content-Type", mime), ("Content-Length", str(len(content))),
            ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "no-referrer"), ("Cache-Control", "no-store"),
            ("Cross-Origin-Resource-Policy", "same-origin"),
            ("Content-Security-Policy",
             "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
             "script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
             "img-src 'self' data: blob: https:; connect-src 'self' https:; "
             "worker-src 'self' blob:; font-src 'self' data:"),
        ]
        start_response("200 OK", headers)
        return [content] if method != "HEAD" else [b""]


def serve_loopback_only(*, port: int = 8765,
                        static_root: str | Path | None = None) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("porta insegura ou fora de intervalo")
    with make_server("127.0.0.1", port, MaritimeLocalWSGI(static_root=static_root)) as server:
        server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NIVON Maritime staging read-only localhost")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ui-dist", type=Path, default=None,
                        help="diretorio opcional maritime_ui/dist compilado localmente")
    args = parser.parse_args()
    serve_loopback_only(port=args.port, static_root=args.ui_dist)
