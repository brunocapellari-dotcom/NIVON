"""Ensaio reverso RAW -> legado em cópia; nenhuma mutação operacional."""
from datetime import datetime, timezone, timedelta
import sqlite3
import unittest

from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.ptax_migracao_reversa import (
    ErroMigracaoReversaPTAX, materializar_visao_legada_em_copia,
)
from nivon.ptax_historico_decimal import selecionar_ptax_decimal_asof
from nivon.ptax_raw_sqlite import guardar_raw_ptax
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.pipeline_api_dados import observar_asof_coleta
from nivon.indicador_ptax import indicador_ptax_sqlite
from nivon.registro_snapshots import abrir_registro

PLANO = planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-19",fim="2026-10-20")[0]
T=datetime(2026,10,20,18,0,tzinfo=timezone.utc)
CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
CAT_TESTE_REAL={"datasets":[{
    "id":"BCB_PTAX","source_id":"BCB",
    "enabled":True,"collection_authorized":True,
}]}
DIREITOS=frozenset({"COLETA","ARMAZENAMENTO"})
FONTES={"BCB_PTAX":{"status_direitos":"APROVADA",
                    "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]}}


def raw(compra="5.10000",venda="5.12000"):
    return ('{"value":[{"cotacaoCompra":'+compra+
            ',"cotacaoVenda":'+venda+
            ',"dataHoraCotacao":"2026-10-20 13:03:00",'
            '"tipoBoletim":"Fechamento"}]}').encode()


def capturar(payload,real=False):
    r=capturar_ptax_odata(
        PLANO,transporte=lambda _: (
            200,{"content-type":"application/json"},payload),
        relogio=lambda:T)
    if real:
        # Somente fixture de teste em memória para exercitar a barreira.
        return {**r,"tipo":"REAL_AUTORIZADO",
                "origem_execucao":"HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO"}
    return r


class TestMigracaoReversaPTAX(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def guardar(self, payload=None, real=False):
        return guardar_raw_ptax(
            self.db,CAT_TESTE_REAL if real else CAT,
            capturar(payload if payload is not None else raw(),real),
            autorizacoes=DIREITOS if real else frozenset(),
            evidencia_direitos="FIXTURE_NAO_REAL" if real else None)

    def migra(self, sha):
        self.db.commit()
        return materializar_visao_legada_em_copia(
            self.db,raw_sha256=sha)

    def test_fluxo_integrado_raw_primeiro_legado_na_copia_e_asof(self):
        r=self.guardar()
        ret=self.migra(r["sha256"])
        self.addCleanup(ret["copia"].close)
        self.assertEqual(ret["status"],
                         "VISAO_LEGADA_MATERIALIZADA_SOMENTE_EM_COPIA")
        self.assertEqual(ret["linhas_compatibilizadas"],1)
        self.assertFalse(ret["banco_original_modificado"])
        self.assertFalse(ret["promocao_editorial_autorizada"])
        self.assertFalse(ret["publicavel"])
        copia=ret["copia"]
        self.assertEqual(
            copia.execute("SELECT schema_versao FROM nivon_snapshots")
            .fetchone()[0],"PTAX_ODATA_RAW_V1")
        self.assertEqual(
            observar_asof_coleta(copia,dataset_id="BCB_PTAX",
                corte_coleta=T.isoformat(),incluir_sinteticos=True)["linhas"],1)
        self.assertEqual(
            selecionar_ptax_decimal_asof(
                copia,corte=T.isoformat(),incluir_sinteticos=True)["compra_decimal"],
            "5.10000")
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='nivon_observacoes_api'").fetchone())

    def test_previa_legacy_real_apenas_fixture_ja_homologada_no_teste(self):
        r=self.guardar(real=True)
        ret=self.migra(r["sha256"])
        self.addCleanup(ret["copia"].close)
        indicadores=indicador_ptax_sqlite(
            ret["copia"],gerado_em=T.isoformat(),fontes=FONTES)
        self.assertEqual(indicadores["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("5,1000",indicadores["indicador"]["valor"])
        # Mapa de direitos é EXCLUSIVAMENTE DE TESTE; não publicar.
        self.assertFalse(ret["promocao_editorial_autorizada"])
        sem_legado=indicador_ptax_sqlite(
            self.db,gerado_em=T.isoformat(),fontes=FONTES)
        self.assertEqual(sem_legado["status"],"BANCO_INDISPONIVEL")

    def test_cinco_casas_depois_da_virgula_bloqueia_troca(self):
        registro=self.guardar(raw(compra="5.10001"))
        with self.assertRaisesRegex(ErroMigracaoReversaPTAX,"perda de casas"):
            self.migra(registro["sha256"])
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE name='nivon_observacoes_api'"
        ).fetchone())

    def test_venda_com_mais_de_quatro_casas_bloqueada(self):
        r=self.guardar(raw(venda="5.12001"))
        with self.assertRaises(ErroMigracaoReversaPTAX):
            self.migra(r["sha256"])

    def test_migracao_nao_aceita_snapshot_sem_raw(self):
        with self.assertRaises(ErroMigracaoReversaPTAX):
            self.migra("b"*64)

    def test_recusa_migracao_duas_vezes_no_mesmo_banco_copia(self):
        r=self.guardar()
        ret=self.migra(r["sha256"])
        self.addCleanup(ret["copia"].close)
        copia=ret["copia"]
        copia.commit()
        with self.assertRaisesRegex(ErroMigracaoReversaPTAX,"já presentes"):
            materializar_visao_legada_em_copia(
                copia,raw_sha256=r["sha256"])

    def test_rejeita_sha_ou_contexto_invalido(self):
        self.guardar()
        self.db.commit()
        for sha in ("", "f"*63, "z"*64):
            with self.subTest(sha=sha),self.assertRaises(ErroMigracaoReversaPTAX):
                materializar_visao_legada_em_copia(
                    self.db,raw_sha256=sha)


if __name__=="__main__":
    unittest.main()
