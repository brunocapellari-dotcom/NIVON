"""Testes offline para amostras de CSV/ZIP do catálogo complementar."""
import hashlib
import io
import unittest
import zipfile
from nivon.arquivos_publicos_lote import (
    DATASETS_CSV, LIMITE_BRUTO, ErroArquivoAberto, inspecionar_arquivo,
)

T = "2026-10-21T20:00:00+00:00"

def verificar(nome="amostra.csv", data=b"municipio;produto;valor\n5105259;SOJA;100\n",
             dataset="MAPA_ZARC"):
    return inspecionar_arquivo(dataset, nome=nome,
                              bytes_brutos=data, coletado_em=T)

def zippado(nome="tabela.csv", dados=b"id;valor\n1;10\n"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(nome, dados)
    return buf.getvalue()

class ArquivosPublicosTest(unittest.TestCase):
    def test_whitelist_todas_fontes(self):
        self.assertEqual(len(DATASETS_CSV), 15)
        for ds in DATASETS_CSV:
            out = verificar(dataset=ds)
            self.assertEqual(out["dataset_id"], ds)
            self.assertFalse(out["publicavel"])
            self.assertFalse(out["persistido"])
            self.assertEqual(out["linhas_amostra"], 1)
            self.assertEqual(out["colunas"], ["municipio", "produto", "valor"])
            self.assertEqual(out["sha256_original"],
                             hashlib.sha256(b"municipio;produto;valor\n5105259;SOJA;100\n").hexdigest())

    def test_zip_csv_autorizado(self):
        out = verificar(nome="amostra.zip", data=zippado())
        self.assertEqual(out["tipo_arquivo"], "ZIP_CSV")
        self.assertEqual(out["linhas_amostra"], 1)

    def test_zip_rejeita_traversal(self):
        with self.assertRaises(ErroArquivoAberto):
            verificar(nome="amostra.zip", data=zippado("../private.csv"))

    def test_zip_rejeita_multiplos_arquivos(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.csv", "a\n1\n")
            zf.writestr("b.csv", "a\n2\n")
        with self.assertRaises(ErroArquivoAberto):
            verificar(nome="amostra.zip", data=buf.getvalue())

    def test_csv_nao_aceita_colunas_inconsistentes(self):
        with self.assertRaises(ErroArquivoAberto):
            verificar(data=b"a;b\n1\n")

    def test_csv_nao_aceita_coluna_duplicada(self):
        with self.assertRaises(ErroArquivoAberto):
            verificar(data=b"a;a\n1;2\n")

    def test_dataset_invalido_sem_efeito_colateral(self):
        with self.assertRaises(ErroArquivoAberto):
            verificar(dataset="CEPEA")

    def test_limite_de_bytes(self):
        with self.assertRaises(ErroArquivoAberto):
            verificar(data=b"x" * (LIMITE_BRUTO + 1))

    def test_fuso_obrigatorio(self):
        with self.assertRaises(ErroArquivoAberto):
            inspecionar_arquivo("MAPA_ZARC", nome="x.csv",
                               bytes_brutos=b"a\n1\n",
                               coletado_em="2026-10-21T12:00:00")

if __name__ == "__main__":
    unittest.main()
