"""Teste temporario de integracao REAL SIDRA sem persistir valores.
Resultados publicados no log: somente contagem de linhas, UFs e hash.
"""
import json
import os
import unittest
from datetime import datetime, timezone

from nivon.pecuaria_sidra_sondagem import _requisicao_https, _URL_VALORES
from nivon.pecuaria_sidra_mapa_observado import contrato_sidra_observado
from nivon.pecuaria_sidra_abate import normalizar_snapshot_sidra_abate
from nivon.pecuaria_sidra_reconciliacao import diagnosticar_cobertura_abate

class TestSondagemRealIntegradaSIDRA(unittest.TestCase):
    def test_br_ufs_202602_seis_consultas(self):
        if (os.getenv("GITHUB_HEAD_REF") != "feat/pecuaria-inteligencia-20261020"
            or os.getenv("GITHUB_REPOSITORY") != "brunocapellari-dotcom/NIVON"):
            self.skipTest("somente branch pecuaria em runner")
        for especie,tabela in (("BOVINO","1092"),("SUINO","1093"),("FRANGO","1094")):
            contrato=contrato_sidra_observado(especie=especie,tabela_sidra=tabela)
            snapshots = []
            for geo in ("n1/1","n3/all"):
                url=_URL_VALORES.format(tabela,"202602").replace(
                    "/n1/1/","/"+geo+"/").replace("/v/allxp/","/v/284,285/")
                try:
                    r=_requisicao_https(url,timeout=8,limite=2_000_000)
                except Exception as exc:
                    print("SIDRA_INTEGRACAO_REDE="+json.dumps({
                        "especie":especie,"geo":geo,"erro":type(exc).__name__,
                        "detalhe":str(exc)[:130]},sort_keys=True),flush=True)
                    raise
                obj=json.loads(r["corpo"].decode("utf-8-sig"))
                self.assertEqual({row["D3C"] for row in obj[1:]},{"284","285"})
                normalized=normalizar_snapshot_sidra_abate(
                    r["corpo"],especie=especie,tabela_sidra=tabela,
                    dimensoes=contrato["dimensoes"],totais=contrato["totais"],
                    variaveis=contrato["variaveis"],
                    publicacao="2026-09-21T12:00:00+00:00",
                    coleta=datetime.now(timezone.utc).isoformat(),
                    status_fonte="APROVADA",
                    operacoes_autorizadas={"LEITURA","ARMAZENAMENTO"})
                snapshots.append(normalized)
                print("SIDRA_INTEGRACAO_REAL="+json.dumps({
                    "especie":especie,"tabela":tabela,"geo":geo,
                    "registros":len(normalized["observacoes"]),
                    "linhas_censuradas":len(normalized["linhas_indisponiveis"]),
                    "ufs":sorted({x.uf for x in normalized["observacoes"]}),
                    "origem_sha256":normalized["origem_sha256"],
                    "classificacao":normalized["classificacao"],
                    "licenca_confirmada":False,
                    "metadata_v3_confirmado":False},sort_keys=True),flush=True)
                self.assertFalse(normalized["previsao_homologada"])
            diag = diagnosticar_cobertura_abate(
                snapshots=snapshots, especie=especie, tabela_sidra=tabela,
                corte_asof=datetime.now(timezone.utc).isoformat())
            resumo = [{
                "indicador": r["indicador"],
                "ufs_num": r["quantidade_ufs_numericas"],
                "ufs_censuradas": r["ufs_censuradas"],
                "ufs_nao_presentes": r["ufs_nao_presentes"],
                "status": r["status"],
                "residuo": r["residuo_brasil"]
            } for r in diag["indicadores"]]
            print("COBERTURA_SIDRA_REAL="+json.dumps(
                {"especie":especie,"tabela":tabela,"indicadores":resumo},
                sort_keys=True,ensure_ascii=False),flush=True)
            self.assertFalse(diag["publicacao_permitida"])
