import unittest
from datetime import datetime,timezone
from nivon.noaa_roni import ErroRONI,importar_roni_ascii,classificar_episodios_roni


def source():
    # Estrutura NOAA CPC RONI ERSSTv6. 1950 é pequeno trecho de origem real
    # seguido de valores de fixture, não um dataset observado em produção.
    a=[]
    from math import sin
    for y in range(1950,1953):
        for m,season in enumerate(("DJF","JFM","FMA","MAM","AMJ","MJJ",
                                   "JJA","JAS","ASO","SON","OND","NDJ"),1):
            v=-1.19 if y==1950 and m==1 else (0.7 if y==1951 and 4<=m<=9 else sin(m+y))
            a.append(f"{season} {y} {v:.2f}")
    return ("SEAS   YR  ANOM\n"+"\n".join(a)+"\n").encode("ascii")


class TestNOAARONI(unittest.TestCase):
    def fetch(self,**opts):
        args={"raw":source(),"coletado_em":"2026-10-20T12:00:00Z"}
        args.update(opts)
        return importar_roni_ascii(**args)

    def test_mapping_rolling_3month_season(self):
        p=self.fetch()
        self.assertEqual(p["quantidade"],36)
        self.assertEqual(p["registros"][0]["temporada"],"DJF")
        self.assertEqual(p["registros"][0]["competencia_centro"],"1950-01")
        self.assertEqual(p["registros"][11]["competencia_centro"],"1950-12")
        self.assertFalse(p["pode_treinar_modelo_point_in_time"])

    def test_episodio_requer_5_temporadas(self):
        p=self.fetch()
        result=classificar_episodios_roni(p)
        self.assertTrue(any(x["tipo"]=="EL_NINO" and x["temporadas"]>=6 for x in result["eventos"]))
        self.assertFalse(result["modelo_de_previsao_validado"])

    def test_ano_repetido_e_lacuna_rejeitados(self):
        s=source().decode().splitlines()
        with self.assertRaises(ErroRONI):
            self.fetch(raw=("\n".join([s[0]]+s[2:])+"\n").encode())
        with self.assertRaises(ErroRONI):
            self.fetch(raw=("\n".join(s+[s[-1]])+"\n").encode())

    def test_arquivo_oni_nao_se_passar_por_roni(self):
        with self.assertRaises(ErroRONI):
            self.fetch(versao_ersst="5")
        with self.assertRaises(ErroRONI):
            self.fetch(raw=source().replace(b"SEAS   YR  ANOM",b"ONI  ANOMALY"))

    def test_sem_timestamp_publicacao_inventado(self):
        p=self.fetch()
        self.assertEqual({x["publicado_em"] for x in p["registros"]},{None})
        self.assertEqual({x["disponivel_asof"] for x in p["registros"]},{False})

    def test_serie_de_revisao_tem_mes_provisorio(self):
        a=[]
        for year in range(2024,2027):
            for month,s in enumerate(("DJF","JFM","FMA","MAM","AMJ","MJJ",
                                      "JJA","JAS","ASO","SON","OND","NDJ"),1):
                if year==2026 and month>9:break
                a.append(f"{s} {year} 0.10")
        p=self.fetch(raw=("SEAS YR ANOM\n"+"\n".join(a)).encode())
        self.assertTrue(p["registros"][-1]["recente_ainda_revisavel"])
        self.assertTrue(p["registros"][-2]["recente_ainda_revisavel"])
        self.assertFalse(p["registros"][-3]["recente_ainda_revisavel"])

if __name__=="__main__":unittest.main()
