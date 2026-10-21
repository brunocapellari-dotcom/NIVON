"""Regressões de integração de motores históricos e dependências da PR #9."""
import hashlib
import json
import unittest
from pathlib import Path

from nivon.registro_motores import MODULOS

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf8"))


def blob_sha1(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


class TestHistoricosMeteoHidroIntegrados(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load("config/integracao_historicos_meteo_hidro.v1.json")
        cls.engines = load("config/motores_inteligencia.v1.json")
        cls.sources = load("config/fontes_nivon_master.v1.json")

    def test_origem_git_original_preservada_ou_alterada_intencionalmente(self):
        provenance = self.manifest["upstream_git_blobs"]
        self.assertEqual(len(provenance), 10)
        updated = []
        for x in provenance:
            path = ROOT / x["path"]
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            sha = blob_sha1(path.read_bytes())
            if x["modified_after_transplant"]:
                self.assertNotEqual(sha, x["sha"])
                updated.append(x["path"])
            else:
                self.assertEqual(sha, x["sha"])
        self.assertEqual(set(updated), {
            "src/nivon/historico_vintages.py",
            "tests/test_historico_vintages.py",
        })

    def test_registro_e_fontes_continuam_desligados(self):
        fronts = {f["front_id"]: f for f in self.engines["engines"]}
        for front in self.engines["engines"]:
            for flag in ("operational_enabled", "scheduled_enabled",
                         "inputs_reais_homologados", "previsao_homologada"):
                self.assertIs(front[flag], False)
            self.assertEqual(len(front["entrypoints"]), len(set(front["entrypoints"])))
        required = {
            "METEOROLOGIA": (
                "nivon.noaa_roni:importar_roni_ascii",
                "nivon.noaa_roni:classificar_episodios_roni",
                "nivon.confronto_janelas_fisicas:confrontar_chuva_janelas_equivalentes",
                "nivon.analogos_historicos:encontrar_anos_analogos",
                "nivon.historico_vintages:normalizar_edicao",
            ),
            "CLIMA_HIDRO": (
                "nivon.confronto_janelas_fisicas:confrontar_chuva_janelas_equivalentes",
                "nivon.historico_vintages:normalizar_edicao",
            ),
        }
        for fid, entries in required.items():
            self.assertTrue(set(entries).issubset(fronts[fid]["entrypoints"]))
            for ep in entries:
                mod = ep.split(":")[0].removeprefix("nivon.")
                self.assertIn(mod, MODULOS)
                self.assertTrue((ROOT / "src" / "nivon" / (mod + ".py")).is_file())
        datasets = self.sources["datasets"]
        self.assertEqual(len(datasets), len({d["id"] for d in datasets}))
        self.assertNotIn("NOAA_ENSO_RONI", {d["id"] for d in datasets})
        self.assertEqual(self.manifest["missing_canonical_dataset"], "NOAA_ENSO_RONI")
        self.assertFalse(self.manifest["collectors_operational"])
        self.assertFalse(self.manifest["forecast_skill_approved"])

    def test_noaa_roni_nao_e_hindcast_asof(self):
        from nivon.noaa_roni import importar_roni_ascii
        seasons = ("DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ",
                   "JJA", "JAS", "ASO", "SON", "OND", "NDJ")
        content = "SEAS YR ANOM\n" + "\n".join(
            f"{season} {year} 0.10"
            for year in (1950, 1951)
            for season in seasons) + "\n"
        result = importar_roni_ascii(
            raw=content.encode("ascii"), coletado_em="2026-10-20T12:00:00Z")
        self.assertFalse(result["pode_treinar_modelo_point_in_time"])
        self.assertFalse(result["vintages_de_publicacao_homologadas"])
        self.assertTrue(all(not row["disponivel_asof"] for row in result["registros"]))

    def test_analogos_sao_descritivos_sem_skill_autorizado(self):
        from nivon.analogos_historicos import encontrar_anos_analogos
        hist = {
            year: {
                "disponivel_em": f"{year + 1}-01-01T12:00:00Z",
                "variaveis": {
                    "chuva": 100 + idx * 3,
                    "temperatura": 25 + idx / 10,
                    "enso": -1 + idx / 4,
                }
            }
            for idx, year in enumerate(range(2010, 2020))
        }
        res = encontrar_anos_analogos(
            ano_alvo=2026, emitido_em="2026-10-21T12:00:00Z",
            variaveis_atuais={"chuva": 112, "temperatura": 25.4, "enso": 0},
            historico=hist, fonte_id="NOAA_RONI_TESTE", top_n=3)
        self.assertEqual(res["estado"], "ANALOGOS_DESCRITIVOS_NAO_PREDITIVOS")
        self.assertNotIn("probabilidade", res)
        self.assertEqual(res["analogos"][0]["ano"], 2014)


if __name__ == "__main__":
    unittest.main()
