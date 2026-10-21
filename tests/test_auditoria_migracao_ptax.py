"""Migração PTAX: comparação lado a lado, sem alterar rotina de produção.

Toda referência a REAL_AUTORIZADO aqui usa autorização FALSA E ISOLADA
exclusivamente para verificar regras do código; não autentica dados BCB.
"""
import copy
import json
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from hashlib import sha256

from nivon.auditoria_migracao_ptax import (
    ErroParidadePTAX, auditar_migracao_ptax, comparar_indicadores_ptax,
)
from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.pipeline_api_dados import ingerir_json_local
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_raw_sqlite import guardar_raw_ptax
from nivon.registro_snapshots import abrir_registro
from nivon.indicador_ptax import indicador_ptax_sqlite
from nivon.ptax_historico_decimal import selecionar_ptax_decimal_asof


PLAN = planejar_consultas_ptax(
    moeda="USD", inicio="2026-10-19", fim="2026-10-20",
)[0]
T = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
CAT = {"datasets": [{
    "id":"BCB_PTAX", "source_id":"BCB",
    "enabled":True, "collection_authorized":True,
}]}
AUTH = frozenset({"COLETA", "ARMAZENAMENTO"})
RIGHTS = {"BCB_PTAX": {
    "status_direitos":"APROVADA",
    "operacoes":["LEITURA", "PUBLICACAO_DERIVADA"],
}}


def body(compra="5.1000", venda="5.1200", tipo="Fechamento",
         instante="2026-10-20 13:03:00"):
    # Inteiros em texto de JSON, não conversões de precisão via float.
    txt = ('{"value":[{"cotacaoCompra":'+compra+
           ',"cotacaoVenda":'+venda+','
           '"dataHoraCotacao":"'+instante+'"')
    if tipo is not None:
        txt += ',"tipoBoletim":"'+tipo+'"'
    return (txt + '}]}').encode()


def criar_raw_teste(payload, instante=T):
    cap = capturar_ptax_odata(
        PLAN,
        transporte=lambda _: (200, {"content-type":"application/json"}, payload),
        relogio=lambda:instante,
    )
    # TESTE DE FRONTEIRA: a simulação local não confirma transporte TLS.
    return {**cap, "tipo":"REAL_AUTORIZADO",
            "origem_execucao":"HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO"}


def antigo(db, momento=T):
    return indicador_ptax_sqlite(
        db, gerado_em=momento.isoformat(), fontes=RIGHTS,
    )


def novo(db, momento=T):
    return selecionar_ptax_decimal_asof(
        db, corte=momento.isoformat(),
    )


class TestAuditoriaMigracaoPTAX(unittest.TestCase):
    def setUp(self):
        self.legacy = abrir_registro(":memory:")
        self.raw = abrir_registro(":memory:")
        self.addCleanup(self.legacy.close)
        self.addCleanup(self.raw.close)

    def inserir(self, payload_old=None, payload_new=None, data=T,
                only_legacy=False):
        raw_old = payload_old if payload_old is not None else body()
        ingerir_json_local(
            self.legacy, CAT, dataset_id="BCB_PTAX", payload=raw_old,
            plano=PLAN, coletado_em=data.isoformat(),
            tipo="REAL_AUTORIZADO", autorizacoes=AUTH,
            evidencia_direitos="FIXTURE_NAO_REAL",
        )
        if not only_legacy:
            raw_new = payload_new if payload_new is not None else raw_old
            guardar_raw_ptax(
                self.raw, CAT, criar_raw_teste(raw_new, data),
                autorizacoes=AUTH, evidencia_direitos="FIXTURE_NAO_REAL",
            )

    def compare(self, instante=T):
        return auditar_migracao_ptax(
            self.legacy, self.raw, gerado_em=instante.isoformat(),
            fontes=RIGHTS,
        )

    def test_paridade_exata_mesmo_raw_em_bancos_distintos(self):
        self.inserir()
        r = self.compare()
        self.assertEqual(r["status"],"PARIDADE_NUMERICA_MESMA_EDICAO_OFFLINE")
        self.assertTrue(r["mesma_edicao_raw_comprovada"])
        self.assertTrue(r["comparacao_numerica_confirmada"])
        self.assertEqual(r["sha_legado"],r["sha_decimal"])
        self.assertFalse(r["substituicao_automatica_autorizada"])
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["apto_backtest_por_publicacao"])

    def test_equivalencia_valores_sem_mesmo_raw_nao_prova_edicao(self):
        self.inserir(payload_old=body(compra="5.1000"),
                     payload_new=body(compra="5.10000"))
        r=self.compare()
        self.assertEqual(r["status"],
                         "PARIDADE_NUMERICA_SEM_MESMA_EDICAO_COMPROVADA")
        self.assertTrue(r["comparacao_numerica_confirmada"])
        self.assertFalse(r["mesma_edicao_raw_comprovada"])

    def test_diferenca_precos_bloqueia_migracao(self):
        self.inserir(payload_new=body(compra="5.1100"))
        r=self.compare()
        self.assertEqual(r["status"],"DIVERGENCIA_PTAX_BLOQUEADA")
        self.assertIn("cotacao_compra",r["motivos"])
        self.assertFalse(r["comparacao_numerica_confirmada"])

    def test_decimal_com_cinco_casas_nao_passara_por_quatro(self):
        self.inserir(payload_new=body(compra="5.10001"))
        r=self.compare()
        self.assertEqual(r["status"],"DIVERGENCIA_PTAX_BLOQUEADA")
        self.assertIn("precisao_decimal_superior_ao_legado",r["motivos"])

    def test_timestamp_diferente_bloqueia(self):
        self.inserir(payload_new=body(instante="2026-10-20 13:04:00"))
        r=self.compare()
        self.assertEqual(r["status"],"DIVERGENCIA_PTAX_BLOQUEADA")
        self.assertIn("referencia_temporal",r["motivos"])

    def test_tipo_boletim_diferente_bloqueia(self):
        self.inserir(payload_new=body(tipo="Intermediário"))
        r=self.compare()
        self.assertEqual(r["status"],"DIVERGENCIA_PTAX_BLOQUEADA")
        self.assertIn("tipo_boletim",r["motivos"])

    def test_lado_decimal_ainda_ausente_e_incompleto(self):
        self.inserir(only_legacy=True)
        r=self.compare()
        self.assertEqual(r["status"],"COMPARACAO_INCOMPLETA")
        self.assertFalse(r["substituicao_automatica_autorizada"])

    def test_corte_temporal_antes_da_coleta_e_incompleto(self):
        self.inserir()
        r=self.compare(T-timedelta(minutes=1))
        self.assertEqual(r["status"],"COMPARACAO_INCOMPLETA")

    def test_sem_direitos_nao_consulta_nem_promove(self):
        self.inserir()
        r=auditar_migracao_ptax(
            self.legacy,self.raw,gerado_em=T.isoformat(),fontes={},
        )
        self.assertEqual(r["status"],"BLOQUEADO_DIREITOS")
        self.assertFalse(r["substituicao_automatica_autorizada"])

    def test_corrupcao_raw_impede_sucesso(self):
        self.inserir()
        self.raw.execute(
            "UPDATE nivon_ptax_raw_blobs SET dados=?",
            (b'{"value":[]}',),
        )
        with self.assertRaises(ValueError):
            self.compare()

    def test_mock_raw_sintetico_isolado_por_padrao(self):
        raw = body()
        captura = capturar_ptax_odata(
            PLAN,
            transporte=lambda _: (200, {"content-type":"application/json"}, raw),
            relogio=lambda:T,
        )
        guardar_raw_ptax(self.raw, {"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]},
                        captura)
        result = selecionar_ptax_decimal_asof(self.raw,corte=T.isoformat())
        self.assertEqual(result["status"],"SEM_RAW_PTAX_ATE_CORTE")
        r=auditar_migracao_ptax(
            self.legacy,self.raw,gerado_em=T.isoformat(),fontes=RIGHTS,
        )
        self.assertEqual(r["status"],"COMPARACAO_INCOMPLETA")

    def test_comparador_puro_rejeita_alegacao_publicacao(self):
        self.inserir()
        old, new=antigo(self.legacy), novo(self.raw)
        new["apto_backtest_por_publicacao"]=True
        r=comparar_indicadores_ptax(old,new)
        self.assertEqual(r["status"],"DIVERGENCIA_PTAX_BLOQUEADA")
        self.assertIn("alegacao_publicacao_sem_prova",r["motivos"])

    def test_comparador_rejeita_moeda_errada(self):
        self.inserir()
        old, new=antigo(self.legacy), novo(self.raw)
        r=comparar_indicadores_ptax(old,new,moeda="EUR")
        self.assertEqual(r["status"],"DIVERGENCIA_PTAX_BLOQUEADA")

    def test_sem_efeitos_colaterais_em_tabelas_legadas(self):
        self.inserir()
        antes=(self.legacy.execute("SELECT COUNT(*) FROM nivon_observacoes_api")
               .fetchone()[0],self.raw.execute(
               "SELECT COUNT(*) FROM nivon_ptax_raw_capturas").fetchone()[0])
        self.compare()
        depois=(self.legacy.execute("SELECT COUNT(*) FROM nivon_observacoes_api")
                .fetchone()[0],self.raw.execute(
                "SELECT COUNT(*) FROM nivon_ptax_raw_capturas").fetchone()[0])
        self.assertEqual(antes,depois)

    def test_bancos_invalidos_bloqueados(self):
        with self.assertRaises(ErroParidadePTAX):
            auditar_migracao_ptax(None,self.raw,gerado_em=T.isoformat(),
                                 fontes=RIGHTS)
        with self.assertRaises(ErroParidadePTAX):
            auditar_migracao_ptax(self.legacy,self.raw,gerado_em=T.isoformat(),
                                 fontes=RIGHTS,idade_maxima_horas=True)


if __name__=="__main__":
    unittest.main()
