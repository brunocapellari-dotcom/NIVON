"""Integração offline CEPEA/IMEA/CONAB no ledger canônico, fail-closed."""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nivon.agro_origem_gcp import (
    coletar_cepea, coletar_imea, coletar_conab, ErroAgroOrigem,
)
from nivon.ingestao_fontes_reais import exportar_jsonl
from scripts.coletar_agro_google_cloud import executar_lote

NOW=datetime(2026,10,23,16,tzinfo=timezone.utc)
HTML="""<html><body>
<h3>INDICADOR DA SOJA CEPEA/ESALQ - PARANAGUÁ</h3>
<table><tr><td>21/10/2026</td><td>150,70</td></tr></table>
<h3>INDICADOR DA SOJA CEPEA/ESALQ - PARANÁ</h3>
<table><tr><td>21/10/2026</td><td>141,35</td></tr></table>
</body></html>"""


class Response:
    headers=SimpleNamespace(get_content_charset=lambda : "utf-8")
    def __init__(self,url): self.url=url
    def geturl(self):return self.url
    def read(self,n):return HTML.encode()[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False


def abrir(req,timeout):return Response(req.full_url)


class Frame:
    def __init__(self,rows):self.rows=rows
    def to_dict(self,orient):assert orient=="records";return self.rows


class IMEA:
    calls=0
    async def cotacoes(self,chain,return_meta):
        self.calls+=1
        url="https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes"
        return Frame([dict(cadeia="soja",indicador_id="101",
            indicador="Preço soja disponível",localidade="Sorriso",
            unidade="R$/sc",valor="151.25",safra="26/27",
            data_publicacao="2026-10-22T12:00:00-04:00")]),SimpleNamespace(
                source="imea",source_url=url)


class TestAgroIntegrado(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p=Path(tmp.name)

    def _rows(self,fonte):
        with sqlite3.connect(self.p/"fontes_reais.sqlite") as db:
            states=db.execute(
                "SELECT estado FROM snapshots WHERE dataset_id=?",(fonte,)).fetchall()
            rows=db.execute(
                "SELECT referencia,publicacao,campos_json FROM observacoes WHERE dataset_id=?",
                (fonte,)).fetchall()
        return states,[(ref,pub,json.loads(x)) for ref,pub,x in rows]

    def test_cepea_html_preservado_e_data_real(self):
        result=coletar_cepea(
            fonte="CEPEA_SOJA",base=self.p,agora=NOW,abrir=abrir,
            homologacao_referencia=True)
        self.assertEqual(result["estado"],"NORMALIZED")
        self.assertEqual(result["quantidade"],2)
        states,rows=self._rows("CEPEA_PRECOS_FISICOS")
        self.assertEqual(states,[("NORMALIZED",)])
        self.assertTrue(all(x[0]=="2026-10-21" for x in rows))
        self.assertTrue(all(x[1] is None for x in rows))
        raw=next((self.p/"raw"/"CEPEA_PRECOS_FISICOS").glob("*.raw"))
        self.assertEqual(raw.read_bytes(),HTML.encode())
        self.assertEqual(coletar_cepea(
            fonte="CEPEA_SOJA",base=self.p,agora=NOW,abrir=abrir,
            homologacao_referencia=True)["novos"],0)

    def test_cepea_sem_homologacao_permanece_quarentena(self):
        res=coletar_cepea(fonte="CEPEA_SOJA",base=self.p,agora=NOW,abrir=abrir)
        self.assertEqual(res["estado"],"QUARANTINED")
        with sqlite3.connect(self.p/"fontes_reais.sqlite") as db:
            states=db.execute("SELECT estado FROM snapshots").fetchall()
        self.assertEqual(states,[("QUARANTINED",)])

    def test_cepea_repetir_snapshot_nao_promove_quarentena(self):
        coletar_cepea(fonte="CEPEA_SOJA",base=self.p,agora=NOW,abrir=abrir)
        with self.assertRaisesRegex(ErroAgroOrigem,"ESTADO_DIVERGENTE"):
            coletar_cepea(fonte="CEPEA_SOJA",base=self.p,agora=NOW,
                          abrir=abrir,homologacao_referencia=True)
        states,_=self._rows("CEPEA_PRECOS_FISICOS")
        self.assertEqual(states,[("QUARANTINED",)])

    def test_cepea_repetir_snapshot_nao_demove_normalizado(self):
        coletar_cepea(fonte="CEPEA_SOJA",base=self.p,agora=NOW,
                      abrir=abrir,homologacao_referencia=True)
        with self.assertRaisesRegex(ErroAgroOrigem,"ESTADO_DIVERGENTE"):
            coletar_cepea(fonte="CEPEA_SOJA",base=self.p,agora=NOW,abrir=abrir)
        states,_=self._rows("CEPEA_PRECOS_FISICOS")
        self.assertEqual(states,[("NORMALIZED",)])

    def test_imea_publicacao_nao_promove_referencia(self):
        import asyncio
        cliente=IMEA()
        primeira=asyncio.run(coletar_imea(
            base=self.p,agora=NOW,cliente=cliente,cadeias=("soja",)))
        self.assertEqual(primeira["estado"],"QUARANTINED")
        self.assertEqual(primeira["cadeias"][0]["quantidade"],1)
        states,rows=self._rows("IMEA_PUBLICACOES_STAGING")
        self.assertEqual(states,[("QUARANTINED",)])
        self.assertIsNone(rows[0][2]["data_referencia"])
        self.assertEqual(rows[0][2]["tipo_referencia"],
                         "PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA")
        repetido=asyncio.run(coletar_imea(
            base=self.p,agora=NOW,cliente=cliente,cadeias=("soja",)))
        self.assertEqual(repetido["cadeias"][0]["novos"],0)
        self.assertEqual(cliente.calls,2)

    def test_conab_edicao_sem_referencia(self):
        import asyncio
        async def catalogo(cliente,limite,hoje):
            return [dict(safra="2025/26",levantamento=10,
                         data_publicacao="2026-10-20",
                         url="https://www.gov.br/conab/pt-br/assuntos/safra")]
        async def registros(cliente,edicao):
            return [dict(publication_date=edicao["data_publicacao"],
                     metric={"produto":p,"producao_mil_t":"123",
                             "data_referencia":None}) for p in ("soja","milho")]
        with (patch("nivon.agro_origem_gcp.edicoes_atuais",side_effect=catalogo),
              patch("nivon.agro_origem_gcp.registros_publicacao",side_effect=registros)):
            r=asyncio.run(coletar_conab(base=self.p,agora=NOW,cliente=object()))
        self.assertEqual(r["estado"],"QUARANTINED")
        self.assertEqual(r["edicoes"][0]["quantidade"],2)
        states,rows=self._rows("CONAB_SAFRAS_STAGING")
        self.assertEqual(states,[("QUARANTINED",)])
        self.assertEqual(len(rows),2)
        self.assertTrue(all(x[2]["data_referencia"] is None for x in rows))

    def test_cepea_fonte_futura_falha_antes_de_banco(self):
        ruim=HTML.replace("21/10/2026","24/10/2026")
        class BadResponse(Response):
            def read(self,n):return ruim.encode()
        with self.assertRaises(ValueError):
            coletar_cepea(fonte="CEPEA_SOJA",base=self.p,agora=NOW,
                          abrir=lambda req,timeout:BadResponse(req.full_url))
        self.assertFalse((self.p/"fontes_reais.sqlite").exists())

    def test_cli_nao_coleta_sem_aprovacao(self):
        self.assertFalse(executar_lote(
            fonte="CEPEA_SOJA",base=self.p)["executado"])
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                executar_lote(fonte="CEPEA_SOJA",base=self.p,executar=True)

    def test_cli_imeaconab_nao_podem_ser_promovidos(self):
        with patch.dict(os.environ,{"NIVON_AGRO_FONTE_AUTORIZADA":"true"}):
            for fonte in ("IMEA","CONAB"):
                with self.subTest(fonte=fonte), self.assertRaises(PermissionError):
                    executar_lote(fonte=fonte,base=self.p,executar=True,
                                  homologar_cepea=True)

if __name__=="__main__":
    unittest.main()
