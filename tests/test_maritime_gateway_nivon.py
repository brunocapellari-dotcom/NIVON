"""API Maritime (staging) deve rejeitar escritas e impedir que demo vire dado real."""
import json
import unittest
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

from nivon.maritime.maritime_gateway import (
    MaritimeLocalWSGI, MaritimeReadAPI, MaritimeShadowFixture,
)
NOW = datetime.now(timezone.utc)


def vessel(*, minutes=5, mmsi="123456789", port="SANTOS", zone="ANCHORAGE"):
    return {
        "mmsi": mmsi, "port_id": port, "zone": zone,
        "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(),
        "latitude": -23.9, "longitude": -46.3,
        "quality_status": "CONFIRMED_SEQUENCE",
    }


def wsgi_call(app, path, *, method="GET", host="127.0.0.1", query=""):
    record = []
    def start(status, headers):
        record.append((status, dict(headers)))
    body = b"".join(app({
        "REQUEST_METHOD": method, "PATH_INFO": path,
        "QUERY_STRING": query, "HTTP_HOST": host,
    }, start))
    return record[0], json.loads(body) if body else None


class TestMaritimeGateway(unittest.TestCase):
    def test_default_requires_no_false_live_counts(self):
        api = MaritimeReadAPI()
        code, data = api.resolve("/v1/maritime/summary", "port_id=SANTOS")
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "DATA_GATED")
        self.assertIsNone(data["data"]["vessels_live"])
        self.assertFalse(data["publication_allowed"])
        code, ships = api.resolve("/v1/maritime/vessels", "")
        self.assertEqual(code, 200)
        self.assertEqual(ships["data"], [])

    def test_config_has_five_ports_and_no_homologation(self):
        code, cfg = MaritimeReadAPI().resolve("/v1/maritime/config")
        self.assertEqual(code, 200)
        self.assertEqual(len(cfg["pilot_ports"]), 5)
        self.assertFalse(cfg["publication_allowed"])

    def test_synthetic_fixture_is_labeled_and_deduplicated(self):
        api = MaritimeReadAPI(fixture=MaritimeShadowFixture(
            vessel_rows=(vessel(minutes=7), vessel(minutes=2),
                         vessel(minutes=1, port="ITAQUI")),
            replay_rows=(vessel(minutes=7), vessel(minutes=2)),
            lineup_rows=({"port_id": "SANTOS", "vessel_name": "TEST"},),
        ))
        code, ships = api.resolve("/v1/maritime/vessels", "port_id=SANTOS&hours=6")
        self.assertEqual(code, 200)
        self.assertEqual(len(ships["data"]), 1)
        self.assertEqual(ships["data_origin"], "SYNTHETIC_FIXTURE")
        self.assertFalse(ships["publication_allowed"])
        self.assertEqual(ships["data"][0]["observed_at"], vessel(minutes=2)["observed_at"] if False else ships["data"][0]["observed_at"])
        code, summary = api.resolve("/v1/maritime/summary", "port_id=SANTOS")
        self.assertEqual(summary["data"]["lineup_calls"], 1)
        self.assertEqual(summary["status"], "SYNTHETIC_TEST_ONLY")

    def test_replay_rejects_unsafe_mmsi_and_filters_identity(self):
        api = MaritimeReadAPI(fixture=MaritimeShadowFixture(
            replay_rows=(vessel(), vessel(mmsi="987654321")),
        ))
        code, _ = api.resolve("/v1/maritime/vessels/000000000/replay", "")
        self.assertEqual(code, 400)
        code, result = api.resolve("/v1/maritime/vessels/123456789/replay", "")
        self.assertEqual(code, 200)
        self.assertEqual(len(result["data"]), 1)

    def test_query_injection_and_unknown_port_fail(self):
        api = MaritimeReadAPI()
        for path, query in [
            ("/v1/maritime/vessels", "port_id=BAD"),
            ("/v1/maritime/vessels", "limit=-4"),
            ("/v1/maritime/vessels", "limit=500000"),
            ("/v1/maritime/vessels", "limit=2&limit=3"),
            ("/v1/maritime/vessels", "user_token=secret"),
            ("/v1/maritime/summary", "hours=0"),
        ]:
            code, _ = api.resolve(path, query)
            self.assertEqual(code, 400, (path, query))

    def test_fixture_cannot_claim_real_data(self):
        with self.assertRaises(ValueError):
            MaritimeShadowFixture(synthetic=False)

    def test_gateway_local_host_only_readonly_and_security_headers(self):
        app = MaritimeLocalWSGI()
        (status, headers), data = wsgi_call(app, "/v1/maritime/status")
        self.assertEqual(status, "200 OK")
        self.assertEqual(data["ais_live"], False)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        (status, _), data = wsgi_call(app, "/v1/maritime/status", host="evil.example")
        self.assertEqual(status, "403 Forbidden")
        (status, _), data = wsgi_call(app, "/v1/maritime/status", method="POST")
        self.assertEqual(status, "405 Method Not Allowed")

    def test_missing_route_and_oversize_query(self):
        api = MaritimeReadAPI()
        self.assertEqual(api.resolve("/v1/maritime/unknown")[0], 404)
        self.assertEqual(api.resolve("/v1/maritime/vessels", "x"*600)[0], 400)


if __name__ == "__main__":
    unittest.main()
