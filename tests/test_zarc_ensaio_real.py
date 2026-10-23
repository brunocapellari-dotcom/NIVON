"""Testes offline de ingestão licenciada: nenhum dado real enviado à nuvem."""
from __future__ import annotations
import csv
import io
import unittest
from datetime import datetime,timezone
from pathlib import Path

from nivon.catalogo_fontes import carregar_catalogo
from nivon.zarc_stream_mt import COLUNAS, URL
from nivon.zarc_sinais_ckan import normalizar_sinal,RESOURCE_ID
from nivon.zarc_licenca_manual import (
    emitir_licenca_manual,validar_licenca_manual,ErroLicencaZarc
)
from nivon.zarc_ensaio_real import ensaiar_zarc_real,obter_csv_temporario
from nivon.zarc_staging import abrir_zarc_staging,importar_zarc_local

def csv_fixture():
    buf=io.StringIO()
    w=csv.DictWriter(buf,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    w.writeheader()
    for uf in ("MT","GO","MT"):
        r={k:"" for k in COLUNAS}
        r.update({"Nome_cultura":"SOJA_FAKE","SafraIni":"2026","SafraFin":"2027",
            "Cod_Cultura":"100","Cod_Ciclo":"20","Cod_Solo":"2",
            "geocodigo":"5105259","UF":uf,"municipio":"EXEMPLO_FICTICIO",
            "Cod_Clima":"7","Cod_Outros_Manejos":"1",
            "Cod_Munic":"23","Portaria":"PORTARIA_TESTE"})
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")

def sinal_mock(license_id="cc-by"):
    md={"fonte_id":"MAPA_ZARC","licenca_declarada":license_id,
        "coleta":"2026-10-23T10:00:00Z",
        "revision_id":"pkg-a","atualizado_em":"2026-10-22T09:00:00",
        "recursos":[{"id":RESOURCE_ID,"formato":"CSV","revision_id":"rec-a",
            "url_somente_referencia":URL,"atualizado_em":"2026-10-22T09:00:00"}]}
    return normalizar_sinal(md)

class FakeResponse:
    status=200
    def __init__(self,data,url=URL,mime="text/csv"):
        self.data=io.BytesIO(data)
        self.url=url
        self.headers={"Content-Type":mime}
    def read(self,n):
        return self.data.read(n)
    def geturl(self):
        return self.url
    def __enter__(self):
        return self
    def __exit__(self,*a):
        return False

class FakeOpener:
    def __init__(self,resp):
        self.resp=resp
        self.count=0
    def open(self,request,timeout=120):
        self.count+=1
        if request.full_url != URL:
            raise AssertionError("URL não autorizada")
        return self.resp

class TestManualLicense(unittest.TestCase):
    def test_scope_never_enables_scheduling(self):
        p=emitir_licenca_manual(sinal_mock(),consentimento_manual=True)
        self.assertFalse(p.schedule)
        self.assertFalse(p.publication)
        self.assertTrue(validar_licenca_manual(p,dataset_id="ZARC_JANELAS",
                                              evidence_id=p.evidence_id))
        self.assertFalse(validar_licenca_manual(p,dataset_id="ANTT_CIOT",
                                               evidence_id=p.evidence_id))

    def test_license_missing_or_other_rejected(self):
        with self.assertRaises(PermissionError):
            emitir_licenca_manual(sinal_mock(),consentimento_manual=False)
        with self.assertRaises(ErroLicencaZarc):
            emitir_licenca_manual(sinal_mock("cc-by-4.0"),consentimento_manual=True)

    def test_real_without_explicit_license_still_blocked(self):
        with abrir_zarc_staging() as db:
            with self.assertRaises(PermissionError):
                importar_zarc_local(db,carregar_catalogo(),io.BytesIO(csv_fixture()),
                    coletado_em="2026-10-23T10:00:00Z",
                    origem="REAL_AUTORIZADO",
                    autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                    evidencia_direitos="MAPA_CCBY_ZARC_"+("f"*64))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_real_licensed_optin_and_qc(self):
        f=FakeOpener(FakeResponse(csv_fixture()))
        d=ensaiar_zarc_real(executar=True,abridor_csv=f,
            consultor_ckan=lambda:{
              "fonte_id":"MAPA_ZARC","licenca_declarada":"cc-by",
              "coleta":"2026-10-23T10:00:00Z",
              "revision_id":"pkg-a","atualizado_em":"2026-10-22T09:00:00",
              "recursos":[{"id":RESOURCE_ID,"formato":"CSV",
                  "revision_id":"rec-a","url_somente_referencia":URL,
                  "atualizado_em":"2026-10-22T09:00:00"}]},
            instante=datetime(2026,10,23,10,tzinfo=timezone.utc))
        self.assertEqual(f.count,1)
        self.assertEqual(d["linhas_brasil"],3)
        self.assertEqual(d["linhas_mt"],2)
        self.assertEqual(d["municipios_mt"],1)
        self.assertTrue(d["raw_e_ledger_verificados"])
        self.assertFalse(d["nuvem_remota_gravada"])
        self.assertFalse(d["agendamento_ativado"])
        self.assertFalse(d["publicavel"])

    def test_unauthorized_network_off(self):
        with self.assertRaises(PermissionError):
            ensaiar_zarc_real()
        with self.assertRaises(PermissionError):
            obter_csv_temporario(destino=Path("/tmp/arquivo-inexistente.csv"))

    def test_http_html_or_redirect_blocked(self):
        for response in (FakeResponse(csv_fixture(),mime="text/html"),
                         FakeResponse(csv_fixture(),url="https://host-errado/abc")):
            op=FakeOpener(response)
            import tempfile
            with tempfile.TemporaryDirectory() as p:
                with self.assertRaises(Exception):
                    obter_csv_temporario(destino=Path(p)/"r.csv",
                                         executar=True,abridor=op)
                self.assertFalse((Path(p)/"r.csv").exists())

if __name__=="__main__":
    unittest.main()
