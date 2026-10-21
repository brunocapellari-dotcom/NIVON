"""Captação XLSX controlada: contratos HTTP, zero coleta sem consentimento.

Usa exclusivamente fixture agrobr de terceiro e transporte simulado,
nunca efetua download de dados CONAB durante CI.
"""
import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime,timezone
from pathlib import Path
from contextlib import redirect_stderr

from nivon.captura_xlsx_conab import (
    ErroCapturaConab,capturar_xlsx_conab,verificar_pacote_captura_local,main,MIME,
    RAW_FILE,EVIDENCE_FILE,
)

URLROOT="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/"
URL=URLROOT+"acompanhamento-das-lavouras-02-02-a-08-02-26/plantio-e-colheita-01-02-a-07-02.xlsx"
REC={
    "id_edicao":"CONAB_PROG_2026_02_08",
    "url_pagina":URLROOT+"acompanhamento-das-lavouras-02-02-a-08-02-26/acompanhamento-das-lavouras-02-02-a-08-02-26",
    "url_anexo":URL,
    "publicacao_data":"2026-02-09",
    "pagina_inicio":"2026-02-02",
    "pagina_fim":"2026-02-08",
    "planilha_inicio":"2026-02-01",
    "planilha_fim":"2026-02-07",
    "conteudo_sha256_verificado":None,
}
FIXTURE=Path(__file__).parent/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"


class FakeResponse:
    def __init__(self,data,*,status=200,final_url=URL,mime=MIME, length=None):
        self.buffer=io.BytesIO(data)
        self.status=status
        self.url=final_url
        self.headers={
            "Content-Type":mime,
            "Content-Length":str(len(data) if length is None else length),
            "ETag":'"fake-test-etag"',
            "Last-Modified":"Tue, 24 Feb 2026 09:59:00 GMT",
        }
    def __enter__(self):return self
    def __exit__(self,*a):self.buffer.close()
    def read(self,n):return self.buffer.read(n)
    def geturl(self):return self.url


class TestCapturaControladaConab(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)/"private"
        self.dir.mkdir(mode=0o700)
        if os.name=="posix":self.dir.chmod(0o700)
        self.data=base64.b64decode(FIXTURE.read_text().strip(),validate=True)
        self.calls=[]
    def clk(self):
        return datetime(2026,2,24,10,tzinfo=timezone.utc)
    def transport(self,*,data=None,status=200,final_url=URL,mime=MIME,length=None):
        content=self.data if data is None else data
        def open_mock(req,timeout):
            self.calls.append((req.full_url,timeout))
            return FakeResponse(content,status=status,final_url=final_url,
                                mime=mime,length=length)
        return open_mock
    def capture(self,**kw):
        tr=kw.pop("transport",self.transport())
        return capturar_xlsx_conab(REC,destino=self.dir,
                    autoriza_requisicao=True,direitos_coleta_conferidos=True,
                    transport=tr,clock=kw.pop("clock",self.clk),**kw)
    def test_sem_autorizacao_nao_consulta_rede(self):
        with self.assertRaises(PermissionError):
            capturar_xlsx_conab(REC,destino=self.dir,transport=self.transport(),
                                clock=self.clk)
        self.assertEqual(self.calls,[])
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_so_uma_das_autorizacoes_nao_consulta(self):
        with self.assertRaises(PermissionError):
            capturar_xlsx_conab(REC,destino=self.dir,
                autoriza_requisicao=True,transport=self.transport(),clock=self.clk)
        self.assertEqual(self.calls,[])

    def test_golden_transporte_simulado_grava_arquivo_e_manifesto(self):
        result=self.capture()
        self.assertEqual(result["raw_sha256"],hashlib.sha256(self.data).hexdigest())
        self.assertEqual(result["quantidade_observacoes"],11)
        self.assertEqual(self.calls,[(URL,20)])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         [EVIDENCE_FILE,RAW_FILE])
        self.assertEqual((self.dir/RAW_FILE).read_bytes(),self.data)
        evidence=json.loads((self.dir/EVIDENCE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema"],"NIVON_CONAB_CAPTURA_SUPERVISIONADA_V1")
        self.assertEqual(evidence["transport_evidencia"]["http_status"],200)
        self.assertEqual(evidence["transport_evidencia"]["etag"],'"fake-test-etag"')
        self.assertFalse(evidence["migracao_permitida"])
        self.assertFalse(evidence["publicacao_permitida"])
        self.assertFalse(evidence["direitos_redistribuicao_verificados"])
        self.assertFalse(evidence["origem_publicada_arquivada_independentemente"])
        if os.name=="posix":
            self.assertEqual((self.dir/RAW_FILE).stat().st_mode & 0o077,0)
            self.assertEqual((self.dir/EVIDENCE_FILE).stat().st_mode & 0o077,0)

    def test_nao_sobrescreve_pasta_nao_vazia(self):
        sentinel=self.dir/"preservar.txt"
        sentinel.write_text("valor anterior")
        with self.assertRaisesRegex(ErroCapturaConab,"não vazio"):
            self.capture()
        self.assertEqual(sentinel.read_text(),"valor anterior")
        self.assertEqual(self.calls,[])

    def test_nao_sobrescreve_em_segunda_coleta(self):
        self.capture()
        saved=(self.dir/RAW_FILE).read_bytes()
        with self.assertRaises(ErroCapturaConab):self.capture()
        self.assertEqual((self.dir/RAW_FILE).read_bytes(),saved)
        self.assertEqual(len(self.calls),1)

    def test_content_type_html_waf_rejeita_antes_de_gravar(self):
        with self.assertRaisesRegex(ErroCapturaConab,"MIME"):
            self.capture(transport=self.transport(data=b"<html>Request Rejected</html>",mime="text/html"))
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_binary_html_mas_mime_xlsx_rejeita(self):
        with self.assertRaises(ErroCapturaConab):
            self.capture(transport=self.transport(data=b"<html>Request Rejected</html>"))
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_http_302_e_redirect_fora_url_exata_rejeitados(self):
        for status,url in ((302,URL), (200,"https://www.gov.br/qualquer/coisa")):
            with self.subTest(status=status,url=url):
                with self.assertRaises(ErroCapturaConab):
                    self.capture(transport=self.transport(status=status,final_url=url))
                self.assertEqual(list(self.dir.iterdir()),[])

    def test_content_length_errado_rejeita(self):
        with self.assertRaisesRegex(ErroCapturaConab,"incompleto"):
            self.capture(transport=self.transport(length=1234))
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_content_length_acima_limite_rejeita_sem_ler(self):
        with self.assertRaisesRegex(ErroCapturaConab,"acima do limite"):
            self.capture(transport=self.transport(length=100000000))
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_timeout_dns_sem_retry_sem_raw(self):
        def fake(req,timeout):
            self.calls.append(1)
            raise urllib.error.URLError("DNS failure")
        with self.assertRaisesRegex(ErroCapturaConab,"download HTTPS falhou"):
            self.capture(transport=fake)
        self.assertEqual(self.calls,[1])
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_shadivergente_nao_salva(self):
        rec={**REC,"conteudo_sha256_verificado":"0"*64}
        with self.assertRaises(ErroCapturaConab):
            capturar_xlsx_conab(rec,destino=self.dir,autoriza_requisicao=True,
                direitos_coleta_conferidos=True,transport=self.transport(),clock=self.clk)
        self.assertEqual(list(self.dir.iterdir()),[])

    def test_pasta_sem_modo_privado_rejeita(self):
        if os.name!="posix":self.skipTest("POSIX only")
        self.dir.chmod(0o755)
        with self.assertRaisesRegex(ErroCapturaConab,"700"):
            self.capture()
        self.assertEqual(self.calls,[])

    def test_symlink_na_pasta_bloqueia(self):
        l=Path(self.tmp.name)/"alias"
        try:l.symlink_to(self.dir,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest("sem symlink")
        with self.assertRaises(ErroCapturaConab):
            capturar_xlsx_conab(REC,destino=l,autoriza_requisicao=True,
                direitos_coleta_conferidos=True,transport=self.transport(),clock=self.clk)
        self.assertEqual(self.calls,[])

    def test_coleta_relogio_sem_timezone_bloqueia(self):
        with self.assertRaises(ErroCapturaConab):
            self.capture(clock=lambda:datetime(2026,2,24,10))
        self.assertEqual(self.calls,[])
        self.assertEqual(list(self.dir.iterdir()),[])


    def test_pacote_salvo_reverificado_sem_rede(self):
        self.capture()
        before=(self.dir/RAW_FILE).read_bytes()
        n=len(self.calls)
        result=verificar_pacote_captura_local(REC,self.dir)
        self.assertEqual(result["estado"],"PACOTE_LOCAL_REVERIFICADO_SEM_ATESTACAO_EXTERNA")
        self.assertEqual(result["observacoes"],11)
        self.assertFalse(result["origem_http_independentemente_atestada"])
        self.assertFalse(result["migracao_permitida"])
        self.assertEqual(len(self.calls),n)
        self.assertEqual((self.dir/RAW_FILE).read_bytes(),before)

    def test_reverificacao_detecta_raw_alterado(self):
        self.capture()
        with (self.dir/RAW_FILE).open("ab") as out:
            out.write(b"adulteracao")
        with self.assertRaisesRegex(ErroCapturaConab,"adulterado"):
            verificar_pacote_captura_local(REC,self.dir)

    def test_reverificacao_detecta_hash_e_metadados_modificados(self):
        self.capture()
        f=self.dir/EVIDENCE_FILE
        value=json.loads(f.read_text())
        value["parser_codigo_sha256"]="0"*64
        f.write_text(json.dumps(value))
        with self.assertRaisesRegex(ErroCapturaConab,"parser/contagens"):
            verificar_pacote_captura_local(REC,self.dir)

    def test_reverificacao_recusa_gates_manipulados(self):
        self.capture()
        f=self.dir/EVIDENCE_FILE
        value=json.loads(f.read_text())
        value["publicacao_permitida"]=True
        f.write_text(json.dumps(value))
        with self.assertRaisesRegex(ErroCapturaConab,"gates"):
            verificar_pacote_captura_local(REC,self.dir)

    def test_reverificacao_recusa_transporte_manipulado(self):
        self.capture()
        f=self.dir/EVIDENCE_FILE
        value=json.loads(f.read_text())
        value["transport_evidencia"]["url_resposta"]="https://evil.example/teste"
        f.write_text(json.dumps(value))
        with self.assertRaisesRegex(ErroCapturaConab,"transporte"):
            verificar_pacote_captura_local(REC,self.dir)

    def test_reverificacao_recusa_json_chaves_duplicadas(self):
        self.capture()
        f=self.dir/EVIDENCE_FILE
        obj=f.read_text()
        f.write_text(obj.replace('"schema": "NIVON_CONAB_CAPTURA_SUPERVISIONADA_V1",',
                            '"schema": "NIVON_CONAB_CAPTURA_SUPERVISIONADA_V1", "schema": "x",'))
        with self.assertRaises(ErroCapturaConab):
            verificar_pacote_captura_local(REC,self.dir)

    def test_reverificacao_recusa_arquivo_extra(self):
        self.capture()
        (self.dir/"intruso.txt").write_text("intruso")
        with self.assertRaisesRegex(ErroCapturaConab,"exatamente RAW"):
            verificar_pacote_captura_local(REC,self.dir)

    def test_reverificacao_recusa_link_simbolico(self):
        self.capture()
        p=self.dir/RAW_FILE
        fake=Path(self.tmp.name)/"outro.xlsx"
        fake.write_bytes(p.read_bytes())
        p.unlink()
        try:p.symlink_to(fake)
        except (OSError,NotImplementedError):self.skipTest("sem symlink")
        with self.assertRaises(ErroCapturaConab):
            verificar_pacote_captura_local(REC,self.dir)

    def test_json_cli_sem_autorizacao_nao_cria_raw(self):
        cat=Path(self.tmp.name)/"manifesto.json"
        cat.write_text(json.dumps({
            "schema":"NIVON_CONAB_PAGINA_ANEXO_V1",
            "edicoes":[REC],
        }))
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exc:
            main(["--manifesto",str(cat),"--id-edicao",REC["id_edicao"],
                  "--destino",str(self.dir)])
        self.assertEqual(exc.exception.code,2)
        self.assertEqual(list(self.dir.iterdir()),[])


if __name__=="__main__":
    unittest.main()
