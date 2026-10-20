import json
import unittest
from nivon.nasa_power_diario import ErroPower,planejar_power,normalizar_power_diario

def plano():
    return planejar_power(latitude=-15.6,longitude=-56.1,
          inicio="2025-01-01",fim="2025-01-03",
          parametros=["PRECTOTCORR","T2M_MAX","T2M_MIN"])

def fixture(*,missing=False):
    return json.dumps({"geometry":{"coordinates":[-56.1,-15.6]},
                       "properties":{"parameter":{
        "PRECTOTCORR":{"20250101":10,"20250102":-999 if missing else 0,"20250103":25},
        "T2M_MAX":{"20250101":30,"20250102":29,"20250103":33},
        "T2M_MIN":{"20250101":20,"20250102":19,"20250103":22}
    }}}).encode()

def obter(payload=None,plan=None):
    return normalizar_power_diario(bytes_json=fixture() if payload is None else payload,
        plano=plano() if plan is None else plan,
        sha256="a"*64,coletado_em="2025-01-05T12:00:00Z")

class TestNASA_POWER_UTC(unittest.TestCase):
    def test_plano_oficial_sem_rede(self):
        p=plano()
        self.assertIn("power.larc.nasa.gov",p["url"])
        self.assertIn("time-standard=UTC",p["url"])
        self.assertEqual(p["intervalo_dias"],3)
        self.assertFalse(p["executar"])

    def test_range_e_parametros_controlados(self):
        with self.assertRaises(ErroPower):
            planejar_power(latitude=95,longitude=0,inicio="2025-01-01",fim="2025-01-02")
        with self.assertRaises(ErroPower):
            planejar_power(latitude=-15,longitude=-56,inicio="2023-01-01",fim="2025-12-31")
        with self.assertRaises(ErroPower):
            planejar_power(latitude=-15,longitude=-56,inicio="2025-01-01",
                           fim="2025-01-02",parametros=["CODE_EXEC"])

    def test_serie_diaria_com_metadados(self):
        r=obter()
        self.assertEqual(r["numero_dias"],3)
        self.assertAlmostEqual(r["latitude_grade"],-15.6)
        self.assertAlmostEqual(r["longitude_grade"],-56.1)
        self.assertEqual(r["registros"][0]["valores"]["PRECTOTCORR"],10.)
        self.assertEqual(r["registros"][1]["valores"]["PRECTOTCORR"],0.)
        self.assertFalse(r["apto_previsao_homologada"])

    def test_nao_aceita_grade_fora_da_regiao(self):
        obj=json.loads(fixture())
        obj["geometry"]["coordinates"]=[10,10]
        with self.assertRaises(ErroPower):obter(json.dumps(obj).encode())

    def test_missing_sentinel_nao_vira_zero(self):
        r=obter(fixture(missing=True))
        self.assertIsNone(r["registros"][1]["valores"]["PRECTOTCORR"])
        self.assertIn("PRECTOTCORR",r["registros"][1]["ausentes"])

    def test_chuva_negativa_e_inconsistencia_termica_rejeitadas(self):
        obj=json.loads(fixture())
        obj["properties"]["parameter"]["PRECTOTCORR"]["20250101"]=-1
        with self.assertRaises(ErroPower):obter(json.dumps(obj).encode())
        obj=json.loads(fixture())
        obj["properties"]["parameter"]["T2M_MIN"]["20250101"]=40
        with self.assertRaises(ErroPower):obter(json.dumps(obj).encode())

    def test_sem_series_completas_e_duplicatas_rejeita(self):
        obj=json.loads(fixture())
        del obj["properties"]["parameter"]["PRECTOTCORR"]["20250101"]
        with self.assertRaises(ErroPower):obter(json.dumps(obj).encode())
        payload=b'{"properties":{"parameter":{"PRECTOTCORR":{},"PRECTOTCORR":{}}}}'
        with self.assertRaises(ErroPower):obter(payload)

    def test_nunca_radiacao_solar_bruta_como_rn(self):
        r=obter()
        self.assertFalse(r["conversao_rad_liquida_fao56_realizada"])
        self.assertNotIn("Rn",r["registros"][0]["valores"])

if __name__=="__main__":
    unittest.main()
