import unittest
from datetime import date
from nivon.nasa_power_nivon import url_diaria,normalizar_resposta,coletar_diario
from nivon.qualidade_cientifica import ErroCientifico


class TestNASA_POWER(unittest.TestCase):
    def payload(self):
        return {"type":"Feature","geometry":{"coordinates":[-55.6,-12.4]},
            "properties":{"parameter":{"PRECTOTCORR":{"20261001":4.5,"20261002":-999},
                                        "T2M":{"20261001":27.1,"20261002":28.4}}}}

    def test_url_segura_sem_query_livre(self):
        s=url_diaria(latitude=-12.4,longitude=-55.6,
            inicio=date(2026,10,1),fim=date(2026,10,2),
            parametros=("PRECTOTCORR","T2M"))
        self.assertTrue(s.startswith("https://power.larc.nasa.gov/api/temporal/daily/point?"))
        self.assertIn("start=20261001",s)

    def test_parser_distingue_estimado_de_observado(self):
        url=url_diaria(latitude=-12.4,longitude=-55.6,
            inicio=date(2026,10,1),fim=date(2026,10,2),
            parametros=("PRECTOTCORR","T2M"))
        rows=normalizar_resposta(self.payload(),parametros=("PRECTOTCORR","T2M"),
             inicio=date(2026,10,1),fim=date(2026,10,2),
             coletado_em="2026-10-20T12:00:00Z",fonte_url=url)
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]["natureza"],"ESTIMADO")
        self.assertIsNone(rows[0]["publicacao"])
        self.assertEqual([r["valor"] for r in rows if r["variavel"]=="PRECTOTCORR" and r["competencia"]=="2026-10-02"],[None])

    def test_direitos_sem_homologacao_bloqueiam_rede(self):
        with self.assertRaises(PermissionError):
            coletar_diario(latitude=-12.4,longitude=-55.6,
                inicio=date(2026,10,1),fim=date(2026,10,2))

    def test_data_janela_e_coordenadas(self):
        with self.assertRaises(ErroCientifico):
            url_diaria(latitude=100,longitude=0,inicio=date(2026,1,1),fim=date(2026,1,2))
        with self.assertRaises(ErroCientifico):
            url_diaria(latitude=0,longitude=0,inicio=date(2025,1,1),fim=date(2026,1,2))
        with self.assertRaises(ErroCientifico):
            url_diaria(latitude=0,longitude=0,inicio=date(2026,1,1),fim=date(2026,1,2),parametros=("BAD",))

    def test_qualidade_nao_inventa_chuva(self):
        p=self.payload()
        p["properties"]["parameter"]["PRECTOTCORR"]["20261001"]=-2.
        with self.assertRaises(ErroCientifico):
            normalizar_resposta(p,parametros=("PRECTOTCORR","T2M"),
                inicio=date(2026,10,1),fim=date(2026,10,2),
                coletado_em="2026-10-20T12:00:00Z",
                fonte_url="https://power.larc.nasa.gov/api/temporal/daily/point")

    def test_mime_nao_autorizado_e_redirecionamento_bloqueados_sem_rede(self):
        p=self.payload()
        p["properties"]["parameter"]["T2M"]["20261001"]=float("nan")
        with self.assertRaises(ErroCientifico):
            normalizar_resposta(p,parametros=("PRECTOTCORR","T2M"),
                inicio=date(2026,10,1),fim=date(2026,10,2),
                coletado_em="2026-10-20T12:00:00Z",
                fonte_url="https://power.larc.nasa.gov/api/temporal/daily/point")


if __name__=="__main__":
    unittest.main()
