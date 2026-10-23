"""Testes sintéticos de armazenamento e planejamento ANA; zero acesso à rede."""
import unittest
from dataclasses import replace
from nivon.ana_contrato import ErroContratoANA, planejar_janelas
from nivon.series_ambientais import (
    Ambiental, ErroAmbiental, abrir_ambiental, salvar_lote,
    consultar_asof, preparar_graus_dia,
)

A="a"*64
B="b"*64

def med(*,hash=A,valor=20.,tipo="TMIN_C",data="2026-10-17",pub="2026-10-18T09:00:00-03:00",
        coleta="2026-10-18T10:00:00-03:00",estacao="A801",dataset="INMET_ESTACOES",
        referencia="2026-10-18"):
    unit={"TMIN_C":"CELSIUS","TMAX_C":"CELSIUS",
          "CHUVA_DIA_MM":"MM","COTA_CM":"CM","VAZAO_M3_S":"M3_S"}[tipo]
    return Ambiental(dataset_id=dataset,estacao_id=estacao,data_local=data,
        metrica=tipo,valor=valor,unidade=unit,natureza="OBSERVADO",
        origem_sha256=hash,referencia=referencia,publicado_em=pub,
        coletado_em=coleta,evidencia="FIXTURE_INMET")

class TestHistoricoAmbiental(unittest.TestCase):
    def setUp(self):
        self.db=abrir_ambiental()
        self.addCleanup(self.db.close)

    def buscar(self,**overrides):
        kw=dict(dataset_id="INMET_ESTACOES",estacao_id="A801",metrica="TMIN_C",
                inicio="2026-10-17",fim="2026-10-17",
                corte_publicacao="2026-10-21T00:00:00Z",
                corte_coleta="2026-10-21T00:00:00Z")
        return consultar_asof(self.db,**(kw|overrides))

    def test_edicao_coletas_idempotentes(self):
        original=med()
        self.assertTrue(salvar_lote(self.db,[original])["nova_edicao"])
        self.assertFalse(salvar_lote(self.db,[original])["nova_coleta"])
        self.assertTrue(salvar_lote(self.db,[replace(original,coletado_em="2026-10-19T11:00:00Z")])["nova_coleta"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM ambiental_medidas").fetchone()[0],1)

    def test_revisao_nunca_vaza_antes_da_publicacao(self):
        salvar_lote(self.db,[med()])
        salvar_lote(self.db,[med(hash=B,valor=24,pub="2026-10-19T10:00:00Z",coleta="2026-10-19T12:00:00Z")])
        antigo=self.buscar(corte_publicacao="2026-10-18T16:00:00Z",corte_coleta="2026-10-19T08:00:00Z")
        novo=self.buscar()
        self.assertEqual(antigo[0]["valor"],20)
        self.assertEqual(novo[0]["valor"],24)

    def test_publicacao_desconhecida_nao_e_dado_disponivel_asof(self):
        salvar_lote(self.db,[med(pub=None)])
        self.assertEqual(self.buscar(),[])

    def test_mesmo_hash_valor_diferente_bloqueia(self):
        salvar_lote(self.db,[med()])
        with self.assertRaises(ErroAmbiental):
            salvar_lote(self.db,[med(valor=22)])
        self.assertEqual(self.buscar()[0]["valor"],20)

    def test_mesma_publicacao_valores_conflitantes_bloqueia(self):
        salvar_lote(self.db,[med()])
        salvar_lote(self.db,[med(hash=B,valor=22,coleta="2026-10-19T12:00:00Z")])
        with self.assertRaises(ErroAmbiental):self.buscar()

    def test_dados_reais_bloqueados_sem_permissoes(self):
        with self.assertRaises(PermissionError):
            salvar_lote(self.db,[med()],classe_registro="REAL_AUTORIZADO")
        with self.assertRaises(ErroAmbiental):
            salvar_lote(self.db,[med()],autorizacoes=frozenset({"ARMAZENAMENTO"}))

    def test_lotes_mistos_e_duplicatas_rejeitados(self):
        with self.assertRaises(ErroAmbiental):salvar_lote(self.db,[med(),med()])
        with self.assertRaises(ErroAmbiental):
            salvar_lote(self.db,[med(),med(hash=B,tipo="TMAX_C",valor=30)])
        self.assertEqual(self.db.execute("SELECT count(*) FROM ambiental_medidas").fetchone()[0],0)

    def test_regras_unidades_nulos_e_datas(self):
        for changes in ({"valor":None},{"valor":True},{"valor":float("nan")},
                        {"unidade":"MM"},{"coletado_em":"2026-10-18T10:00:00"},
                        {"publicado_em":"2026-10-19T11:00:00Z"}):
            with self.assertRaises(ErroAmbiental):replace(med(),**changes)
        self.assertEqual(med(tipo="COTA_CM",dataset="ANA_HIDRO",valor=-20).valor,-20)
        with self.assertRaises(ErroAmbiental):med(tipo="VAZAO_M3_S",dataset="ANA_HIDRO",valor=-1)

    def test_monta_tmin_tmax_sem_preencher_buracos(self):
        a=[med(data=day) for day in ("2026-10-17","2026-10-18")]
        b=[med(tipo="TMAX_C",valor=30,data=day) for day in ("2026-10-17","2026-10-18")]
        salvar_lote(self.db,a+b)
        tmin=self.buscar(fim="2026-10-18")
        tmax=self.buscar(metrica="TMAX_C",fim="2026-10-18")
        self.assertEqual(len(preparar_graus_dia(tmin,tmax)),2)
        with self.assertRaises(ErroAmbiental):preparar_graus_dia(tmin,tmax[1:])

    def test_nao_mistura_estacoes(self):
        am=[{"dataset_id":"INMET_ESTACOES","estacao_id":"A801","metrica":"TMIN_C","data_local":"2026-10-17","valor":21}]
        ax=[{"dataset_id":"INMET_ESTACOES","estacao_id":"A802","metrica":"TMAX_C","data_local":"2026-10-17","valor":32}]
        with self.assertRaises(ErroAmbiental):preparar_graus_dia(am,ax)

class TestANAContrato(unittest.TestCase):
    def test_telemetria_corta_30_dias(self):
        p=planejar_janelas(estacao_id="12345678",data_inicio="2026-01-01",
                           data_fim="2026-03-01",familia="TELEMETRIA_ADOTADA")
        self.assertEqual([x["dias"] for x in p["janelas"]],[30,30])
        self.assertFalse(p["executar"])
        self.assertIn("SSO",p["autenticacao"])

    def test_convencional_corta_366_dias(self):
        p=planejar_janelas(estacao_id="12345678",data_inicio="2024-01-01",
                           data_fim="2025-01-01",familia="CONVENCIONAL_COTAS")
        self.assertEqual([x["dias"] for x in p["janelas"]],[366,1])

    def test_sem_fallback_para_servico_antigo(self):
        with self.assertRaises(ErroContratoANA):
            planejar_janelas(estacao_id="12345678",data_inicio="2024-01-01",
                             data_fim="2024-03-01",familia="SOAP_LEGADO")

if __name__=="__main__":
    unittest.main()
