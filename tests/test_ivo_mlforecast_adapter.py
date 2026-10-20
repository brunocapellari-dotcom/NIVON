import unittest
from dataclasses import replace
from datetime import date,datetime,timezone

from nivon.historico import Observacao
from nivon.ivo_lab_temporal import ErroLab
from nivon.ivo_mlforecast_adapter import prever_mlforecast_asof

UTC=timezone.utc


def serie():
    data=[]
    for y in range(2020,2027):
        for m in range(1,13):
            if y==2026 and m>4:
                break
            ya=y+(m==12); ma=m%12+1
            data.append(Observacao(
                fonte="CONAB",variavel="VOLUME",produto="SOJA",regiao="MT",unidade="t",
                calendario="MENSAL",competencia=f"{y}-{m:02d}",
                referencia=date(y,m,1), publicacao=date(ya,ma,3),
                coleta=datetime(ya,ma,4,tzinfo=UTC),
                valor=float(100+y-2020+m),natureza="OBSERVADO"))
    return data


def prever(data,**extras):
    return prever_mlforecast_asof(data,periodo_alvo="2026-06",
            fonte="CONAB",variavel="VOLUME",produto="SOJA",regiao="MT",
            unidade="t",dados_autorizados=True,
            backend=lambda series,h:float(series[-1][1]+h),**extras)


class TestIVOMLForecast(unittest.TestCase):
    def test_treino_historico_e_janela_sem_lookahead(self):
        p=prever(serie())
        self.assertEqual(p["estado"],"CANDIDATO_ML_NAO_HOMOLOGADO")
        self.assertEqual(p["treino_fim"],"2026-04")
        self.assertEqual(p["horizonte_meses_desde_ultima_observacao"],2)
        self.assertEqual(p["treino_meses"],36)
        self.assertEqual(p["baseline_sazonal"],float(100+2025-2020+6))
        self.assertFalse(p["modelo_homologado"])
        self.assertTrue(p["backend_de_teste_injetado"])

    def test_sem_autorizacao_bloqueado(self):
        with self.assertRaises(PermissionError):
            prever_mlforecast_asof(serie(),periodo_alvo="2026-06",
                fonte="CONAB",variavel="VOLUME",produto="SOJA",regiao="MT",
                unidade="t",backend=lambda s,h:100.)

    def test_revisao_futura_nao_altera_features_ou_resultado(self):
        a=serie()
        p1=prever(a)
        old=next(x for x in a if x.competencia=="2025-05")
        revision=replace(old,valor=100000.,edicao="revisada",
            publicacao=date(2026,8,3),
            coleta=datetime(2026,8,4,tzinfo=UTC))
        p2=prever(a+[revision])
        self.assertEqual(p1["hash_treino_asof"],p2["hash_treino_asof"])
        self.assertEqual(p1["estimativa"],p2["estimativa"])

    def test_backfill_tardio_igualmente_nao_finge_captura(self):
        a=serie()
        a=[replace(x,coleta=datetime(2026,9,4,tzinfo=UTC))
           if x.competencia in ("2026-02","2026-03","2026-04") else x for x in a]
        with self.assertRaises(ErroLab):
            prever(a)

    def test_falta_mes_nao_interpolada(self):
        a=[x for x in serie() if x.competencia!="2025-02"]
        with self.assertRaises(ErroLab):
            prever(a)

    def test_rejeita_projecao_como_observacao(self):
        a=serie()
        a[0]=replace(a[0],natureza="PROJETADO")
        with self.assertRaises(ErroLab):
            prever(a)

    def test_valida_estimativa_invalida(self):
        for value in (-1, float("nan"),float("inf"),True):
            with self.subTest(value=value):
                with self.assertRaises(ErroLab):
                    prever_mlforecast_asof(serie(),periodo_alvo="2026-06",
                       fonte="CONAB",variavel="VOLUME",produto="SOJA",
                       regiao="MT",unidade="t",dados_autorizados=True,
                       backend=lambda s,h,value=value:value)

    def test_janela_invalida_e_backend_invalido(self):
        with self.assertRaises(ErroLab):
            prever(serie(),minimo_meses=12)
        with self.assertRaises(ErroLab):
            prever_mlforecast_asof(serie(),periodo_alvo="2026-06",
                   fonte="CONAB",variavel="VOLUME",produto="SOJA",
                   regiao="MT",unidade="t",dados_autorizados=True,backend="not_callable")

    def test_nao_altera_serie_entrada(self):
        a=serie()
        b=list(a)
        prever(a)
        self.assertEqual(a,b)


if __name__=="__main__":
    unittest.main()
