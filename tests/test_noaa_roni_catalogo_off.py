"""NIVON: NOAA CPC RONI registrado sem autorização operacional."""
import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo, ErroCatalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas, montar_plano, ErroRota
from nivon.noaa_roni import importar_roni_ascii


URL = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"
DOC = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/"


class TestNoaaRoniCandidatoGovernado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def get_source(self, d=None):
        catalog = d or self.cat
        return next(x for x in catalog["datasets"] if x["id"] == "NOAA_ENSO_RONI")

    def get_route(self, routes=None):
        return next(x for x in (routes or self.rotas)["entries"]
                    if x["dataset_id"] == "NOAA_ENSO_RONI")

    def test_candidato_e_uma_unica_rota_sem_ativacao(self):
        self.assertEqual(sum(x["id"] == "NOAA_ENSO_RONI"
                             for x in self.cat["datasets"]), 1)
        self.assertEqual(sum(x["dataset_id"] == "NOAA_ENSO_RONI"
                             for x in self.rotas["entries"]), 1)
        d = self.get_source()
        e = self.get_route()
        self.assertEqual(d["source_id"], "NOAA")
        self.assertEqual(d["stage"], "CANDIDATE")
        self.assertEqual(d["cadence"], "MONTHLY")
        self.assertEqual(d["existing_module"],
                         "nivon.noaa_roni:importar_roni_ascii")
        for flag in ("enabled", "collection_authorized",
                     "commercial_redistribution_authorized"):
            self.assertIs(d[flag], False)
        for flag in ("runtime_enabled", "scheduled_enabled"):
            self.assertIs(e[flag], False)
        self.assertIsNone(e["last_verified_data"])
        self.assertEqual(e["collector_class"], "STRUCTURED_FILE")

    def test_rota_exata_e_prova_oficial_sem_confundir_oni(self):
        e = self.get_route()
        self.assertEqual(e["locator"]["kind"], "DIRECT_PUBLIC_FILE")
        self.assertEqual(e["locator"]["url"], URL)
        self.assertEqual(e["locator"]["source_proof"], DOC)
        for gate in ("VERIFY_COLLECTION_RIGHTS", "VERIFY_STORAGE_RIGHTS",
                     "VERIFY_REDISTRIBUTION_RIGHTS",
                     "POINT_IN_TIME_VINTAGE_ARCHIVE",
                     "REAL_SAMPLE_AND_SCHEMA_VALIDATION",
                     "DURABLE_PERSISTENCE_AND_RESTORE"):
            self.assertIn(gate, e["gates_missing"])

    def test_catalogo_integral_e_rotas_validos_com_nova_fonte(self):
        a = validar_catalogo(self.cat)
        b = validar_rotas(self.rotas, self.cat)
        self.assertEqual(a["datasets"], b["datasets"])
        self.assertEqual(b["rotas"], b["datasets"])
        self.assertEqual(b["coletas_ativadas"], 0)
        d = next(x for x in montar_plano(
            self.rotas, self.cat, grupo="CLIMA")
                 if x["dataset"] == "NOAA_ENSO_RONI")
        self.assertFalse(d["programado"])
        self.assertEqual(d["codigo_reutilizavel"],
                         "nivon.noaa_roni:importar_roni_ascii")
        self.assertEqual(d["fonte_especifica"], URL)

    def test_ativacao_de_fonte_candidato_falha_fechado(self):
        for key in ("enabled", "collection_authorized",
                    "commercial_redistribution_authorized"):
            copydoc = copy.deepcopy(self.cat)
            self.get_source(copydoc)[key] = True
            with self.subTest(key=key), self.assertRaises(ErroCatalogo):
                validar_catalogo(copydoc)

    def test_ativacao_de_coleta_na_rota_falha_fechado(self):
        for key in ("runtime_enabled", "scheduled_enabled"):
            doc = copy.deepcopy(self.rotas)
            self.get_route(doc)[key] = True
            with self.subTest(key=key), self.assertRaises(ErroRota):
                validar_rotas(doc, self.cat)

    def test_substituicao_oni_ou_host_nao_noaa_falha(self):
        for wrong in (
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            "https://cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
            "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/v5/",
            "https://fake.example/data/indices/RONI.ascii.txt",
        ):
            doc = copy.deepcopy(self.rotas)
            self.get_route(doc)["locator"]["url"] = wrong
            with self.subTest(url=wrong), self.assertRaises(ErroRota):
                validar_rotas(doc, self.cat)

    def test_dados_retrospectivos_nao_autorizam_hindcast(self):
        seasons = ("DJF","JFM","FMA","MAM","AMJ","MJJ","JJA",
                   "JAS","ASO","SON","OND","NDJ")
        raw = ("SEAS YR ANOM\n" + "\n".join(
            f"{season} {year} 0.1" for year in (1950,1951)
            for season in seasons) + "\n").encode("ascii")
        parsed = importar_roni_ascii(
            raw=raw, coletado_em="2026-10-21T12:00:00Z")
        self.assertEqual(parsed["quantidade"], 24)
        self.assertFalse(parsed["pode_treinar_modelo_point_in_time"])
        self.assertFalse(parsed["vintages_de_publicacao_homologadas"])
        self.assertEqual({e["publicado_em"] for e in parsed["registros"]}, {None})


if __name__ == "__main__":
    unittest.main()
