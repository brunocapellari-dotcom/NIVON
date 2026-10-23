"""Protocolo PAM: transporte pontual protegido, SEM INTERNET nos testes."""
import hashlib
import json
import unittest
from datetime import datetime,timezone

from nivon.ivo_pam_coletor_pontual import (
    ErroColetaPAM,_url,_SemRedirecionamento,coletar_candidato_pam
)
from nivon.sidra_pam import planejar_pam_1612


CAT={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
    "enabled":True,"collection_authorized":True,"training_authorized":False}]}
DIREITOS={"operacoes":frozenset(("COLETA","ARMAZENAMENTO")),
          "evidencia_ref":"TERMO_TESTE_SOMENTE_FIXTURE"}
AGORA=datetime(2026,10,21,15,20,tzinfo=timezone.utc)


def plano():
    return planejar_pam_1612(municipio_ibge="5107958",ano=2021,
        codigo_produto_c81="2713",codigo_variavel="214")


def raw_json(valor="1200"):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":"5107958","D2C":"214","D3C":"2021",
         "D4C":"2713","V":valor,"MN":"Toneladas"}],
        ensure_ascii=False).encode()


class TestIVOColetorPontualPAM(unittest.TestCase):
    def setUp(self):
        self.calls=[]
    def responder(self,url,limit,timeout):
        self.calls.append((url,limit,timeout))
        return raw_json(),"application/json; charset=utf-8"
    def coletar(self,**kw):
        opts=dict(catalogo=CAT,direitos=DIREITOS,tipo="SIDRA_JSON",
                  coletado_em=AGORA,plano=plano(),transporte=self.responder)
        opts.update(kw)
        return coletar_candidato_pam(**opts)

    def test_um_get_planejado_sem_seguir_redirecionamentos(self):
        r=self.coletar()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][0],plano()["url"])
        self.assertEqual(r["sha256"],hashlib.sha256(raw_json()).hexdigest())
        self.assertEqual(r["conteudo_original"],raw_json())
        self.assertEqual(r["bytes"],len(raw_json()))
        self.assertEqual(r["estado_valor"],"OBSERVADO_NUMERICO")
        self.assertFalse(r["publicacao_oficial_verificada"])
        self.assertFalse(r["treinamento_autorizado"])
        self.assertFalse(r["gravado_em_snapshot_ledger"])
        self.assertFalse(r["http_real_executado"])

    def test_catalogo_desativado_bloqueia_antes_de_rede(self):
        fonte={"datasets":[dict(CAT["datasets"][0],enabled=False)]}
        with self.assertRaises(PermissionError):
            self.coletar(catalogo=fonte)
        self.assertEqual(self.calls,[])

    def test_fonte_com_coleta_desautorizada_bloqueia(self):
        fonte={"datasets":[dict(CAT["datasets"][0],collection_authorized=False)]}
        with self.assertRaises(PermissionError):
            self.coletar(catalogo=fonte)
        self.assertFalse(self.calls)

    def test_coleta_nao_herda_direitos_de_treinamento(self):
        x=self.coletar()
        self.assertFalse(x["treinamento_autorizado"])
        self.assertEqual(x["evidencia_direitos_declarada"],
            "TERMO_TESTE_SOMENTE_FIXTURE")

    def test_direitos_ausentes_bloqueados(self):
        for bad in (None,{},{"operacoes":frozenset(("COLETA",)),
                             "evidencia_ref":"TESTE_123"},
                    {"operacoes":frozenset(("COLETA","ARMAZENAMENTO")),
                     "evidencia_ref":" "},):
            with self.subTest(bad=bad),self.assertRaises(PermissionError):
                self.coletar(direitos=bad)
        self.assertFalse(self.calls)

    def test_plano_adulterado_bloqueado(self):
        p=plano()
        p["url"]="https://evil.test/steal"
        with self.assertRaises(ErroColetaPAM):
            self.coletar(plano=p)
        self.assertFalse(self.calls)

    def test_produto_sem_semantica_conhecida_bloqueado(self):
        p=planejar_pam_1612(municipio_ibge="5107958",ano=2021,
           codigo_produto_c81="9999",codigo_variavel="214")
        with self.assertRaises(ErroColetaPAM):
            self.coletar(plano=p)
        self.assertFalse(self.calls)

    def test_arquivos_dominios_maliciosos_negados(self):
        for url,tipo in (
            ("http://apisidra.ibge.gov.br/values/t/1612/x","SIDRA_JSON"),
            ("https://apisidra.ibge.gov.br.evil.test/values/t/1612/x","SIDRA_JSON"),
            ("https://evil.test@apisidra.ibge.gov.br/values/t/1612/x","SIDRA_JSON"),
            ("https://apisidra.ibge.gov.br:8080/values/t/1612/x","SIDRA_JSON"),
            ("https://www.ibge.gov.br.evil.test/errata.pdf","PDF_IBGE"),
            ("https://ftp.ibge.gov.br/Outro_Dataset/pam.xls","ARQUIVO_LEGADO"),
            ("https://ftp.ibge.gov.br/Producao_Agricola/Producao_Agricola_Municipal_x/%2e%2e/x.csv","ARQUIVO_LEGADO")
        ):
            with self.subTest(url=url),self.assertRaises(ErroColetaPAM):
                _url(url,tipo=tipo)

    def test_redirecionamento_sempre_proibido(self):
        with self.assertRaises(ErroColetaPAM):
            _SemRedirecionamento().redirect_request(
                None,None,302,"Found",{},"https://evil.test/redirect")

    def test_marcas_sidra_ainda_nao_sao_observacao_realizada(self):
        for flag in ("X","0","-","..","..."):
            with self.subTest(flag=flag):
                x=self.coletar(transporte=lambda u,l,t:(raw_json(flag),"application/json"))
                self.assertNotEqual(x["estado_valor"],"OBSERVADO_NUMERICO")
                self.assertFalse(x["treinamento_autorizado"])

    def test_json_duplicado_invalidado(self):
        bad=b'[{"D1C":"Municipio"},{"D1C":"5107958","D1C":"5107958"}]'
        with self.assertRaises(ErroColetaPAM):
            self.coletar(transporte=lambda u,l,t:(bad,"application/json"))

    def test_limite_e_status_formato(self):
        for body,mime in ((b"z"*(2_000_001),"application/json"),
                          (b"{}","text/html"),
                          (b"", "application/json")):
            with self.subTest(size=len(body)),self.assertRaises(ErroColetaPAM):
                self.coletar(transporte=lambda u,l,t:(body,mime))

    def test_pdf_ibge_unico_e_nao_autenticado(self):
        content=b"%PDF-1.4\n"+b"A"*80
        r=self.coletar(tipo="PDF_IBGE",plano=None,
            url_documento="https://biblioteca.ibge.gov.br/visualizacao/periodicos/66/pam.pdf",
            transporte=lambda u,l,t:(content,"application/pdf"))
        self.assertEqual(r["tipo"],"PDF_IBGE")
        self.assertEqual(r["estado_valor"],"DOCUMENTO_NAO_VERIFICADO")
        self.assertFalse(r["autenticidade_documental_verificada"])

    def test_pdf_html_inesperado_bloqueado(self):
        with self.assertRaises(ErroColetaPAM):
            self.coletar(tipo="PDF_IBGE",plano=None,
                url_documento="https://www.ibge.gov.br/errata.pdf",
                transporte=lambda u,l,t:(b"<html>not a pdf","text/html"))

    def test_arquivo_legado_candidato_nao_e_verdade_pam_2021(self):
        url=("https://ftp.ibge.gov.br/Producao_Agricola/"
             "Producao_Agricola_Municipal_%5Banual%5D/2016/old.xls")
        r=self.coletar(tipo="ARQUIVO_LEGADO",plano=None,
            url_documento=url,
            transporte=lambda u,l,t:(b"ExcelFixture","application/vnd.ms-excel"))
        self.assertEqual(r["estado_valor"],"LEGADO_SEM_PARSER_HOMOLOGADO")
        self.assertFalse(r["treinamento_autorizado"])

    def test_http_real_nao_pode_ser_retrodatado(self):
        # Rejeita antes de abrir qualquer conexão. Não há acesso à rede.
        with self.assertRaises(ErroColetaPAM):
            self.coletar(transporte=None,
                coletado_em=datetime(2020,1,1,tzinfo=timezone.utc))

    def test_timeout_timezone_e_resposta_invalidos(self):
        with self.assertRaises(ErroColetaPAM):
            self.coletar(timeout=0)
        with self.assertRaises(ErroColetaPAM):
            self.coletar(coletado_em=datetime(2026,10,21))
        with self.assertRaises(ErroColetaPAM):
            self.coletar(transporte=lambda u,l,t:None)


if __name__=="__main__":
    unittest.main()
