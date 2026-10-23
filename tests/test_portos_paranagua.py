"""Descoberta de edições oficiais de Paranaguá: sem rede e sem OCR."""
import unittest
from hashlib import sha256
from unittest.mock import patch

from nivon.coleta_web import FonteWeb
from nivon.portos_paranagua import (
    IndiceParanagua, descobrir_edicao_paranagua, processar_edicao_paranagua
)
from nivon.portos_automaticos import ErroPorto

BASE = "https://www.portosdoparana.pr.gov.br/Operacional/Pagina/Atas-do-Corredor-de-Exportacao"
HTML = """<html><body>
<a href="/docs/oeste-antigo.pdf">LINE UP CORREDOR OESTE - 10/10/2026</a>
<a href="/docs/oeste-novo.pdf">LINE UP CORREDOR OESTE - 19/10/2026</a>
<a href="/docs/leste.pdf">LINE UP CORREDOR LESTE - 19/10/2026</a>
<a href="/docs/ata.pdf">ATA DE ATRACACAO - 19/10/2026</a>
<a href="https://outro.site/invalido.pdf">LINE UP CORREDOR OESTE - 21/10/2026</a>
</body></html>"""


class TestIndicePortos(unittest.TestCase):
    def indice(self, serie="EXPORT_OESTE"):
        return IndiceParanagua(
            FonteWeb("PORTO_PARANAGUA",BASE,"www.portosdoparana.pr.gov.br",
                     "HTML",status_direitos="APROVADA",
                     operacoes_permitidas=frozenset({"COLETA"})),serie)

    def fake(self, fonte, *args, **kwargs):
        return {"conteudo":HTML.encode(),"url":fonte.url,
                "sha256":sha256(HTML.encode()).hexdigest()}

    def test_escolhe_edicao_mais_recente_por_serie(self):
        with patch("nivon.portos_paranagua.adquirir_fonte",side_effect=self.fake):
            d=descobrir_edicao_paranagua(self.indice())
        self.assertEqual(d["url_edicao"],
                         "https://www.portosdoparana.pr.gov.br/docs/oeste-novo.pdf")
        self.assertEqual(d["status"],"DESCOBERTO_PENDENTE_EXTRAÇÃO")

    def test_leste_nao_recebe_atracado(self):
        with patch("nivon.portos_paranagua.adquirir_fonte",side_effect=self.fake):
            d=descobrir_edicao_paranagua(self.indice("EXPORT_LESTE"))
        self.assertEqual(d["url_edicao"],
                         "https://www.portosdoparana.pr.gov.br/docs/leste.pdf")

    def test_falta_autorizacao_bloqueia_antes_de_fetch(self):
        with patch("nivon.portos_paranagua.adquirir_fonte",
                   side_effect=AssertionError("rede não permitida")):
            with self.assertRaises(PermissionError):
                processar_edicao_paranagua(
                    {"url_edicao":"https://www.portosdoparana.pr.gov.br/docs/x.pdf",
                     "serie":"EXPORT_OESTE"},
                    referencia=__import__("datetime").date(2026,10,19))

    def test_serie_invalida_bloqueada(self):
        with self.assertRaises(ErroPorto):
            self.indice("ATALHO").verificar()

    def test_nenhuma_serie_compatível_falha(self):
        with patch("nivon.portos_paranagua.adquirir_fonte",
                   return_value={"conteudo":b"<html></html>",
                                 "url":BASE,"sha256":"x"*64}):
            with self.assertRaises(ErroPorto):
                descobrir_edicao_paranagua(self.indice())


if __name__ == "__main__":
    unittest.main()
