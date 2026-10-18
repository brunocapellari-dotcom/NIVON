import hashlib
import io
import zipfile
import unittest
from nivon.antt_ferrovia import extrair_registros, sumarizar_mercadorias, ErroFerrovia


def workbook_sintetico(*,erro_uf=False):
    yearlist=list(range(2006,2021))
    blob=io.BytesIO()
    ns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relns="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    body=''.join(f'<sheet name="{y}" sheetId="{i}" r:id="rId{i}"/>' for i,y in enumerate(yearlist,1))
    wb=f'<workbook xmlns="{ns}" xmlns:r="{relns}"><sheets>{body}</sheets></workbook>'
    rs=''.join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>' for i in range(1,16))
    with zipfile.ZipFile(blob,"w") as z:
        z.writestr("xl/workbook.xml",wb)
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rs}</Relationships>')
        for i,y in enumerate(yearlist,1):
            vals=[f"01/{y}","RUMO","Soja","Estacao Sinop","MT" if not erro_uf else "XX",
                  "Terminal Porto","SP","100","10000"]
            cells=''.join(f'<c r="{chr(65+j)}3" t="inlineStr"><is><t>{v}</t></is></c>'
                          for j,v in enumerate(vals))
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       f'<worksheet xmlns="{ns}"><sheetData><row r="3">{cells}</row></sheetData></worksheet>')
    return blob.getvalue()


class TestANTTFerrovia(unittest.TestCase):
    def test_extrai_estacoes_sem_inferir_municipio(self):
        raw=workbook_sintetico()
        dados=list(extrair_registros(raw,sha256=hashlib.sha256(raw).hexdigest()))
        self.assertEqual(len(dados),15)
        self.assertEqual(dados[0]["periodo"],"2006-01")
        self.assertEqual(dados[0]["modal"],"FERROVIARIO")
        self.assertEqual(dados[0]["local_tipo"],"ESTACAO_NAO_MUNICIPIO")
        self.assertEqual(dados[0]["tu_t"],100)
        self.assertEqual(dados[0]["tku"],10000)

    def test_resumo_por_mercadoria(self):
        raw=workbook_sintetico()
        r=sumarizar_mercadorias(extrair_registros(raw,sha256=hashlib.sha256(raw).hexdigest()))
        self.assertEqual(r["linhas_ferroviarias"],15)
        self.assertEqual(r["mercadorias_relevantes"][0]["tu_t"],1500)
        self.assertIn("NAO_SAO_MDFe",r["aviso"])

    def test_rejeita_uf_invalida(self):
        raw=workbook_sintetico(erro_uf=True)
        with self.assertRaises(ErroFerrovia):
            list(extrair_registros(raw,sha256=hashlib.sha256(raw).hexdigest()))

    def test_rejeita_arquivo_sem_assinatura_xlsx(self):
        with self.assertRaises(ErroFerrovia):
            list(extrair_registros(b"nao zip",sha256="a"*64))

    def test_rejeita_hash_malformado(self):
        with self.assertRaises(ErroFerrovia):
            list(extrair_registros(workbook_sintetico(),sha256="abc"))

if __name__=="__main__":unittest.main()
