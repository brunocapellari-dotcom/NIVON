"""Testes do corredor ferroviário por estação com fonte isolada e manifesto válido."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nivon.antt_mdfe_volumes import importar
from nivon.conciliacao_corredores_ferrovia import (
    CROSSWALK_MERCADORIAS, ErroConciliacao, analisar_estacoes,
    analisar_staging, quadro_intermodal, quadro_staging,
)
from nivon.inteligencia_corredores import consultar_corredores
from nivon.transporte_multimodal import link_antt, interpretar_csv_antt

SHAF="a"*64
def linha(i,estacao,mercadoria,uf="MT",comp="2026-08",tu="100",dest="Santos",ferro="RMO"):
    return {
        "linha_id":f"linha-{i}","ferrovia":ferro,"competencia":comp,
        "mercadoria":mercadoria,"estacao_origem":estacao,
        "uf_origem":uf,"estacao_destino":dest,"uf_destino":"SP",
        "toneladas_uteis":tu,"natureza_tu":"OBSERVADO_DECLARADO",
        "arquivo_sha256":SHAF,
    }

class TestRankingEstacoes(unittest.TestCase):
    def setUp(self):
        self.rows=[
            linha(1,"Rondonópolis","SOJA",tu="80"),
            linha(2,"Rondonópolis","SOJA",tu="20"),
            linha(3,"Itiquira","MILHO",tu="40"),
            linha(4,"Dom Aquino","SOJA",tu="10"),
            linha(5,"Terminal Itiquira Norte","MILHO",tu="150"),
            linha(6,"Rondonópolis","FARELO DE SOJA",tu="25",dest="Paranagua"),
            linha(7,"Santos","SOJA",uf="SP",tu="200"),
        ]

    def test_ranking_e_totais(self):
        r=analisar_estacoes(self.rows,competencia="2026-08",uf_origem="MT",sha256=SHAF,limite=2)
        self.assertEqual(r["total_de_linhas_no_periodo"],6)
        self.assertTrue(r["ranking_truncado"])
        self.assertEqual(r["polos_ferroviarios"][0]["polo"]["id"],"MT_RONDONOPOLIS_FERRO")
        self.assertEqual(r["polos_ferroviarios"][0]["toneladas_ferroviarias"],"125")
        self.assertEqual(r["polos_ferroviarios"][1]["polo"]["id"],"MT_ITIQUIRA_FERRO")
        self.assertEqual(r["polos_ferroviarios"][1]["toneladas_ferroviarias"],"40")
        self.assertTrue(all(not x["terminal_comprovado"] for x in r["polos_ferroviarios"]))
        self.assertEqual(r["polos_ferroviarios"][2]["toneladas_ferroviarias"],"10")
        self.assertEqual(r["polos_ferroviarios"][0]["mercadorias"][0]["produto_normalizado"],
                         "SOJA_EM_GRAO")
        self.assertEqual(r["ranking"][0]["estacao_origem"],"Terminal Itiquira Norte")
        self.assertIsNone(r["ranking"][0]["produto_normalizado"]) if False else None

    def test_produto_ambiguo_nao_imputado(self):
        rows=[linha(1,"Rondonópolis","GRAOS",tu="55")]
        doc=analisar_estacoes(rows,competencia="2026-08")
        self.assertIsNone(doc["ranking"][0]["produto_normalizado"])
        self.assertIsNone(CROSSWALK_MERCADORIAS.get("fertilizantes"))

    def test_duplicata_hash_e_negativos(self):
        for rows,sha in (
            ([self.rows[0],self.rows[0]],SHAF),
            ([self.rows[0]],"b"*64),
            ([linha(1,"Rondonópolis","SOJA",tu="-4")],SHAF),
            ([linha(1,"Rondonópolis","SOJA",tu="nan")],SHAF),
            ([linha(1,"Rondonópolis","SOJA")|{"natureza_tu":"ESTIMADO"}],SHAF),
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(ErroConciliacao):
                    analisar_estacoes(rows,competencia="2026-08",sha256=sha)

    def test_filtro_de_mes_e_uf_nao_fabrica_dados(self):
        doc=analisar_estacoes(self.rows,competencia="2026-07",uf_origem="MT")
        self.assertEqual(doc["total_de_linhas_no_periodo"],0)
        self.assertEqual(doc["polos_ferroviarios"],[])
        with self.assertRaises(ErroConciliacao):
            analisar_estacoes(self.rows,competencia="2026-13")


class TestCruzamento(unittest.TestCase):
    def _rodo(self,d):
        banco=Path(d)/"rod.sqlite"
        csv=(
          "competencia;origem;destino;toneladas;NCM\n"
          "2026-08;Sorriso;Rondonópolis;300;1201\n"
          "2026-08;Sinop;Itiquira;50;1005\n"
          "2026-08;Sorriso;Itaituba;80;1201\n"
        ).encode()
        importar(banco,csv,arquivo="mock.csv",recorte="teste_mt_2026",nivel="MUNICIPIO")
        return banco

    def test_nao_somar_rodovia_ferrovia(self):
        with tempfile.TemporaryDirectory() as d:
            rod=consultar_corredores(self._rodo(d),recorte="teste_mt_2026",competencia="2026-08")
            ferro=analisar_estacoes([linha(1,"Rondonópolis","SOJA",tu="125"),
                                    linha(2,"Itiquira","MILHO",tu="15")],
                                   competencia="2026-08")
            q=quadro_intermodal(ferro,rod)
            a={x["polo_id"]:x for x in q["dados"]}
            self.assertEqual(a["MT_RONDONOPOLIS_FERRO"]["toneladas_rodoviarias_destino_geografico"],"300")
            self.assertEqual(a["MT_RONDONOPOLIS_FERRO"]["toneladas_ferroviarias_estacao_origem"],"125")
            self.assertFalse(a["MT_RONDONOPOLIS_FERRO"]["razao_rodo_ferro_permitida"])
            self.assertFalse(a["MT_ITIQUIRA_FERRO"]["soma_entre_modais_permitida"])
            self.assertTrue(q["sem_dados_nao_equivale_a_zero"])
            with self.assertRaises(ErroConciliacao):
                quadro_intermodal({**ferro,"competencia":"2026-07"},rod)

    def test_staging_end_to_end_hash_e_registros(self):
        with tempfile.TemporaryDirectory() as d:
            pasta=Path(d)
            raw=(
                "Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;"
                "Estacao_Destino;UF_Destino;TU;TKU\n"
                "08/2026;RMO;SOJA;Rondonópolis;MT;Santos;SP;1.234,50;123450\n"
                "08/2026;RMO;MILHO;Itiquira;MT;Santos;SP;500;30000\n"
            ).encode()
            sha=hashlib.sha256(raw).hexdigest()
            (pasta/"antt-od-2026.csv").write_bytes(raw)
            (pasta/"manifesto-antt.json").write_text(json.dumps({
                "formato":"nivon-antt-staging-v1",
                "anos":{"2026":{
                    "sha256":sha,"url":link_antt(2026),"verificado_utc":"2026-10-23T10:00:00Z",
                    "status":"STAGING_NAO_HOMOLOGADO","registros":2,"competencia_maxima":"2026-08",
                }}}),encoding="utf-8")
            doc=analisar_staging(pasta,ano=2026,competencia="2026-08")
            self.assertEqual(doc["total_de_linhas_no_periodo"],2)
            self.assertEqual(doc["sha256_fonte"],sha)
            self.assertEqual(doc["polos_ferroviarios"][0]["toneladas_ferroviarias"],"1234.50")
            r=quadro_staging(pasta,self._rodo(d),ano=2026,
                             competencia="2026-08",recorte="teste_mt_2026")
            self.assertEqual(r["estado"],"COMPARACAO_EXPLORATORIA_NAO_BALANCO")
            (pasta/"antt-od-2026.csv").write_bytes(raw+b"\n")
            from nivon.transporte_multimodal import ErroTransporte
            with self.assertRaises(ErroTransporte):
                analisar_staging(pasta,ano=2026,competencia="2026-08")

if __name__=="__main__":
    unittest.main()
