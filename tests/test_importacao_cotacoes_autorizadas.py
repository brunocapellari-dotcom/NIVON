"""Testes offline com cotações EXCLUSIVAMENTE sintéticas."""
import unittest
from copy import deepcopy
from nivon.importacao_cotacoes_autorizadas import (
    normalizar_arquivo_cotacoes, persistir_quarentena, ErroImportacaoCotacoes)
from nivon.historico_vintages import ArmazemVintages

HDR = "serie_id;produto;localidade;competencia;referencia;preco;unidade\n"
ROWS = ("SOJA_SORRISO_MT;Soja;Sorriso - MT;2026-10;2026-10-20;125,50;BRL/SC60KG\n"
        "MILHO_LRV_MT;Milho;Lucas do Rio Verde - MT;2026-10;2026-10-20;60,40;BRL/SC60KG\n")
URLS = {"CEPEA": "https://www.cepea.esalq.usp.br/br/indicador/soja.aspx",
        "IMEA": "https://www.imea.com.br/imea-site/indicador-soja"}

def montar(fonte="IMEA", txt=HDR+ROWS, **kwargs):
    return normalizar_arquivo_cotacoes(bruto=txt.encode(), fonte_id=fonte,
        fonte_url=URLS[fonte], edicao_id="EDICAO_SINTETICA_20261021",
        coletado_em="2026-10-21T15:00:00-04:00", **kwargs)

class TestImportacaoCotacoes(unittest.TestCase):
    def test_duas_fontes_csv_e_gate(self):
        for fonte in URLS:
            p = montar(fonte)
            self.assertEqual(p["linhas"], 2)
            self.assertEqual(p["registros"][0]["valor"], "125.50")
            self.assertFalse(p["api_confirmada"])
            self.assertFalse(p["autorizado_publicar"])
            self.assertFalse(p["autorizado_backtest"])
            self.assertFalse(p["registros"][0]["disponibilidade_verificada"])
            self.assertIsNone(p["registros"][0]["publicado_em"])

    def test_multiplos_dias_da_mesma_serie_e_replay(self):
        txt = (HDR + "SOJA_SORRISO_MT;Soja;Sorriso;2026-10;2026-10-19;120,01;BRL/SC60KG\n"
               + "SOJA_SORRISO_MT;Soja;Sorriso;2026-10;2026-10-20;120,02;BRL/SC60KG\n")
        pacote = montar(txt=txt)
        self.assertEqual(pacote["linhas"],2)
        self.assertNotEqual(pacote["registros"][0]["edicao_id"], pacote["registros"][1]["edicao_id"])
        self.assertTrue(pacote["registros"][0]["edicao_id"].endswith("REF_20261019"))
        db = ArmazemVintages()
        try:
            self.assertEqual(persistir_quarentena(db,pacote,operador_autorizou_importacao=True)["novas"],2)
            self.assertEqual(persistir_quarentena(db,pacote,operador_autorizou_importacao=True)["duplicadas"],2)
            self.assertEqual(db.contar(),2)
            self.assertIsNone(db.consultar_asof(dataset_id="IMEA_FISICO",serie_id="SOJA_SORRISO_MT",
                              competencia="2026-10",instante_decisao="2026-10-22T00:00:00Z"))
        finally:
            db.fechar()
        with self.assertRaises(ErroImportacaoCotacoes):
            montar(txt=txt.replace("2026-10-19", "2026-10-20"))

    def test_quatro_datas_sem_promocao_automatica(self):
        p = montar(publicado_em="2026-10-20T18:00:00-04:00",
                   disponivel_em="2026-10-20T19:00:00-04:00")
        self.assertEqual(p["registros"][0]["publicado_em"], "2026-10-20T22:00:00+00:00")
        self.assertFalse(p["registros"][0]["disponibilidade_verificada"])
        with self.assertRaises(ErroImportacaoCotacoes):
            montar(publicado_em="2026-10-21T18:00:00-04:00",
                   disponivel_em="2026-10-21T19:00:00-04:00")
        with self.assertRaises(ErroImportacaoCotacoes):
            montar(disponivel_em="2026-10-20T19:00:00-04:00")

    def test_rejeicao_de_malformacao_e_injecao(self):
        ruins = [
            HDR+ROWS.replace("125,50", "1.125,50"),
            HDR+ROWS.replace("125,50", "-125,50"),
            HDR+ROWS.replace("BRL/SC60KG", "BRL/SACA"),
            HDR+ROWS.replace("2026-10-20", "2027-10-20"),
            HDR+ROWS.replace("SOJA_SORRISO_MT", "MILHO_LRV_MT"),
            HDR+ROWS.replace("Sorriso - MT", "=CMD"),
            HDR+ROWS.replace("2026-10;2026-10-20", "2026-09;2026-10-20"),
            "preco;unidade\n1;BRL/T\n",
        ]
        for txt in ruins:
            with self.subTest(txt=txt[:30]), self.assertRaises(ErroImportacaoCotacoes):
                montar(txt=txt)

    def test_host_e_limites(self):
        with self.assertRaises(ErroImportacaoCotacoes):
            normalizar_arquivo_cotacoes(bruto=(HDR+ROWS).encode(), fonte_id="CEPEA",
                fonte_url="https://www.cepea.esalq.usp.br.attacker.test/indicador",
                edicao_id="TESTE", coletado_em="2026-10-21T15:00:00Z")
        for b in (b"", b"\\xff", b"a"*1_000_001, b"\\x00"):
            with self.subTest(size=len(b)), self.assertRaises(ErroImportacaoCotacoes):
                normalizar_arquivo_cotacoes(bruto=b, fonte_id="IMEA",
                    fonte_url=URLS["IMEA"], edicao_id="X",
                    coletado_em="2026-10-21T15:00:00Z")

    def test_quarentena_sqlite_replay_sem_asof(self):
        db = ArmazemVintages()
        try:
            pacote = montar()
            with self.assertRaises(PermissionError):
                persistir_quarentena(db, pacote)
            self.assertEqual(db.contar(), 0)
            r = persistir_quarentena(db, pacote, operador_autorizou_importacao=True)
            self.assertEqual(r["novas"], 2)
            self.assertEqual(db.contar(), 2)
            r = persistir_quarentena(db, pacote, operador_autorizou_importacao=True)
            self.assertEqual(r["duplicadas"], 2)
            self.assertIsNone(db.consultar_asof(dataset_id=pacote["dataset_id"],
                serie_id="SOJA_SORRISO_MT", competencia="2026-10",
                instante_decisao="2026-10-22T00:00:00Z"))
            adulterado = deepcopy(pacote)
            adulterado["registros"][0]["disponibilidade_verificada"] = True
            with self.assertRaises(ErroImportacaoCotacoes):
                persistir_quarentena(db, adulterado, operador_autorizou_importacao=True)
            adulterado = deepcopy(pacote)
            adulterado["registros"][0]["valor"] = "999.99"
            with self.assertRaises(ErroImportacaoCotacoes):
                persistir_quarentena(db, adulterado, operador_autorizou_importacao=True)
        finally:
            db.fechar()

if __name__ == "__main__":
    unittest.main()
