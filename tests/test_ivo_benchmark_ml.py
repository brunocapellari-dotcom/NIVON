import unittest
from dataclasses import replace
from datetime import date,datetime,timezone

from nivon.historico import Observacao
from nivon.ivo_benchmark_ml import benchmark_ml_asof
from nivon.ivo_lab_temporal import ErroLab

UTC=timezone.utc


def serie():
    out=[]
    for ano in range(2018,2026):
        for mes in range(1,13):
            ny=ano+int(mes==12); nm=mes%12+1
            out.append(Observacao(
                fonte="CONAB",variavel="PRODUCAO",produto="SOJA",regiao="MT",
                unidade="t",competencia=f"{ano}-{mes:02d}",
                calendario="MENSAL",referencia=date(ano,mes,1),
                publicacao=date(ny,nm,3),coleta=datetime(ny,nm,4,tzinfo=UTC),
                valor=float(100+12*(ano-2018)+mes),natureza="OBSERVADO"))
    return out


def bench(dados,**kw):
    opts=dict(fonte="CONAB",variavel="PRODUCAO",produto="SOJA",
        regiao="MT",unidade="t",inicio="2024-01",fim="2024-06",
        corte_avaliacao=datetime(2025,2,1,tzinfo=UTC),
        dados_autorizados=True, backend=lambda s,h:s[-1][1]+h)
    opts.update(kw)
    return benchmark_ml_asof(dados,**opts)


class TestIVOBacktestML(unittest.TestCase):
    def test_seis_folds_e_baseline(self):
        v=bench(serie())
        self.assertEqual(v["estado"],"BENCHMARK_ML_ASOF_NAO_HOMOLOGADO")
        self.assertEqual(v["folds_validos"],6)
        self.assertEqual(len(v["folds_ignorados"]),0)
        self.assertEqual(len({x["hash_treino_asof"] for x in v["folds"]}),6)
        self.assertFalse(v["modelo_homologado"])
        self.assertFalse(v["promocao_automatica"])
        self.assertIsNotNone(v["mae_modelo"])

    def test_licenca_requer_flag(self):
        with self.assertRaises(PermissionError):
            bench(serie(),dados_autorizados=False)

    def test_apos_a_emissao_revisao_nao_altera_treino(self):
        s=serie()
        antes=bench(s)
        original=next(x for x in s if x.competencia=="2023-05")
        revision=replace(original,valor=20000.,edicao="posterior",
            publicacao=date(2025,1,5),
            coleta=datetime(2025,1,6,tzinfo=UTC))
        depois=bench(s+[revision])
        self.assertEqual(
            [x["hash_treino_asof"] for x in antes["folds"]],
            [x["hash_treino_asof"] for x in depois["folds"]])

    def test_corte_sem_resultados_nao_atualiza_metrica(self):
        v=benchmark_ml_asof(serie(),
            fonte="CONAB",variavel="PRODUCAO",produto="SOJA",
            regiao="MT",unidade="t",inicio="2024-01",fim="2024-06",
            corte_avaliacao=datetime(2024,2,1,tzinfo=UTC),
            dados_autorizados=True,backend=lambda s,h:s[-1][1])
        self.assertEqual(v["folds_validos"],0)
        self.assertIsNone(v["mae_modelo"])
        self.assertGreaterEqual(len(v["folds_ignorados"]),6)

    def test_nao_avalia_bloqueios_com_dados_ausentes(self):
        s=[x for x in serie() if x.competencia!="2023-10"]
        v=bench(s)
        self.assertLess(v["folds_validos"],6)
        self.assertGreater(len(v["folds_ignorados"]),0)

    def test_horizonte_depois_periodo_canonico(self):
        with self.assertRaises(ErroLab):
            benchmark_ml_asof(serie(),fonte="CONAB",variavel="PRODUCAO",
                produto="SOJA",regiao="MT",unidade="t",
                inicio="2024-01",fim="2026-10",
                corte_avaliacao=datetime(2027,1,1,tzinfo=UTC),
                dados_autorizados=True,backend=lambda s,h:100.)


if __name__=="__main__":
    unittest.main()
