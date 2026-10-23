"""Expansão tabular de line-up nacional com fonte e parser OFF por padrão."""
import unittest
from datetime import datetime,timezone

from nivon.coleta_web import FonteWeb
from nivon.portos_nacionais_tabela import (
    ContratoTabular,analisar_html_nacional,coletar_html_nacional,
    ErroPortoTabular
)
from nivon.lineup_nacional import consolidar

URL="https://www.portodesantos.com.br/linha/"
FONTE=FonteWeb(
    "HTML_SANTOS",URL,"www.portodesantos.com.br","HTML",
    status_direitos="APROVADA",operacoes_permitidas=frozenset({"COLETA"}))
SCOPE={"ports":[{
    "id":"SANTOS","endpoint_verified":False,
    "parser_homologated":False,"lineup_source_url":None,
    "commercial_rights":"PENDING",
}]}
HTML="""<html><table><tr>
<th>Navio</th><th>DuV</th><th>Carga</th><th>Qtde t</th>
<th>ETA</th><th>Local</th>
</tr><tr><td>Navio um</td><td>DUV100</td><td>SOJA</td>
<td>1.234,50</td><td>21/10/2026</td><td>Berço 1</td></tr></table></html>"""


class TestPortoNacionalGenerico(unittest.TestCase):
    def contrato(self):
        return ContratoTabular(
            "SANTOS",FONTE,
            {"navio":"Navio","duv":"DUV","produto":"Carga",
             "toneladas_programadas":"Qtde t","eta":"ETA",
             "terminal":"Local"},
            "2026-10-19T07:00:00-03:00",
        )

    def parse(self,html=HTML,contrato=None):
        return analisar_html_nacional(
            html,contrato or self.contrato(),escopo=SCOPE,
            coletado_em="2026-10-19T11:00:00-03:00",
        )

    def test_html_com_colunas_contratadas(self):
        r=self.parse()
        self.assertEqual(r["total"],1)
        x=r["registros"][0]
        self.assertEqual(x["porto_id"],"SANTOS")
        self.assertEqual(x["duv"],"DUV100")
        self.assertEqual(x["toneladas_programadas"],1234.5)
        self.assertEqual(x["eta_programado_documental"],"21/10/2026")
        self.assertEqual(x["terminal_informado"],"Berço 1")
        self.assertEqual(x["situacao"],"PROGRAMADO")
        self.assertIsNone(x["toneladas_realizadas"])

    def test_agregado_nao_finge_volume_sem_lote(self):
        r=self.parse()
        c=consolidar([{
            k:v for k,v in r["registros"][0].items()
            if k not in ("eta_programado_documental","terminal_informado")
        }],SCOPE)
        self.assertEqual(c["grupos"][0]["toneladas_programadas_sem_duplicacao"],0)
        self.assertEqual(c["grupos"][0]["volumes_nao_conciliaveis"],1)

    def test_remoto_bloqueado_antes_da_rede(self):
        class Proibido:
            def open(self,*args,**kwargs):
                raise AssertionError("coleta remota não habilitada")
        with self.assertRaises(PermissionError):
            coletar_html_nacional(
                self.contrato(),escopo=SCOPE,abridor=Proibido())

    def test_tabela_duplicada_falha(self):
        with self.assertRaises(ErroPortoTabular):
            self.parse(HTML+HTML)

    def test_cabecalho_duplicado_falha(self):
        contrato=ContratoTabular(
            "SANTOS",FONTE,
            {"navio":"Navio","produto":"navio"},
            "2026-10-19T07:00:00-03:00")
        with self.assertRaises(ErroPortoTabular):
            self.parse(contrato=contrato)

    def test_sem_produto_rejeita(self):
        html=HTML.replace("<td>SOJA</td>","<td></td>")
        with self.assertRaises(ErroPortoTabular):
            self.parse(html)

    def test_volumes_com_ponto_decimal_estrangeiro_rejeita(self):
        html=HTML.replace("1.234,50","1234.50")
        with self.assertRaises(ErroPortoTabular):
            self.parse(html)

    def test_nenhum_porto_na_lista_rejeita(self):
        contrato=ContratoTabular(
            "PORTO_FALSO",FONTE,{"navio":"Navio","produto":"Carga"},
            "2026-10-19T07:00:00-03:00")
        with self.assertRaises(ErroPortoTabular):
            self.parse(contrato=contrato)

    def test_publicacao_futura_rejeita(self):
        contrato=ContratoTabular(
            "SANTOS",FONTE,{"navio":"Navio","produto":"Carga"},
            "2026-10-20T07:00:00-03:00")
        with self.assertRaises(ErroPortoTabular):
            self.parse(contrato=contrato)


if __name__=="__main__":
    unittest.main()
