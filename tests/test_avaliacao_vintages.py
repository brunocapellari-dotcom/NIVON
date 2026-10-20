"""Backtesting preditivo auditável com datas as-of e vintages. Dados sintéticos."""
import unittest

from nivon.avaliacao_vintages import (
    validar_vintages, selecionar_asof, avaliar_asof, ErroVintage,
)

SOURCE="CONAB_SERIES_TESTE"


def montar(n=36):
    rows=[]
    for i in range(n):
        ano=2022+i//12
        mes=i%12+1
        rows.append({
            "fonte_id":SOURCE,
            "competencia":f"{ano:04d}-{mes:02d}",
            "valor":float(100+i),
            "publicacao":f"{ano:04d}-{mes:02d}-25T15:00:00+00:00",
            "coleta":f"{ano:04d}-{mes:02d}-26T15:00:00+00:00",
            "evidencia":f"SHA_FIXTURE_{i}",
        })
    return rows


def folds():
    return [
        {"competencia_alvo":"2024-10",
         "origem":"2024-09-30T22:00:00+00:00",
         "avaliacao":"2024-11-01T12:00:00+00:00"},
        {"competencia_alvo":"2024-11",
         "origem":"2024-10-31T22:00:00+00:00",
         "avaliacao":"2024-12-01T12:00:00+00:00"},
        {"competencia_alvo":"2024-12",
         "origem":"2024-11-30T22:00:00+00:00",
         "avaliacao":"2025-01-01T12:00:00+00:00"},
    ]


def trend(serie,h):
    return [serie[-1][1]+1]


class TestValidacaoVintage(unittest.TestCase):
    def test_walk_forward_sempre_sem_promocao_automatica(self):
        x=avaliar_asof(montar(),cortes=folds(),backend=trend)
        self.assertEqual(x["n_origens"],3)
        self.assertEqual(x["mae_modelo"],0)
        self.assertGreater(x["mae_referencia_sazonal"],0)
        self.assertTrue(x["superou_referencia"])
        self.assertFalse(x["publicar_previsao"])
        self.assertFalse(x["licenca_confirmada"])
        self.assertTrue(x["look_ahead_blocked"])

    def test_revisao_futura_nao_vaza_para_origem(self):
        base=montar()
        revisao={**base[12],"valor":999999.0,
                 "publicacao":"2024-12-20T00:00:00+00:00",
                 "coleta":"2024-12-21T00:00:00+00:00",
                 "evidencia":"REVISADO_DEPOIS"}
        reg,source=validar_vintages(base+[revisao])
        tr=selecionar_asof(reg,corte="2024-09-30T22:00:00+00:00",
                          ate_competencia="2024-09")
        self.assertEqual(dict(tr)["2023-01"],112.0)
        with_revision=avaliar_asof(base+[revisao],cortes=folds(),backend=trend)
        self.assertEqual(with_revision["mae_modelo"],0)

    def test_revisao_realmente_visivel_apos_publicacao_e_coleta(self):
        base=montar()
        rev={**base[0],"valor":200.0,"publicacao":"2024-12-20T00:00:00+00:00",
             "coleta":"2024-12-21T00:00:00+00:00","evidencia":"REV"}
        rows,_=validar_vintages(base+[rev])
        old=dict(selecionar_asof(rows,corte="2024-12-19T00:00:00+00:00",
                                ate_competencia="2022-01"))
        new=dict(selecionar_asof(rows,corte="2024-12-22T00:00:00+00:00",
                                ate_competencia="2022-01"))
        self.assertEqual(old["2022-01"],100)
        self.assertEqual(new["2022-01"],200)

    def test_fonte_incorreta_bloqueada(self):
        records=montar()
        records[0]["fonte_id"]="MERCADO_DISTINTO"
        with self.assertRaises(ErroVintage):
            avaliar_asof(records,cortes=folds(),backend=trend)

    def test_sem_data_publicacao_rejeitado(self):
        records=montar()
        records[0].pop("publicacao")
        with self.assertRaises(ErroVintage):
            validar_vintages(records)

    def test_coleta_anterior_publicacao_rejeitada(self):
        records=montar()
        records[0]["coleta"]="2022-01-20T00:00:00+00:00"
        with self.assertRaises(ErroVintage):
            validar_vintages(records)

    def test_vintage_com_mes_duplicado_rejeitada(self):
        rows=montar()
        with self.assertRaises(ErroVintage):
            validar_vintages(rows+[rows[0]])

    def test_resultado_nao_finito_rejeitado(self):
        with self.assertRaises(ErroVintage):
            avaliar_asof(montar(),cortes=folds(),backend=lambda s,h:[float("nan")])
        with self.assertRaises(ErroVintage):
            avaliar_asof(montar(),cortes=folds(),backend=lambda s,h:[-2.0])

    def test_origem_nao_pode_ser_futura_ao_alvo(self):
        f=folds()
        f[0]["origem"]="2024-10-15T00:00:00+00:00"
        with self.assertRaises(ErroVintage):
            avaliar_asof(montar(),cortes=f,backend=trend)

    def test_alvo_sem_observacao_na_avaliacao_bloqueia(self):
        records=montar()
        records[-1]["publicacao"]="2025-02-20T00:00:00+00:00"
        records[-1]["coleta"]="2025-02-21T00:00:00+00:00"
        with self.assertRaises(ErroVintage):
            avaliar_asof(records,cortes=folds(),backend=trend)

    def test_treino_com_atraso_na_publicacao_nao_projeta_1_mes_incorreto(self):
        records=montar()
        # Setembro de 2024 ainda não está disponível na origem do fold de outubro
        records[32]["publicacao"]="2024-10-02T00:00:00+00:00"
        records[32]["coleta"]="2024-10-03T00:00:00+00:00"
        with self.assertRaises(ErroVintage):
            avaliar_asof(records,cortes=folds(),backend=trend)

    def test_versao_futura_target_nao_substitui_real_observado(self):
        records=montar()
        new={**records[33],"valor":99999.,
             "publicacao":"2025-01-05T00:00:00+00:00",
             "coleta":"2025-01-06T00:00:00+00:00",
             "evidencia":"REV_DEPOIS_AVALIACAO"}
        x=avaliar_asof(records+[new],cortes=folds(),backend=trend)
        self.assertEqual(x["folds"][0]["observado"],133.0)

    def test_nao_presume_vintage_de_dado_final(self):
        final=[{"competencia":f"{2022+i//12}-{i%12+1:02d}","valor":i}
               for i in range(36)]
        with self.assertRaises(ErroVintage):
            avaliar_asof(final,cortes=folds(),backend=trend)


if __name__=="__main__":
    unittest.main()
