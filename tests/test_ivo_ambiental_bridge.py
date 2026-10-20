import calendar
import unittest
from datetime import date,datetime,timezone
from hashlib import sha256

from nivon.series_ambientais import Ambiental,abrir_ambiental,salvar_lote
from nivon.ivo_ambiental_bridge import ErroPonteAmbiental,resumo_mensal_estacao_asof

UTC=timezone.utc

def dt(y,m,d):
    return datetime(y,m,d,12,tzinfo=UTC)

def registros(*,dias=range(1,29),dataset="INMET_ESTACOES",
       metrica="CHUVA_DIA_MM",unidade="MM",valor=2.,sha=None,
       estacao="A123",natureza="OBSERVADO"):
    sha=sha or sha256((dataset+metrica+str(tuple(dias))).encode()).hexdigest()
    return [Ambiental(
        dataset_id=dataset,estacao_id=estacao,data_local=f"2026-02-{d:02d}",
        metrica=metrica,valor=valor,unidade=unidade,natureza=natureza,
        origem_sha256=sha,referencia="2026-02-28",
        publicado_em=dt(2026,3,3).isoformat(),
        coletado_em=dt(2026,3,4).isoformat(),
        evidencia="EXEMPLO TESTE SINTETICO") for d in dias]


class TestIVOAmbientalBridge(unittest.TestCase):
    def setUp(self):
        self.db=abrir_ambiental()
        self.addCleanup(self.db.close)

    def salvar(self,**kwargs):
        return salvar_lote(self.db,registros(**kwargs))

    def mes(self,**kwargs):
        dados=dict(dataset_id="INMET_ESTACOES",estacao_id="A123",
                   metrica="CHUVA_DIA_MM",mes="2026-02",
                   corte_publicacao=dt(2026,3,5),
                   corte_coleta=dt(2026,3,5))
        dados.update(kwargs)
        return resumo_mensal_estacao_asof(self.db,**dados)

    def test_chuva_mensal_soma_28_dias_sem_inventar_dados(self):
        self.salvar()
        r=self.mes()
        self.assertEqual(r["estado"],"CANDIDATO_MENSAL_COMPLETO_NAO_HOMOLOGADO")
        self.assertEqual(r["dias_esperados"],28)
        self.assertEqual(r["valor_mensal"],56.)
        self.assertEqual(r["regra_calculo"],"SOMA_DIARIA")
        self.assertFalse(r["treino_autorizado"])
        self.assertFalse(r["cobertura_espacial_homologada"])
        self.assertEqual(r["classe_registro"],"SINTETICO")
        self.assertEqual(len(r["hash_evidencia"]),64)

    def test_temperatura_media_de_minimas_nao_soma_celsius(self):
        self.salvar(metrica="TMIN_C",unidade="CELSIUS",valor=-2.)
        r=self.mes(metrica="TMIN_C")
        self.assertEqual(r["regra_calculo"],"MEDIA_MINIMAS_DIARIAS")
        self.assertEqual(r["valor_mensal"],-2.)

    def test_vazao_e_media_nao_soma_28_m3_s(self):
        self.salvar(dataset="ANA_HIDRO",metrica="VAZAO_M3_S",unidade="M3_S",valor=31.)
        r=self.mes(dataset_id="ANA_HIDRO",metrica="VAZAO_M3_S")
        self.assertEqual(r["valor_mensal"],31.)
        self.assertEqual(r["regra_calculo"],"MEDIA_DIARIA")

    def test_mes_incompleto_nao_preenche_com_zero(self):
        self.salvar(dias=range(1,28))
        r=self.mes()
        self.assertEqual(r["estado"],"BLOQUEADO_COBERTURA_DIARIA_INCOMPLETA")
        self.assertEqual(r["dias_ausentes"],1)
        self.assertIsNone(r["valor_mensal"])

    def test_edicao_publicada_depois_do_corte_nao_entra(self):
        self.salvar()
        r=self.mes(corte_publicacao=dt(2026,3,2),corte_coleta=dt(2026,3,5))
        self.assertEqual(r["dias_ausentes"],28)

    def test_coleta_apos_corte_nao_entra(self):
        self.salvar()
        r=self.mes(corte_publicacao=dt(2026,3,3),corte_coleta=dt(2026,3,3))
        self.assertEqual(r["dias_ausentes"],28)

    def test_corte_com_mes_incompleto_rejeita(self):
        self.salvar()
        with self.assertRaises(ErroPonteAmbiental):
            self.mes(corte_publicacao=dt(2026,2,27),corte_coleta=dt(2026,2,28))

    def test_misturar_amostra_sintetica_e_real_bloqueia(self):
        salvar_lote(self.db,registros(dias=range(1,15)))
        salvar_lote(self.db,registros(dias=range(15,29)),
            classe_registro="REAL_AUTORIZADO",
            autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
            direitos_ref="direitos-teste-2026")
        with self.assertRaises(ErroPonteAmbiental):
            self.mes()

    def test_mes_real_declarado_nao_ativa_treinamento(self):
        salvar_lote(self.db,registros(),
            classe_registro="REAL_AUTORIZADO",
            autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
            direitos_ref="direitos-teste-2026")
        x=self.mes()
        self.assertEqual(x["classe_registro"],"REAL_AUTORIZADO")
        self.assertFalse(x["treino_autorizado"])

    def test_dado_informado_nao_vira_observado(self):
        self.salvar(natureza="INFORMADO")
        with self.assertRaises(ErroPonteAmbiental):
            self.mes()

    def test_mes_invalido_rejeitado(self):
        with self.assertRaises(ErroPonteAmbiental):
            self.mes(mes="2026-13")
        with self.assertRaises(ErroPonteAmbiental):
            self.mes(corte_coleta=datetime(2026,3,5))

    def test_estacao_distinta_nao_compoe_mes(self):
        self.salvar(estacao="A123",dias=range(1,15))
        self.salvar(estacao="B456",dias=range(15,29))
        r=self.mes()
        self.assertEqual(r["dias_ausentes"],14)

if __name__=="__main__":
    unittest.main()
