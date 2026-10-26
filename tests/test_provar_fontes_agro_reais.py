"""Contrato da prova real agrícola sem cloud com ledger/fixtures determinísticos."""
from __future__ import annotations
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from nivon.ingestao_fontes_reais import gravar_lote
from datetime import date
from scripts.provar_fontes_agro_reais import (conferir,provar,avaliar_frescor,
    dias_uteis_entre,main)

NOW=datetime(2026,10,25,12,tzinfo=timezone.utc)


class ProvaAgro(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.banco=self.root/"fontes_reais.sqlite"

    def guardar(self,estado="QUARANTINED",data_ref=None):
        ds="IMEA_PUBLICACOES_STAGING"
        return gravar_lote(
            banco=self.banco,diretorio_bruto=self.root/"raw",
            dataset_id=ds,origem="https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes",
            raw=b'{"indicador":"soja"}',tipo="application/json",
            coletado_em=NOW,estado=estado,registros=[{
                "identidade":"preco-soja","referencia":"2026-10-23",
                "publicacao":"2026-10-23T12:00:00-04:00",
                "natureza":"INFORMADO","valor":"123.50",
                "campos":{"data_referencia":data_ref,
                          "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"}}])

    def comprovante(self,snapshot):
        return {"dataset":"IMEA_PUBLICACOES_STAGING","estado":"QUARANTINED",
                "cadeias":[{"snapshot_id":snapshot,"quantidade":1}]}

    def test_imeaconab_nunca_promovem_e_nao_imprimem_valores(self):
        s=self.guardar()
        report=conferir("IMEA",self.comprovante(s["snapshot_id"]),
                       self.banco,agora=NOW)
        self.assertEqual(report["registros"],1)
        self.assertEqual(report["snapshots"],1)
        self.assertEqual(report["tipo_data"],"PUBLICACAO_COM_REFERENCIA_AUSENTE")
        self.assertFalse(report["valores_publicados"])
        self.assertNotIn("123.50",json.dumps(report))
        self.assertEqual(report["gcs_escritas"],0)
        self.assertEqual(report["bigquery_jobs"],0)

    def test_coleta_rejeitada_com_referencia_falsa(self):
        s=self.guardar(data_ref="2026-10-23")
        with self.assertRaisesRegex(ValueError,"inventada"):
            conferir("IMEA",self.comprovante(s["snapshot_id"]),self.banco,agora=NOW)

    def test_nao_confunde_contagem_esperada_com_persistida(self):
        s=self.guardar()
        errado=self.comprovante(s["snapshot_id"])
        errado["cadeias"][0]["quantidade"]=10
        with self.assertRaisesRegex(ValueError,"contagens"):
            conferir("IMEA",errado,self.banco,agora=NOW)

    def test_modo_real_descarta_ledger_na_saida(self):
        s=self.guardar()
        def fake_collector(*,base,**kwargs):
            # Nesta fixture, escrever na pasta temporária da função provar
            r=gravar_lote(
                banco=Path(base)/"fontes_reais.sqlite",
                diretorio_bruto=Path(base)/"raw",
                dataset_id="IMEA_PUBLICACOES_STAGING",
                origem="https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes",
                raw=b'{"indicador":"soja"}',tipo="application/json",
                coletado_em=NOW,estado="QUARANTINED",registros=[{
                    "identidade":"preco-soja","referencia":"2026-10-23",
                    "natureza":"INFORMADO",
                    "campos":{"data_referencia":None,
                              "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"}}])
            return self.comprovante(r["snapshot_id"])
        with patch("scripts.provar_fontes_agro_reais.coletar",
                   side_effect=fake_collector) as coletor:
            result=provar("IMEA",agora=NOW)
        self.assertEqual(result["estado"],"COLETA_REAL_CONCILIADA_EM_RUNNER")
        self.assertEqual(coletor.call_count,1)
        self.assertFalse(result["producao_ativada"])


class FrescorAgro(unittest.TestCase):
    def test_dias_uteis_ignoram_fim_de_semana(self):
        # sexta 23/10 -> segunda 26/10 = 1 dia útil
        self.assertEqual(dias_uteis_entre(date(2026,10,23),date(2026,10,26)),1)
        self.assertEqual(dias_uteis_entre(date(2026,10,23),date(2026,10,23)),0)

    def test_cepea_fresco_apos_fim_de_semana(self):
        r=avaliar_frescor("CEPEA_SOJA",date(2026,10,23),date(2026,10,26))
        self.assertEqual((r["frescor"],r["frescor_idade"]),("FRESCO",1))

    def test_cepea_limite_de_tres_dias_uteis(self):
        r=avaliar_frescor("CEPEA_MILHO",date(2026,10,20),date(2026,10,23))
        self.assertEqual(r["frescor"],"FRESCO")
        r=avaliar_frescor("CEPEA_MILHO",date(2026,10,16),date(2026,10,23))
        self.assertEqual(r["frescor"],"DEFASADO")

    def test_imea_conab_contam_dias_corridos_de_publicacao(self):
        self.assertEqual(avaliar_frescor("IMEA",date(2026,10,13),date(2026,10,23))["frescor"],"FRESCO")
        self.assertEqual(avaliar_frescor("IMEA",date(2026,10,12),date(2026,10,23))["frescor"],"DEFASADO")
        r=avaliar_frescor("CONAB",date(2026,10,15),date(2026,10,26))
        self.assertEqual((r["frescor"],r["frescor_criterio"]),("FRESCO","DIAS_CORRIDOS_DESDE_PUBLICACAO"))

    def test_exigir_frescor_retorna_3_quando_defasado(self):
        import io,contextlib
        for estado,codigo in (("FRESCO",0),("DEFASADO",3)):
            with patch("scripts.provar_fontes_agro_reais.provar",return_value={"frescor":estado}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--fonte","IMEA","--executar","--exigir-frescor"]),codigo)

    def test_sem_exigir_frescor_mantem_codigo_zero(self):
        import io,contextlib
        with patch("scripts.provar_fontes_agro_reais.provar",return_value={"frescor":"DEFASADO"}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--fonte","IMEA","--executar"]),0)

    def test_plano_sem_rede_com_exigencia_nao_passa(self):
        import io,contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--fonte","CONAB","--exigir-frescor"]),3)


if __name__=="__main__":
    unittest.main()
