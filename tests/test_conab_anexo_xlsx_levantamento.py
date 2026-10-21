"""Anexo CONAB XLSX: fixtures ZIP sintéticos, sem bytes oficiais."""
from __future__ import annotations
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
import unittest

from nivon.conab_anexo_xlsx_levantamento import (
    conferir_anexo_xlsx_levantamento, ErroDocumentoConab, ANEXO,
)

ROOT = ("https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/"
        "safras/safra-de-graos/boletim-da-safra-de-graos/"
        "3o-levantamento-safra-2023-24")
VIEW = ROOT + "/" + ANEXO + "/view"
ARQUIVO = VIEW.removesuffix("/view")
STAMP = "2026-10-21T15:00:00-04:00"


def zipbytes(files=None):
    if files is None:
        files = {
            "[Content_Types].xml": b"<Types/>",
            "_rels/.rels": b"<Relationships/>",
            "xl/workbook.xml": b"<workbook/>",
        }
    f = BytesIO()
    with ZipFile(f, "w", ZIP_DEFLATED) as z:
        for name, value in files.items():
            z.writestr(name, value)
    return f.getvalue()


def args():
    raw = zipbytes()
    return dict(
        safra="2023/24", numero_levantamento=3,
        pagina_levantamento_url=ROOT,
        pagina_anexo_url=VIEW, arquivo_xlsx_url=ARQUIVO,
        html_levantamento_raw=(
            f'<html><a href="{ARQUIVO}">Tabela de dados</a></html>'
        ).encode(),
        html_anexo_raw=(
            "<html><h1>Tabela de dados - Produção e balanço de oferta e demanda"
            " de grãos</h1><p>Site_PREVISAO_DE_SAFRA-POR_PRODUTO-DEZ-2023.xlsx</p>"
            "</html>"
        ).encode(),
        xlsx_raw=raw, sha256_xlsx_esperado=sha256(raw).hexdigest(),
        coletado_levantamento_em=STAMP,
        coletado_anexo_em=STAMP,
        coletado_xlsx_em=STAMP,
    )


def executar(**changes):
    x=args()
    x.update(changes)
    return conferir_anexo_xlsx_levantamento(**x)


class TestAnexoCONAB(unittest.TestCase):
    def test_captura_sintetica_aceita_sem_prova_asof(self):
        r = executar()
        self.assertEqual(r["numero_levantamento"], 3)
        self.assertEqual(r["arquivo_xlsx_url"], ARQUIVO)
        self.assertTrue(r["estrutura_xlsx_basica_verificada"])
        self.assertFalse(r["celulas_xlsx_lidas"])
        self.assertFalse(r["edicao_historica_autenticada"])
        self.assertFalse(r["disponibilidade_asof_comprovada"])
        self.assertFalse(r["habilita_backtest"])
        self.assertFalse(r["habilita_treino"])
        self.assertFalse(r["habilita_publicacao"])
        self.assertEqual(r["arquivo_raw_sha256"],sha256(args()["xlsx_raw"]).hexdigest())

    def test_link_relativo_sem_view_reconhecido(self):
        html=f'<html><a href="{ANEXO}">Tabela</a></html>'.encode()
        r=executar(html_levantamento_raw=html)
        self.assertEqual(r["pagina_anexo_url"],VIEW)

    def test_mistura_de_levantamento_ou_safra_rejeitada(self):
        for changes in ({"numero_levantamento":4},
                        {"safra":"2024/25"},
                        {"safra":"2023/29"},
                        {"numero_levantamento":True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ErroDocumentoConab):
                    executar(**changes)

    def test_arquivo_de_outro_levantamento_nao_aceito(self):
        with self.assertRaisesRegex(ErroDocumentoConab,"download XLSX"):
            executar(arquivo_xlsx_url=ROOT+"/boletim.pdf")
        with self.assertRaisesRegex(ErroDocumentoConab,"anexo"):
            executar(pagina_anexo_url=ROOT+"/outro/view")

    def test_dominio_e_porta_estranhos(self):
        for bad in (ARQUIVO.replace("www.gov.br", "www.gov.br.evil.tld"),
                    ARQUIVO.replace("https:", "http:"),
                    ARQUIVO+"?v=1",
                    ARQUIVO.replace("www.gov.br", "www.gov.br:8443")):
            with self.subTest(bad=bad):
                with self.assertRaises(ErroDocumentoConab):
                    executar(arquivo_xlsx_url=bad)

    def test_anexo_nao_linkado_no_html_pai(self):
        with self.assertRaisesRegex(ErroDocumentoConab,"não encontrado"):
            executar(html_levantamento_raw=b"<html><p>sem link do XLSX</p></html>")

    def test_html_com_host_externo_nao_autoriza_documento(self):
        html=(f'<html><a href="https://conab.evil.example/{ANEXO}">falso</a></html>').encode()
        with self.assertRaisesRegex(ErroDocumentoConab,"não encontrado"):
            executar(html_levantamento_raw=html)

    def test_sha_de_captura_mudou(self):
        with self.assertRaisesRegex(ErroDocumentoConab,"SHA"):
            executar(sha256_xlsx_esperado="f"*64)
        with self.assertRaisesRegex(ErroDocumentoConab,"SHA"):
            executar(xlsx_raw=args()["xlsx_raw"]+b" ")

    def test_capturas_em_janelas_distantes_rejeitadas(self):
        with self.assertRaisesRegex(ErroDocumentoConab,"10 minutos"):
            executar(coletado_xlsx_em="2026-10-21T15:11:00-04:00")

    def test_timestamp_sem_fuso_rejeitado(self):
        with self.assertRaisesRegex(ErroDocumentoConab,"fuso"):
            executar(coletado_anexo_em="2026-10-21T15:00:00")

    def test_zip_vazio_ou_corrompido(self):
        for raw in (b"", b"PK\x03\x04"+b"0"*120, "<html>não é xlsx</html>".encode("utf-8")):
            with self.subTest(raw=raw[:5]):
                with self.assertRaises(ErroDocumentoConab):
                    executar(xlsx_raw=raw, sha256_xlsx_esperado=sha256(raw).hexdigest())

    def test_xlsx_sem_workbook(self):
        raw=zipbytes({"[Content_Types].xml":b"1",
                      "_rels/.rels":b"2",
                      "xl/worksheets/sheet1.xml":b"3"})
        with self.assertRaisesRegex(ErroDocumentoConab,"estrutura mínima"):
            executar(xlsx_raw=raw,sha256_xlsx_esperado=sha256(raw).hexdigest())

    def test_rejeita_entrada_maliciosa(self):
        for nome in ("xl/vbaProject.bin", "xl/externalLinks/externalLink1.xml",
                     "xl/activeX/activeX1.xml", "xl/../../x.xml"):
            data={
                "[Content_Types].xml":b"1", "_rels/.rels":b"2",
                "xl/workbook.xml":b"3", nome:b"ativo",
            }
            raw=zipbytes(data)
            with self.subTest(nome=nome):
                with self.assertRaises(ErroDocumentoConab):
                    executar(xlsx_raw=raw,sha256_xlsx_esperado=sha256(raw).hexdigest())

    def test_zip_bomba_e_limites(self):
        data={"[Content_Types].xml":b"1","_rels/.rels":b"2",
              "xl/workbook.xml":b"3","xl/sharedStrings.xml":b"A"*3_000_000}
        raw=zipbytes(data)
        with self.assertRaisesRegex(ErroDocumentoConab,"descompressão"):
            executar(xlsx_raw=raw,sha256_xlsx_esperado=sha256(raw).hexdigest())

    def test_nome_de_anexo_no_html_nao_homologa_edicao(self):
        html=(b"<html><p>Site_PREVISAO_DE_SAFRA-POR_PRODUTO-DEZ-2023.xlsx</p>"
              b"<p>Atualizado em 24/01/2025</p></html>")
        r=executar(html_anexo_raw=html)
        self.assertFalse(r["edicao_historica_autenticada"])

    def test_datas_de_publicacao_nao_sao_inferidas_pelo_codigo(self):
        r=executar()
        self.assertNotIn("publicado_em",r)
        self.assertNotIn("disponivel_em",r)
        self.assertNotIn("valor_producao",r)


if __name__ == "__main__":
    unittest.main()
