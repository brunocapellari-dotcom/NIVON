"""Integração marítima: PR #6 + PR #40 sem promover programação a operação.

Os documentos, navios e autorizações usados aqui são inteiramente sintéticos.
"""
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from nivon.catalogo_fontes import carregar_catalogo
from nivon.coleta_web import FonteWeb
from nivon.lineup_nacional import carregar_escopo
from nivon.maritime.ais_stream_client import stream_once
from nivon.maritime.maritime_final_readiness import evaluate_final_readiness
from nivon.maritime.maritime_gateway import (
    MaritimeProgrammedSnapshot, MaritimeReadAPI,
)
from nivon.maritime.official_lineup_bridge import bridge_official_html_document
from nivon.portos_automaticos import ContratoPorto
from nivon.registro_motores import carregar_registro
from nivon.rotas_coleta import carregar_rotas, validar_rotas

SANTOS_URL = (
    "https://www.portodesantos.com.br/informacoes-operacionais/"
    "operacoes-portuarias/navegacao-e-movimento-de-navios/"
    "atracacoes-programadas/"
)


class TestIntegracaoMaritimaPR6PR40(unittest.TestCase):
    def test_preserva_139_datasets_45_portos_e_gate_ais(self):
        catalogo = carregar_catalogo()
        rotas = carregar_rotas()
        escopo = carregar_escopo()
        self.assertEqual(len(catalogo["datasets"]), 139)
        self.assertEqual(len(escopo["ports"]), 45)
        self.assertEqual(validar_rotas(rotas, catalogo)["rotas"], 139)
        dataset = next(x for x in catalogo["datasets"] if x["id"] == "AIS_POSICOES")
        route = next(x for x in rotas["entries"] if x["dataset_id"] == "AIS_POSICOES")
        self.assertFalse(dataset["enabled"])
        self.assertFalse(dataset["collection_authorized"])
        self.assertFalse(dataset["commercial_redistribution_authorized"])
        self.assertIsNone(route["locator"]["url"])
        self.assertFalse(route["runtime_enabled"])
        self.assertFalse(route["scheduled_enabled"])

    def test_registro_maritime_preserva_motores_de_tendencias(self):
        register = carregar_registro()
        front = next(x for x in register["engines"] if x["front_id"] == "MARITIMO")
        entries = front["entrypoints"]
        self.assertIn("nivon.motor_tendencias:tendencia_observada", entries)
        self.assertIn("nivon.motor_tendencias:tendencia_projetada", entries)
        self.assertIn("nivon.maritime.port_call_engine:reconstruct_port_call", entries)
        self.assertIn("nivon.maritime.maritime_eta:estimate_eta", entries)
        self.assertEqual(len(entries), len(set(entries)))
        for flag in ("inputs_reais_homologados", "previsao_homologada",
                     "scheduled_enabled", "operational_enabled"):
            self.assertIs(front[flag], False)

    def test_ais_stream_api_key_nao_substitui_direitos(self):
        with self.assertRaises(PermissionError):
            next(stream_once(api_key="chave-apenas-fixture",
                             bounding_boxes=[[[0.0, 0.0], [1.0, 1.0]]]))

    def test_lineup_programado_nao_se_transforma_em_navio_real_ou_carga(self):
        contract = ContratoPorto(
            porto="SANTOS", modo="HTML_SANTOS_SCHEDULE",
            fonte=FonteWeb(
                fonte_id="TEST_SANTOS_AUTHORITY",
                url=SANTOS_URL,
                dominio_autorizado="www.portodesantos.com.br",
                formato="HTML", status_direitos="APROVADA",
                operacoes_permitidas=frozenset({"COLETA"}),
            ),
        )
        now = datetime.now(timezone.utc)
        eta_local = (now + timedelta(hours=6)).astimezone(
            timezone(timedelta(hours=-3))
        ).strftime("%d/%m/%Y %H:%M")
        captured_at = (now - timedelta(hours=1)).isoformat()
        html = (
            "<html><body><table><thead><tr>"
            "<th>Navio</th><th>IMO</th><th>ETA</th>"
            "<th>DUV</th><th>Local</th><th>Carga</th>"
            "</tr></thead><tbody><tr>"
            "<td>NAVIO TESTE</td><td>9074729</td>"
            f"<td>{eta_local}</td><td>12345</td>"
            "<td>T1</td><td>SOJA</td>"
            "</tr></tbody></table></body></html>"
        ).encode("utf-8")
        document = {
            "conteudo": html, "sha256": hashlib.sha256(html).hexdigest(),
            "url": SANTOS_URL, "fonte_id": "TEST_SANTOS_AUTHORITY",
            "mime": "text/html", "bytes": len(html),
            "capturado_em": captured_at,
        }
        bridge = bridge_official_html_document(contract=contract, document=document)
        self.assertEqual(len(bridge.candidates), 1)
        self.assertFalse(bridge.publication_allowed)
        self.assertFalse(bridge.realized_cargo_claimed)
        with self.assertRaises(PermissionError):
            MaritimeProgrammedSnapshot.from_bridge(bridge)
        staged = MaritimeProgrammedSnapshot.from_bridge(
            bridge, display_authorized=True,
        )
        api = MaritimeReadAPI(programmed=staged)
        code, lineup = api.resolve("/v1/maritime/lineup", "port_id=SANTOS")
        self.assertEqual(code, 200)
        self.assertFalse(lineup["publication_allowed"])
        self.assertEqual(lineup["status"], "SHADOW_LINEUP_ONLY")
        self.assertEqual(lineup["data_origin"], "OFFICIAL_PROGRAMMED_NOT_REALIZED")
        self.assertEqual(lineup["data"][0]["reconciled_state"], "PROGRAMMED")
        self.assertEqual(lineup["data"][0]["evidence_class"], "PROGRAMADO_NAO_REALIZADO")
        code, summary = api.resolve("/v1/maritime/summary", "port_id=SANTOS")
        self.assertEqual(code, 200)
        self.assertEqual(summary["data"]["lineup_calls"], 1)
        self.assertIsNone(summary["data"]["vessels_live"])
        self.assertIsNone(summary["data"]["vessels_berthed"])
        self.assertIsNone(summary["data"]["waiting_p50_hours"])
        self.assertIsNone(summary["data"]["eta_mae_hours"])
        self.assertFalse(summary["publication_allowed"])

    def test_filtro_eta_por_janela_e_contagem_resumo_coerente(self):
        now = datetime.now(timezone.utc)
        entries = (
            {"port_id": "SANTOS", "eta": (now-timedelta(hours=10)).isoformat(),
             "call_id": "PASSADO"},
            {"port_id": "SANTOS", "eta": (now+timedelta(hours=2)).isoformat(),
             "call_id": "DENTRO"},
            {"port_id": "SANTOS", "eta": (now+timedelta(hours=30)).isoformat(),
             "call_id": "FUTURO"},
            {"port_id": "SANTOS", "eta": "sem timestamp", "call_id": "INVALIDO"},
        )
        snapshot = MaritimeProgrammedSnapshot(
            lineup_rows=entries, source_hash="a"*64, port_id="SANTOS",
        )
        api = MaritimeReadAPI(programmed=snapshot)
        status, result = api.resolve(
            "/v1/maritime/lineup", "port_id=SANTOS&past_hours=0&future_hours=6",
        )
        self.assertEqual(status, 200)
        self.assertEqual([x["call_id"] for x in result["data"]], ["DENTRO"])
        status, summary = api.resolve(
            "/v1/maritime/summary", "port_id=SANTOS&hours=1&future_hours=6",
        )
        self.assertEqual(status, 200)
        self.assertEqual(summary["data"]["lineup_calls"], 1)
        self.assertIsNone(summary["data"]["vessels_live"])
        status, longer = api.resolve(
            "/v1/maritime/lineup", "port_id=SANTOS&past_hours=12&future_hours=36",
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            {x["call_id"] for x in longer["data"]}, {"PASSADO", "DENTRO", "FUTURO"},
        )
        self.assertFalse(longer["publication_allowed"])

    def test_default_gateway_e_aprovacao_final_sempre_bloqueados(self):
        api = MaritimeReadAPI()
        status, data = api.resolve("/v1/maritime/status")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "DATA_GATED")
        self.assertFalse(data["ais_live"])
        self.assertFalse(data["lineup_live"])
        self.assertFalse(data["publication_allowed"])
        readiness = evaluate_final_readiness([])
        self.assertFalse(readiness.final_ready)
        self.assertEqual(readiness.status, "BLOCKED")
        self.assertIn("ais_live_five_ports", readiness.blocked_gates)


if __name__ == "__main__":
    unittest.main()
