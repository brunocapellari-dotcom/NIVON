"""CEPEA no painel: coleta como disponibilidade conservadora (decisão #303).

Fixtures sintéticos e artificiais; não são cotações reais.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.adaptadores_operacionais import ler_cepea_ledger_sqlite
from nivon.ingestao_fontes_reais import gravar_lote
from nivon.painel_operacional import ErroMotor, tendencia_precos
from nivon.ponte_painel_fontes import analisar_fontes

AS_OF = "2026-10-26T12:00:00Z"
DIAS = [13, 14, 15, 16, 19, 20, 21, 22, 23]


def obs(dia, valor, *, flag=True, classe="PRECO_FISICO"):
    o = {
        "identidade": f"soja_paranagua|2026-10-{dia:02d}",
        "data_referencia": f"2026-10-{dia:02d}", "data_publicacao": None,
        "data_coleta": f"2026-10-{dia:02d}T22:00:00Z",
        "valor": str(valor), "unidade": "BRL/sc60kg", "natureza": "INFORMADO",
        "campos": {"serie_id": "CEPEA:soja_paranagua", "classe": classe,
                   "produto": "soja", "praca": "Paranaguá/PR",
                   "tipo_preco": "INDICADOR_CEPEA", "regime": "NAO_APLICAVEL"},
    }
    if flag:
        o["tipo_disponibilidade"] = "DATA_COLETA_CONSERVADORA"
    return o


class TendenciaSemPublicacao(unittest.TestCase):
    def test_sem_marcacao_continua_excluido(self):
        r = tendencia_precos([obs(d, 100 + i, flag=False) for i, d in enumerate(DIAS)],
                             classe="PRECO_FISICO", serie_id="CEPEA:soja_paranagua", as_of=AS_OF)
        self.assertEqual(r["status"], "DADOS_INSUFICIENTES")
        self.assertEqual(r["registros_excluidos"], len(DIAS))

    def test_coleta_como_disponibilidade_produz_tendencia(self):
        r = tendencia_precos([obs(d, 100 + 2 * i) for i, d in enumerate(DIAS)],
                             classe="PRECO_FISICO", serie_id="CEPEA:soja_paranagua", as_of=AS_OF)
        self.assertEqual(r["status"], "SHADOW_READY")
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["observacoes_disponiveis_pela_coleta"], len(DIAS))
        self.assertFalse(r["publicavel"])

    def test_coleta_futura_nao_vaza_point_in_time(self):
        linhas = [obs(d, 100) for d in DIAS]
        linhas[-1]["data_coleta"] = "2026-10-27T01:00:00Z"
        r = tendencia_precos(linhas, classe="PRECO_FISICO",
                             serie_id="CEPEA:soja_paranagua", as_of=AS_OF)
        self.assertEqual(r["observacoes_disponiveis_pela_coleta"], len(DIAS) - 1)
        self.assertEqual(r["registros_excluidos"], 1)

    def test_marcacao_nao_vale_para_frete(self):
        linhas = [obs(d, 100, classe="FRETE_ANUNCIADO") for d in DIAS]
        for x in linhas:
            x["campos"].update(origem="A", destino="B", transportadora="T", regime="PJ",
                               equipamento="E", ponto_embarque="P", terminal="X",
                               pedagio="ADICIONAL", tipo_preco="BASE")
        r = tendencia_precos(linhas, classe="FRETE_ANUNCIADO",
                             serie_id="CEPEA:soja_paranagua", as_of=AS_OF)
        self.assertEqual(r["status"], "DADOS_INSUFICIENTES")


class LedgerCepea(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.banco = self.root / "fontes_reais.sqlite"

    def gravar(self, estado, base=100, serie="soja_paranagua"):
        coleta = datetime(2026, 10, 23, 22, tzinfo=timezone.utc)
        return gravar_lote(
            banco=self.banco, diretorio_bruto=self.root / "raw",
            dataset_id="CEPEA_PRECOS_FISICOS", origem="https://www.cepea.org.br/br/indicador/soja.aspx",
            raw=f"<html>fixture {estado} {base} {serie}</html>".encode(), tipo="text/html",
            coletado_em=coleta, estado=estado, registros=[{
                "identidade": f"{serie}|2026-10-{d:02d}", "referencia": f"2026-10-{d:02d}",
                "publicacao": None, "natureza": "INFORMADO", "unidade": "BRL/sc60kg",
                "valor": str(base + i),
                "campos": {"serie_id": serie, "produto": "soja", "praca": "Paranaguá/PR"},
            } for i, d in enumerate(DIAS)])

    def test_quarentena_exige_opt_in(self):
        self.gravar("QUARANTINED")
        r = ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="soja_paranagua", as_of=AS_OF)
        self.assertEqual(r["observacoes"], [])
        r = ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="soja_paranagua",
                                    as_of=AS_OF, aceitar_quarentena=True)
        self.assertEqual(len(r["observacoes"]), len(DIAS))
        self.assertFalse(r["homologado"])
        self.assertFalse(r["publicacao_declarada"])
        o = r["observacoes"][0]
        self.assertIsNone(o["data_publicacao"])
        self.assertEqual(o["tipo_disponibilidade"], "DATA_COLETA_CONSERVADORA")
        self.assertRegex(o["fingerprint"], r"^[0-9a-f]{64}$")

    def test_filtra_serie_e_coleta_posterior_ao_corte(self):
        self.gravar("NORMALIZED")
        self.gravar("NORMALIZED", base=50, serie="soja_parana")
        r = ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="soja_parana", as_of=AS_OF)
        self.assertEqual({o["campos"]["serie_id"] for o in r["observacoes"]}, {"CEPEA:soja_parana"})
        self.assertTrue(r["homologado"])
        antes = ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="soja_parana",
                                        as_of="2026-10-23T21:00:00Z")
        self.assertEqual(antes["observacoes"], [])

    def test_ledger_nao_e_alterado(self):
        self.gravar("NORMALIZED")
        antes = self.banco.read_bytes()
        ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="soja_paranagua", as_of=AS_OF)
        self.assertEqual(antes, self.banco.read_bytes())

    def test_entradas_invalidas(self):
        with self.assertRaises(ErroMotor):
            ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="soja_paranagua", as_of=AS_OF)
        self.gravar("NORMALIZED")
        with self.assertRaises(ErroMotor):
            ler_cepea_ledger_sqlite(banco=str(self.banco), serie_id="Soja; DROP", as_of=AS_OF)

    def test_painel_integra_serie_cepea(self):
        self.gravar("NORMALIZED")
        painel = analisar_fontes({"cepea_sqlite": [
            {"banco": str(self.banco), "serie_id": "soja_paranagua"}]}, as_of=AS_OF)
        quant = painel["quantitativo"]
        self.assertEqual(len(quant), 1)
        self.assertEqual(quant[0]["status"], "SHADOW_READY")
        self.assertEqual(quant[0]["observacoes_disponiveis_pela_coleta"], len(DIAS))
        self.assertEqual(painel["fontes_cepea"][0]["linhas"], len(DIAS))
        self.assertEqual(painel["status"], "ANALISE_SHADOW_NAO_HOMOLOGADA")

    def test_painel_rejeita_serie_cepea_duplicada(self):
        self.gravar("NORMALIZED")
        cfg = {"banco": str(self.banco), "serie_id": "soja_paranagua"}
        with self.assertRaises(ErroMotor):
            analisar_fontes({"cepea_sqlite": [cfg, dict(cfg)]}, as_of=AS_OF)


if __name__ == "__main__":
    unittest.main()
