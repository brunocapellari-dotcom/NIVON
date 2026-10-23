"""PortWatch: consulta ArcGIS real, fixtures inteiramente inventadas."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from nivon.portwatch_fluxos import (
    PASSAGENS, consulta_url, normalizar, HistoricoPortWatch, baixar_pagina, PortWatchErro
)

COLETA = "2026-10-22T23:00:00Z"

class FluxosPortWatch(unittest.TestCase):
    def exemplo(self, total=12):
        return json.dumps({"exceededTransferLimit": False, "features": [
            {"attributes": {"portname": "Strait of Hormuz", "portid": "CHOKEPOINT_TEST",
            "date": "2026-10-20", "n_total": total, "n_dry_bulk": 3, "n_tanker": 4,
            "capacity": 123456}}]}).encode()

    def test_contrato_url_restrito(self):
        url = consulta_url(passagens=["hormuz", "suez"], inicio="2026-10-01", fim="2026-10-20")
        query = parse_qs(urlsplit(url).query)
        self.assertIn("portname IN", query["where"][0])
        self.assertIn("date >= DATE '2026-10-01'", query["where"][0])
        self.assertIn("Suez Canal", query["where"][0])
        with self.assertRaises(PortWatchErro):
            consulta_url(passagens=["arbitrary"], inicio="2026-10-01", fim="2026-10-20")
        with self.assertRaises(PortWatchErro):
            consulta_url(passagens=["hormuz"], inicio="2026-01-01", fim="2026-10-20")
        with self.assertRaises(PermissionError):
            baixar_pagina(url)

    def test_normalizar_sem_confundir_capacidade_e_tonelagem(self):
        rows, more = normalizar(self.exemplo(), consultadas=["hormuz"], coletado_em=COLETA)
        self.assertEqual(rows[0]["transitos_ais"], 12)
        self.assertEqual(rows[0]["volume_transito_estimado_t"], 123456)
        self.assertIsNone(rows[0]["volume_realizado_t"])
        self.assertFalse(rows[0]["operacoes_confirmadas"])
        self.assertFalse(more)

    def test_idempotencia_e_revisoes_historicas(self):
        db = HistoricoPortWatch()
        rows, _ = normalizar(self.exemplo(), consultadas=["hormuz"], coletado_em=COLETA)
        self.assertEqual(db.inserir(rows), 1)
        self.assertEqual(db.inserir(rows), 0)
        changed, _ = normalizar(self.exemplo(13), consultadas=["hormuz"], coletado_em=COLETA)
        self.assertEqual(db.inserir(changed), 1)
        self.assertEqual(db.quantidade(), 2)
        db.fechar()

    def test_erro_metrica_nula_ou_maliciosa(self):
        bad = json.loads(self.exemplo())
        bad["features"][0]["attributes"]["n_total"] = -3
        with self.assertRaises(PortWatchErro):
            normalizar(json.dumps(bad).encode(), consultadas=["hormuz"], coletado_em=COLETA)
        bad["features"][0]["attributes"]["n_total"] = 12
        bad["features"][0]["attributes"]["portname"] = "Outro porto"
        with self.assertRaises(PortWatchErro):
            normalizar(json.dumps(bad).encode(), consultadas=["hormuz"], coletado_em=COLETA)

if __name__ == "__main__":
    unittest.main()
