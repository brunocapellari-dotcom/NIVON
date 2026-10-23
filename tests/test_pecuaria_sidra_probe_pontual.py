"""Sondagem temporaria: expor APENAS dimensoes/codigos, nunca valores V.
Remover apos verificacao da resposta oficial no runner GitHub Actions.
"""
import json
import os
import unittest
from nivon.pecuaria_sidra_sondagem import _requisicao_https, _URL_VALORES

class TestSondagemEsquemaSIDRA(unittest.TestCase):
    def test_cabecalhos_reais_tres_tabelas(self):
        if (os.getenv("GITHUB_HEAD_REF") != "feat/pecuaria-inteligencia-20261020"
            or os.getenv("GITHUB_REPOSITORY") != "brunocapellari-dotcom/NIVON"):
            self.skipTest("teste pontual da branch pecuaria")
        for esp, tabela in (("BOVINO","1092"),("SUINO","1093"),("FRANGO","1094")):
            url = _URL_VALORES.format(tabela,"202602")
            res = _requisicao_https(url,timeout=7,limite=2_000_000)
            self.assertEqual(res["status_http"],200)
            doc=json.loads(res["corpo"].decode("utf-8-sig"))
            self.assertGreaterEqual(len(doc),2)
            dados = []
            for row in doc[1:]:
                dados.append({k:v for k,v in row.items() if k not in ("V","MN","D1N","D2N")})
            header={k:v for k,v in doc[0].items() if k not in ("V","MN")}
            print("ESQUEMA_SIDRA_VERIFICADO="+json.dumps(
                {"especie":esp,"tabela":tabela,"cabecalho":header,
                 "amostras_dimensoes_sem_valores":dados},ensure_ascii=False,sort_keys=True),flush=True)
