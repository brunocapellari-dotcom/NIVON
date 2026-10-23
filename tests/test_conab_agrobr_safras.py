"""AgroBR 2.0 safras: consulta por edição, unidades e staging no SQLite.

Integração sintética com API stub; não representa coleta HTTP real CONAB.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from nivon.conab_agrobr_safras import (
    normalizar_safras_agrobr, consultar_safras_agrobr,
    consultar_lote_agrobr, _guardar_staging_sqlite, ErroAgroBRSafras,
)


def linhas(produto="soja",safra="2024/25",levantamento=5,uf="MT"):
    return [{
        "fonte":"CONAB","produto":produto,"safra":safra,"uf":uf,
        "area_plantada":12800.5,"area_colhida":None,
        "produtividade":3570.0,"producao":45698.0,
        "levantamento":levantamento,"data_publicacao":date(2025,2,13),
    }]


def meta(safra="2024/25",numero=5):
    return SimpleNamespace(source_details={"publicacao":{
        "safra":safra,"levantamento":numero,
        "url":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-graos/boletim-da-safra-de-graos/5o-levantamento-safra-2024-25",
        "data_publicacao":"2025-02-13",
    }})


def normalize(frame=None,source=None):
    return normalizar_safras_agrobr(
        frame=linhas() if frame is None else frame,
        meta=meta() if source is None else source,
        produto="soja",safra="2024/25",levantamento=5,uf="MT",
        coletado_em="2026-10-23T13:00:00-04:00",
    )


class API:
    def __init__(self):
        self.calls=[]
    async def safras(self,produto,*,safra,uf,levantamento,return_meta):
        self.calls.append({
            "produto":produto,"safra":safra,"uf":uf,
            "levantamento":levantamento,"return_meta":return_meta,
        })
        return linhas(produto=produto,safra=safra,levantamento=levantamento,uf=uf),meta(
            safra=safra,numero=levantamento
        )


class TestAgroBRContrato(TestCase):
    def test_transforma_unidades_e_sem_prova_asof(self):
        out=normalize()
        self.assertEqual((out["produto"],out["levantamento"],out["uf_filtro"]),("soja",5,"MT"))
        self.assertEqual(out["registros"][0]["area_plantada"],"12800.5")
        self.assertEqual(out["registros"][0]["produtividade"],"3570.0")
        self.assertEqual(out["registros"][0]["producao"],"45698.0")
        self.assertEqual(out["registros"][0]["unidades"]["producao"],"MIL_T")
        self.assertFalse(out["registros"][0]["area_colhida_disponivel"])
        self.assertIsNone(out["raw_conab_sha256"])
        self.assertIsNone(out["registros"][0]["data_disponibilidade_historica"])
        self.assertFalse(out["habilita_backtest"])
        self.assertFalse(out["habilita_treino"])
        self.assertFalse(out["habilita_publicacao"])

    def test_fallback_para_outra_edicao_ou_serie_historica_rejeitado(self):
        for source in (meta(numero=6),meta(safra="2025/26"),
                       SimpleNamespace(source_details={"publicacao":{
                           **meta().source_details["publicacao"],"origem":"serie_historica"
                       }})):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ErroAgroBRSafras,"edição|boletim"):
                    normalize(source=source)

    def test_url_hostil_rejeitada(self):
        bad=meta()
        bad.source_details["publicacao"]["url"]="https://www.gov.br.evil.example/doc"
        with self.assertRaisesRegex(ErroAgroBRSafras,"URL"):
            normalize(source=bad)

    def test_area_colhida_nao_eh_area_plantada(self):
        bad=linhas()
        bad[0]["area_colhida"]=12700.0
        with self.assertRaisesRegex(ErroAgroBRSafras,"área colhida"):
            normalize(frame=bad)

    def test_metricas_nan_e_negativas_rejeitadas(self):
        for badvalue in (float("inf"),-0.1,"NaN",float("nan"),"999999999999999999999"):
            with self.subTest(badvalue=badvalue):
                row=linhas()
                row[0]["producao"]=badvalue
                with self.assertRaisesRegex(ErroAgroBRSafras,"número"):
                    normalize(frame=row)

    def test_uf_incoerente_e_duplicada_rejeitadas(self):
        with self.assertRaisesRegex(ErroAgroBRSafras,"UF/edição"):
            normalize(frame=linhas(uf="PR"))
        x=linhas()
        with self.assertRaisesRegex(ErroAgroBRSafras,"duplicada"):
            normalize(frame=x+x)

    def test_data_de_publicacao_divergente_rejeitada(self):
        x=linhas()
        x[0]["data_publicacao"]=date(2025,2,12)
        with self.assertRaisesRegex(ErroAgroBRSafras,"publicação"):
            normalize(frame=x)

    def test_sem_producao_pode_ter_area_sem_zero_inventado(self):
        x=linhas()
        x[0]["producao"]=None
        normalized=normalize(frame=x)
        self.assertIsNone(normalized["registros"][0]["producao"])
        self.assertFalse(normalized["habilita_publicacao"])

    def test_falha_se_metadado_da_edicao_ausente(self):
        with self.assertRaisesRegex(ErroAgroBRSafras,"MetaInfo"):
            normalize(source=SimpleNamespace(source_details={}))

    def test_sqlite_isola_staging_de_capturas_raw(self):
        p=normalize()
        milho=normalizar_safras_agrobr(
            frame=linhas(produto="milho"),meta=meta(),produto="milho",
            safra="2024/25",levantamento=5,uf="MT",
            coletado_em="2026-10-23T13:00:00-04:00",
        )
        lote={"status":"LOTE_AGROBR_CONAB_SEM_RAW_NEM_VINTAGE",
              "culturas":[p,milho],"habilita_publicacao":False,
              "habilita_backtest":False,"disponibilidade_asof_comprovada":False}
        with tempfile.TemporaryDirectory() as tmp:
            file=str(Path(tmp)/"staging.sqlite")
            one=_guardar_staging_sqlite(file,lote)
            two=_guardar_staging_sqlite(file,lote)
            self.assertEqual((one["gravados"],one["recebidos"],two["duplicatas"]),(2,2,2))
            with sqlite3.connect(file) as db:
                rows=db.execute(
                    "SELECT produto,classe FROM conab_agrobr_staging ORDER BY produto"
                ).fetchall()
            self.assertEqual(rows,[("milho","SEM_RAW_SEM_VINTAGE"),
                                   ("soja","SEM_RAW_SEM_VINTAGE")])
            self.assertFalse(one["habilita_publicacao"])

    def test_staging_rejeita_promocao_direta(self):
        fake={"status":"LOTE_AGROBR_CONAB_SEM_RAW_NEM_VINTAGE",
              "culturas":[normalize()],"habilita_publicacao":True,
              "habilita_backtest":False,"disponibilidade_asof_comprovada":False}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ErroAgroBRSafras,"promover"):
                _guardar_staging_sqlite(str(Path(tmp)/"x.sqlite"),fake)
            self.assertFalse((Path(tmp)/"x.sqlite").exists())


class TestAgroBRAssincrono(IsolatedAsyncioTestCase):
    async def test_consulta_conab_safra_uf_e_levantamento_sem_fallback(self):
        api=API()
        out=await consultar_safras_agrobr(
            produto="soja",safra="2024/25",uf="MT",levantamento=5,
            direitos_confirmados=True,api=api,
            coletado_em="2026-10-23T12:00:00-04:00",
        )
        self.assertEqual(api.calls,[{
            "produto":"soja","safra":"2024/25","uf":"MT",
            "levantamento":5,"return_meta":True
        }])
        self.assertEqual(out["total"],1)
        self.assertFalse(out["edicao_historica_autenticada"])

    async def test_direitos_ausentes_nao_consultam_rede(self):
        api=API()
        with self.assertRaises(PermissionError):
            await consultar_safras_agrobr(
                produto="soja",safra="2024/25",uf="MT",levantamento=5,
                direitos_confirmados=False,api=api,
            )
        self.assertEqual(api.calls,[])

    async def test_agrobr_sem_meta_reprova(self):
        class BrokenAPI:
            async def safras(self,*a,**k):
                return linhas()
        with self.assertRaisesRegex(ErroAgroBRSafras,"DataFrame e MetaInfo"):
            await consultar_safras_agrobr(
                produto="soja",safra="2024/25",uf="MT",levantamento=5,
                direitos_confirmados=True,api=BrokenAPI()
            )


if __name__=="__main__":
    import unittest
    unittest.main()
