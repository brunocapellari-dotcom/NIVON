"""Ensaio integrado de lote inteiro. Todos os JSONs são sintéticos."""
import json
from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_lote import executar_lote_sidra_offline, resumir_lote_sidra
from nivon.pecuaria_sidra_arquivo import arquivar_lote_sidra_atomico
from nivon.pecuaria_sidra_sondagem import sondar_sidra_abate, sondar_tres_cadeias

TABLES = {"BOVINO": "1092", "SUINO": "1093", "FRANGO": "1094"}
DIM = {"territorio": "D1C", "periodo": "D2C", "variavel": "D3C",
       "referencia_temporal": "D4C", "inspecao": "D5C"}
VARIABLES = {"9999": "ABATE_CABECAS", "8888": "PESO_CARCACAS_KG"}
PUB1 = "2026-09-21T12:00:00-03:00"
PUB2 = "2026-10-06T12:00:00-03:00"
COL1 = "2026-10-20T12:00:00-04:00"
COL2 = "2026-10-22T12:00:00-04:00"


def pacote(especie, *, cabecas=100, pub=PUB1, coleta=COL1):
    table = TABLES[especie]
    dims = dict(DIM)
    totais = {"referencia_temporal": "0", "inspecao": "0"}
    if especie == "BOVINO":
        dims["rebanho"] = "D6C"
        totais["rebanho"] = "0"
    header = {x: x + " (codigo)" for x in dims.values()}
    header.update({"NC": "nivel", "MN": "unidade", "V": "valor"})
    rows = []
    for nivel, geo in (("1", "1"), ("3", "51")):
        for codigo, valor in (("9999", cabecas),
                              ("8888", cabecas * 200)):
            row = {"NC": nivel, "V": str(valor),
                   "MN": "Cabeças" if codigo == "9999" else "Quilogramas",
                   "D1C": geo, "D2C": "202602", "D3C": codigo,
                   "D4C": "0", "D5C": "0"}
            if especie == "BOVINO":
                row["D6C"] = "0"
            rows.append(row)
    return {
        "especie": especie, "tabela_sidra": table,
        "url_valores": f"https://apisidra.ibge.gov.br/values/t/{table}/n1/1/p/202602/v/allxp/h/y",
        "url_metadados": f"https://servicodados.ibge.gov.br/api/v3/agregados/{table}/metadados",
        "bruto_valores": json.dumps([header, *rows], ensure_ascii=False).encode(),
        "bruto_metadados": json.dumps({"id": int(table),
                                       "variaveis": [{"id": 9999},
                                                     {"id": 8888}]}).encode(),
        "publicacao_declarada": pub, "coleta_declarada": coleta,
        "dimensoes": dims, "totais": totais, "variaveis": dict(VARIABLES),
    }


def simulacao(url, *, timeout, limite):
    if "/metadados" in url:
        table = url.split("/")[-2]
        body = json.dumps({"id": int(table)}).encode()
    else:
        body = json.dumps([{"V": "Valor"}, {"V": "100"}]).encode()
    return {"status_http": 200, "content_type": "application/json",
            "corpo": body}


class TestLoteInteiro(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.banco = Path(self.tmp.name) / "sidra-local.sqlite"
        self.capturas = [pacote(especie) for especie in TABLES]
        self.kw = {"corte_asof": "2026-10-23T00:00:00-04:00",
                   "status_fonte": "APROVADA",
                   "operacoes_autorizadas": {"LEITURA", "ARMAZENAMENTO"}}

    def executar(self, *, capturas=None, **changes):
        p = dict(self.kw)
        p.update(changes)
        return executar_lote_sidra_offline(
            capturas=self.capturas if capturas is None else capturas,
            **p)

    def test_dry_run_tres_especies_nao_grava(self):
        out = self.executar()
        self.assertFalse(self.banco.exists())
        self.assertFalse(out["persistido"])
        self.assertEqual(set(out["historicos"]), set(TABLES))
        self.assertEqual(out["qualidade"]["registros_normalizados"], 12)
        self.assertEqual(out["qualidade"]["n_capturas"], 3)
        self.assertEqual(out["qualidade"]["ufs_nao_verificadas"], 6)
        self.assertTrue(all(not h["amostra_real_homologada"]
                            for h in out["historicos"].values()))
        resumo = resumir_lote_sidra(out)
        self.assertFalse(resumo["publicacao_permitida"])
        self.assertEqual(len(resumo["capturas"]), 3)
        json.dumps(resumo)

    def test_persistencia_transacional_tres_especies_e_reprocessamento(self):
        out = self.executar(banco=self.banco, persistir=True)
        self.assertTrue(out["persistido"])
        self.assertTrue(out["persistencia_transacional"])
        self.assertEqual(len(set(out["ids_capturas"])), 3)
        self.assertEqual(out["qualidade"]["registros_normalizados"], 12)
        again = self.executar(banco=self.banco, persistir=True)
        self.assertEqual(again["ids_capturas"], out["ids_capturas"])
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], 3)

    def test_preflight_falha_nao_toca_banco(self):
        packets = deepcopy(self.capturas)
        packets[-1]["variaveis"] = {"9999": "ABATE_CABECAS", "777": "PESO_CARCACAS_KG"}
        with self.assertRaises(DadoInvalido):
            self.executar(capturas=packets, banco=self.banco, persistir=True)
        self.assertFalse(self.banco.exists())

    def test_preflight_direitos_fail_closed(self):
        with self.assertRaises(PermissionError):
            self.executar(banco=self.banco, persistir=True,
                          status_fonte="PENDENTE")
        self.assertFalse(self.banco.exists())

    def test_revisao_frango_sem_antecipar_coleta(self):
        packets = [pacote("FRANGO"), pacote("FRANGO", cabecas=120,
                                             pub=PUB2, coleta=COL2)]
        antes = self.executar(capturas=packets,
                              corte_asof="2026-10-21T00:00:00-04:00")
        hist_antigo = antes["historicos"]["FRANGO"]
        self.assertEqual(len(hist_antigo["revisoes"]), 0)
        self.assertEqual({x.valor for x in hist_antigo["observacoes"]
                          if x.indicador == "ABATE_CABECAS"}, {100})
        depois = self.executar(capturas=packets)
        self.assertEqual(len(depois["historicos"]["FRANGO"]["revisoes"]), 4)
        self.assertEqual(depois["qualidade"]["total_revisoes_por_corte"], 4)
        self.assertEqual({x.valor for x in depois["historicos"]["FRANGO"]["observacoes"]
                          if x.indicador == "ABATE_CABECAS"}, {120})

    def test_rollback_lote_com_conflito_do_banco(self):
        base = [pacote("SUINO")]
        self.executar(capturas=base, banco=self.banco, persistir=True)
        novo = pacote("FRANGO")
        conflito = pacote("SUINO", cabecas=900)  # mesma captura, hash divergente
        with self.assertRaisesRegex(DadoInvalido, "conflito"):
            self.executar(capturas=[novo, conflito], banco=self.banco,
                          persistir=True)
        with sqlite3.connect(self.banco) as cx:
            especies = [r[0] for r in cx.execute("SELECT especie FROM capturas_sidra")]
        self.assertEqual(especies, ["SUINO"])

    def test_entrada_duplicada_sem_fabricar_duas_coletas(self):
        with self.assertRaises(DadoInvalido):
            self.executar(capturas=[self.capturas[0], self.capturas[0]])
        self.assertFalse(self.banco.exists())

    def test_sem_cobertura_uf_nao_agrega_nacionalmente(self):
        out = self.executar()
        self.assertEqual({v["status"] for v in out["auditoria_territorial"]},
                         {"COBERTURA_NAO_VERIFICADA"})
        self.assertTrue(all(a["soma_ufs"] is None
                            for a in out["auditoria_territorial"]))

    def test_contrato_varias_categorias_nao_autorizadas(self):
        packets = deepcopy(self.capturas)
        rows = json.loads(packets[0]["bruto_valores"])
        rows[1]["D5C"] = "1"
        packets[0]["bruto_valores"] = json.dumps(rows).encode()
        with self.assertRaises(DadoInvalido):
            self.executar(capturas=packets)

    def test_lote_25_capturas_bloqueado(self):
        with self.assertRaises(DadoInvalido):
            self.executar(capturas=self.capturas * 9)

    def test_sondagem_gera_plano_sem_rede(self):
        out = sondar_tres_cadeias(periodo="202602")
        self.assertEqual(len(out["cadeias"]), 3)
        self.assertTrue(all(not x["rede_executada"] for x in out["cadeias"]))
        self.assertEqual({x["tabela_sidra"] for x in out["cadeias"]},
                         {"1092", "1093", "1094"})

    def test_sondagem_simulada_seis_respostas(self):
        out = sondar_tres_cadeias(periodo="202602", transporte=simulacao)
        self.assertEqual(len(out["cadeias"]), 3)
        for chain in out["cadeias"]:
            self.assertEqual(chain["modo"], "SIMULACAO")
            self.assertFalse(chain["homologado"])
            self.assertTrue(all(x["status"] == "FORMATO_PRELIMINAR_CONFIRMADO"
                                for x in chain["resultados"].values()))
            self.assertFalse(chain["rede_executada"])

    def test_sondagem_falha_isolada_sem_falso_positivo(self):
        def falha(url, *, timeout, limite):
            if "/metadados" in url:
                return {"status_http": 500, "content_type": "text/html", "corpo": b"erro"}
            return {"status_http": 200, "content_type": "application/json",
                    "corpo": b'{"v":"nao e lista"}'}
        chain = sondar_sidra_abate(especie="FRANGO", periodo="202602",
                                   transporte=falha)
        self.assertEqual({x["status"] for x in chain["resultados"].values()},
                         {"ERRO_NAO_HOMOLOGADO"})
        self.assertFalse(chain["homologado"])

    def test_sondagem_periodo_invalido(self):
        for periodo in ("199604", "202613", "latest", "202601/redirect"):
            with self.assertRaises(DadoInvalido):
                sondar_sidra_abate(especie="BOVINO", periodo=periodo)


if __name__ == "__main__":
    unittest.main()
