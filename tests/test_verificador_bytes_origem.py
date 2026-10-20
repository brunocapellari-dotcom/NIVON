import hashlib
import io
import json
import unittest
from zipfile import ZipFile
from nivon.verificador_bytes_origem import conferir_bytes_origem,ErroBytesOrigem

def verificar(payload, mime="text/plain",**kwargs):
    return conferir_bytes_origem(payload=payload,
        sha256_informado=kwargs.pop("sha",hashlib.sha256(payload).hexdigest()),
        tamanho_informado=kwargs.pop("n",len(payload)),
        mime=mime)

class TestBytesOrigem(unittest.TestCase):
    def test_texto_hash_verificado_nao_certifica_fonte(self):
        r=verificar(b"CONAB\n")
        self.assertFalse(r["origem_oficial_comprovada"])
        self.assertFalse(r["direitos_de_uso_comprovados"])
        self.assertFalse(r["parser_vs_bruto_conciliado"])
    def test_hash_alterado_rejeitado(self):
        with self.assertRaises(ErroBytesOrigem):
            verificar(b"arquivo",sha="0"*64)
    def test_tamanho_alterado_rejeitado(self):
        with self.assertRaises(ErroBytesOrigem):
            verificar(b"arquivo",n=55)
    def test_pdf_sem_assinatura_rejeitado(self):
        with self.assertRaises(ErroBytesOrigem):
            verificar(b"nao e PDF",mime="application/pdf")
    def test_html_waf_rejeitado(self):
        for payload in (b"<html>access denied</html>",b"<!DOCTYPE HTML><body>WAF</body>"):
            with self.assertRaises(ErroBytesOrigem):
                verificar(payload)
    def test_json_resposta_valida(self):
        self.assertEqual(verificar(json.dumps({"records":[]}).encode(),
                                mime="application/json")["mime_validado_localmente"],
                         "application/json")
    def test_xlsx_valido_por_metadados_sem_descompactar(self):
        mem=io.BytesIO()
        with ZipFile(mem,"w") as z:
            z.writestr("[Content_Types].xml","<Types/>")
            z.writestr("xl/workbook.xml","<workbook/>")
        self.assertEqual(verificar(mem.getvalue(),
             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")["mime_validado_localmente"],
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    def test_zip_qualquer_nao_e_xlsx(self):
        with self.assertRaises(ErroBytesOrigem):
            verificar(b"PK\x03\x04nao um zip",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    def test_tamanho_limite_memo(self):
        with self.assertRaises(ErroBytesOrigem):
            verificar(b"x"*(20_000_001))
