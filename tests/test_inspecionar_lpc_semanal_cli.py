import json
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date

from scripts.inspecionar_lpc_semanal import executar

try:
    from openpyxl import Workbook
except ImportError:
    Workbook=None

URL=("https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
     "precos/arquivos-lpc/2026/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx")

@unittest.skipIf(Workbook is None,"openpyxl não disponível")
class TestInspecionarLPC(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.xlsx=self.root/"anp.xlsx"
        self.json=self.root/"resultado.json"
        wb=Workbook();w=wb.active;w.title="MUNICIPIOS"
        for _ in range(6):w.append(["METADADOS DA SEMANA"])
        w.append(["DATA INICIAL","DATA FINAL","ESTADO","MUNICÍPIO","PRODUTO",
                  "NÚMERO DE POSTOS PESQUISADOS","UNIDADE DE MEDIDA","PREÇO MÉDIO REVENDA"])
        w.append([date(2026,10,4),date(2026,10,10),"MATO GROSSO","SINOP",
                  "OLEO DIESEL S10",5,"R$/l",6.02])
        w.append([date(2026,10,4),date(2026,10,10),"MATO GROSSO","SORRISO",
                  "OLEO DIESEL",6,"R$/l",5.94])
        wb.save(self.xlsx);wb.close()

    def tearDown(self):
        self.temp.cleanup()

    def importar(self,**extra):
        kwargs={"arquivo":self.xlsx,"url_fonte":URL,
                "coletado_em":"2026-10-20T10:00:00-03:00",
                "saida":self.json}
        kwargs.update(extra)
        return executar(**kwargs)

    def test_comando_emite_json_agregado_sem_publicar(self):
        meta=self.importar()
        self.assertEqual(meta["municipios"],2)
        self.assertEqual(meta["registros"],2)
        data=json.loads(self.json.read_text())
        self.assertFalse(data["publicavel"])
        self.assertEqual(data["dataset_id"],"ANP_PRECO_REVENDA_DIESEL")
        self.assertNotIn("CNPJ",self.json.read_text())

    def test_filtro_municipal(self):
        a=self.importar(municipios=["SINOP"])
        self.assertEqual(a["municipios"],1)

    def test_arquivo_inexistente_nao_cria_resultado(self):
        with self.assertRaises(ValueError):
            self.importar(arquivo=self.root/"sem.xlsx")
        self.assertFalse(self.json.exists())

    def test_arquivo_invalido_sem_publicacao(self):
        self.xlsx.write_bytes(b"<html>Request Rejected</html>")
        with self.assertRaises(ValueError):
            self.importar()
        self.assertFalse(self.json.exists())

    def test_nao_sobrescrever_arquivo_de_entrada(self):
        with self.assertRaises(ValueError):
            self.importar(saida=self.xlsx)

if __name__=="__main__":
    unittest.main()
