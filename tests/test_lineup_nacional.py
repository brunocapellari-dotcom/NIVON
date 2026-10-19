import copy
import unittest

from nivon.lineup_nacional import (
    ErroLineupNacional, carregar_escopo, normalizar_linha, consolidar,
)


class TestLineupNacional(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.escopo = carregar_escopo()

    def linha(self, **changes):
        d = {
            "porto_id": "ITAQUI", "navio": "NAVIO TESTE", "duv": "DUV-77",
            "produto": "SOJA EM GRAOS", "lote_id": "LOTE-A",
            "situacao": "PROGRAMADO", "classe_evidencia": "LINEUP_INFORMADO",
            "toneladas_programadas": 50000, "toneladas_realizadas": None,
            "fonte_url": "https://fonte.oficial.example/dados",
            "publicado_em": "2026-10-19T10:00:00-03:00",
            "coletado_em": "2026-10-19T11:00:00-03:00",
        }
        d.update(changes)
        return d

    def test_35_organizados_10_privados(self):
        ports = self.escopo["ports"]
        self.assertEqual(len(ports), 45)
        self.assertEqual(sum(p["kind"] == "PORTO_ORGANIZADO" for p in ports), 35)
        self.assertTrue(all(not p["live_enabled"] for p in ports))
        self.assertIn("MIRITITUBA", {p["id"] for p in ports})
        self.assertIn("SUAPE", {p["id"] for p in ports})

    def test_uma_escala_duas_mercadorias(self):
        result = consolidar([self.linha(), self.linha(produto="MILHO", lote_id="LOTE-B")], self.escopo)
        self.assertEqual(len(result["grupos"]), 2)
        self.assertEqual(sum(r["escalas_distintas_identificadas"] for r in result["grupos"]), 2)

    def test_mesma_linha_duplicada_nao_soma_duas_vezes(self):
        result = consolidar([self.linha(), copy.deepcopy(self.linha())], self.escopo)
        self.assertEqual(result["grupos"][0]["toneladas_programadas_sem_duplicacao"], 50000)
        self.assertEqual(result["grupos"][0]["escalas_distintas_identificadas"], 1)

    def test_sem_duv_volume_nao_conciliavel(self):
        result = consolidar([self.linha(duv=None)], self.escopo)
        self.assertEqual(result["grupos"][0]["toneladas_programadas_sem_duplicacao"], 0)
        self.assertEqual(result["grupos"][0]["linhas_sem_duv"], 1)

    def test_realizacao_exige_fonte_fisica(self):
        with self.assertRaises(ErroLineupNacional):
            normalizar_linha(self.linha(situacao="REALIZADO", toneladas_realizadas=45000), self.escopo)

    def test_realizado_oficial_aceita_com_lote(self):
        r = consolidar([self.linha(situacao="REALIZADO",
                                   classe_evidencia="CARGA_MOVIMENTADA_OFICIAL",
                                   toneladas_realizadas=46000)], self.escopo)
        self.assertEqual(r["grupos"][0]["toneladas_realizadas_sem_duplicacao"], 46000)

    def test_nao_publicar_observacao_futura(self):
        with self.assertRaises(ErroLineupNacional):
            normalizar_linha(self.linha(publicado_em="2026-10-20T11:00:00-03:00"), self.escopo)

    def test_nao_admitir_porto_falso(self):
        with self.assertRaises(ErroLineupNacional):
            normalizar_linha(self.linha(porto_id="PORTO_INVENTADO"), self.escopo)

    def test_nao_somar_lote_duplicado_divergente(self):
        with self.assertRaises(ErroLineupNacional):
            consolidar([self.linha(), self.linha(toneladas_programadas=60000)], self.escopo)

    def test_registro_privado_bloqueado(self):
        d = copy.deepcopy(self.escopo)
        d["ports"][0]["live_enabled"] = True
        from pathlib import Path
        import json
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "portos.json"
            p.write_text(json.dumps(d), encoding="utf-8")
            with self.assertRaises(ErroLineupNacional):
                carregar_escopo(p)


if __name__ == "__main__":
    unittest.main()
