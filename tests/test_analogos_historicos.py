import unittest
from nivon.qualidade_cientifica import ErroCientifico
from nivon.analogos_historicos import encontrar_anos_analogos


def historia():
    return {2010+i:{
        "disponivel_em":f"{2011+i}-02-01T12:00:00Z",
        "variaveis":{"chuva_mm":100+i*10., "temperatura_c":22+i*.2,
                     "enso":-1+i*.25}}
        for i in range(10)}


class TestAnalogosHistoricos(unittest.TestCase):
    def call(self,**kwargs):
        arg=dict(ano_alvo=2026,emitido_em="2026-04-01T12:00:00Z",
            variaveis_atuais={"chuva_mm":140.,"temperatura_c":22.8,"enso":0},
            historico=historia(),fonte_id="NASA_POWER+NOAA",top_n=3)
        arg.update(kwargs)
        return encontrar_anos_analogos(**arg)

    def test_ano_mais_parecido_e_sem_probabilidade(self):
        r=self.call()
        self.assertEqual(r["analogos"][0]["ano"],2014)
        self.assertEqual(r["analogos"][0]["distancia_padronizada"],0)
        self.assertEqual(r["estado"],"ANALOGOS_DESCRITIVOS_NAO_PREDITIVOS")
        self.assertNotIn("probabilidade",r)

    def test_corte_exclui_ano_ainda_nao_disponivel(self):
        h=historia()
        h[2014]["disponivel_em"]="2026-05-01T12:00:00Z"
        r=self.call(historico=h)
        self.assertNotEqual(r["analogos"][0]["ano"],2014)

    def test_ano_futuro_bloqueado(self):
        h=historia()
        h[2026]={"disponivel_em":"2026-01-01T12:00:00Z",
                 "variaveis":{"chuva_mm":140.,"temperatura_c":22.8,"enso":0}}
        with self.assertRaises(ErroCientifico):
            self.call(historico=h)

    def test_observacao_incompleta_bloqueada(self):
        h=historia()
        del h[2012]["variaveis"]["enso"]
        with self.assertRaises(ErroCientifico):
            self.call(historico=h)

    def test_historico_insuficiente_reprovado(self):
        h={k:v for k,v in historia().items() if k<2013}
        self.assertEqual(self.call(historico=h)["estado"],"REPROVADO")

    def test_features_sem_variabilidade_reprovadas(self):
        h=historia()
        for row in h.values():
            row["variaveis"]={"chuva_mm":100.,"temperatura_c":22.,"enso":0}
        self.assertEqual(self.call(historico=h)["motivo"],"FATORES_SEM_VARIABILIDADE")


if __name__=="__main__":
    unittest.main()
