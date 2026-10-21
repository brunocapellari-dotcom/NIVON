"""Testes 100% sintéticos da ponte arquivo -> normalizador -> vintage."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_arquivo import (
    arquivar_pacote_sidra_offline, recuperar_pacote_sidra_offline,
)
from nivon.pecuaria_sidra_pacote import normalizar_captura_arquivada_sidra
from nivon.pecuaria_sidra_vintages import historico_sidra_asof

DIM = {"territorio": "D1C", "periodo": "D2C", "variavel": "D3C",
       "referencia_temporal": "D4C", "inspecao": "D5C"}
TOTAIS = {"referencia_temporal": "0", "inspecao": "0"}
VARIAVEIS = {"9999": "ABATE_CABECAS", "8888": "PESO_CARCACAS_KG"}
HEADER = {x: x + " (codigo)" for x in DIM.values()}
HEADER.update({"NC": "nivel", "MN": "unidade", "V": "valor"})


def linha(indicador, valor):
    return {
        "NC": "1", "V": valor,
        "MN": "Cabeças" if indicador == "9999" else "Quilogramas",
        "D1C": "1", "D2C": "202602", "D3C": indicador,
        "D4C": "0", "D5C": "0",
    }


VALORES = json.dumps([HEADER, linha("9999", "50"),
                      linha("8888", "100000")], ensure_ascii=False).encode("utf-8")
META = b'{"id":1094,"mock":true}'


class TestPonteSIDRA(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.banco = Path(self.tmp.name) / "arquivo.sqlite"
        self.permissoes = {"LEITURA", "ARMAZENAMENTO"}
        self.arch_args = {
            "banco": self.banco, "especie": "FRANGO",
            "tabela_sidra": "1094", "bruto_valores": VALORES,
            "bruto_metadados": META,
            "url_valores": "https://apisidra.ibge.gov.br/values/t/1094/n1/1/p/202602/v/allxp/h/y",
            "url_metadados": "https://servicodados.ibge.gov.br/api/v3/agregados/1094/metadados",
            "publicacao_declarada": "2026-09-21T09:30:00-03:00",
            "coleta_declarada": "2026-10-21T09:30:00-04:00",
            "status_fonte": "APROVADA",
            "operacoes_autorizadas": self.permissoes,
        }

    def capturar(self):
        return arquivar_pacote_sidra_offline(**self.arch_args)

    def normalizar(self, id_captura, **kwargs):
        return normalizar_captura_arquivada_sidra(
            **dict(banco=self.banco, id_captura=id_captura,
                   especie="FRANGO", tabela_sidra="1094",
                   dimensoes=DIM, totais=TOTAIS, variaveis=VARIAVEIS,
                   status_fonte="APROVADA",
                   operacoes_autorizadas=self.permissoes, **kwargs))

    def test_bytes_originais_integridade_e_datas_do_banco(self):
        cap = self.capturar()
        raw = recuperar_pacote_sidra_offline(
            banco=self.banco, id_captura=cap["id"])
        self.assertEqual(raw["id_captura"], cap["id"])
        self.assertEqual(raw["publicacao_declarada"], "2026-09-21T12:30:00+00:00")
        self.assertEqual(raw["coleta_declarada"], "2026-10-21T13:30:00+00:00")
        self.assertEqual(raw["url_metadados"], self.arch_args["url_metadados"])
        self.assertEqual(raw["sha256_valores"], sha256(VALORES).hexdigest())
        self.assertFalse(raw["timestamps_autenticados"])

    def test_integracao_ponta_a_ponta_arquivamento_parser_vintage(self):
        cap = self.capturar()
        r = self.normalizar(cap["id"])
        self.assertEqual([x.valor for x in r["observacoes"]], [50, 100000])
        self.assertEqual(r["origem_sha256"], cap["sha256_valores"])
        self.assertEqual(r["sha256_metadados"], cap["sha256_metadados"])
        self.assertTrue(r["identidade_arquivo_verificada"])
        for atributo in ("mapa_dimensional_homologado", "amostra_real_homologada",
                         "resposta_http_autenticada", "timestamps_autenticados",
                         "coleta_real_executada", "previsao_homologada"):
            self.assertFalse(r[atributo], atributo)
        before = historico_sidra_asof(
            snapshots=[r], especie="FRANGO", tabela_sidra="1094",
            corte_asof="2026-10-20T23:59:59-04:00")
        self.assertEqual(before["observacoes"], [])
        after = historico_sidra_asof(
            snapshots=[r], especie="FRANGO", tabela_sidra="1094",
            corte_asof="2026-10-22T00:00:00-04:00")
        self.assertEqual(len(after["observacoes"]), 2)
        self.assertFalse(after["amostra_real_homologada"])

    def test_nao_aceita_sobreposicao_de_especie(self):
        cap = self.capturar()
        with self.assertRaises(DadoInvalido):
            self.normalizar(cap["id"], especie="SUINO", tabela_sidra="1093")

    def test_sem_permissoes_nao_faz_leitura(self):
        cap = self.capturar()
        for perms in ({"ARMAZENAMENTO"}, {"LEITURA"}):
            with self.assertRaises(PermissionError):
                self.normalizar(cap["id"], operacoes_autorizadas=perms)

    def test_parser_nao_presume_variaveis_oficiais(self):
        cap = self.capturar()
        with self.assertRaises(DadoInvalido):
            self.normalizar(cap["id"], variaveis={
                "284": "ABATE_CABECAS", "285": "PESO_CARCACAS_KG"
            })

    def test_recuperacao_nao_aceita_metadados_alterados(self):
        cap = self.capturar()
        with sqlite3.connect(self.banco) as cx:
            cx.execute("DROP TRIGGER sidra_sem_update")
            cx.execute("UPDATE capturas_sidra SET bruto_metadados=? WHERE id=?",
                       (b'{"id":1093}', cap["id"]))
        with self.assertRaisesRegex(DadoInvalido, "integridade"):
            self.normalizar(cap["id"])

    def test_antigo_esquema_nao_gera_efeitos_ddl(self):
        with sqlite3.connect(self.banco) as cx:
            cx.execute("""CREATE TABLE capturas_sidra(
                id INTEGER PRIMARY KEY, especie TEXT,
                tabela_sidra TEXT, url_valores TEXT, url_metadados TEXT,
                coleta_declarada TEXT, sha256_valores TEXT,
                sha256_metadados TEXT,
                UNIQUE(especie,tabela_sidra,url_valores,url_metadados,
                       coleta_declarada,sha256_valores,sha256_metadados))""")
            sql_before = cx.execute("SELECT sql FROM sqlite_master WHERE name='capturas_sidra'").fetchone()[0]
        with self.assertRaisesRegex(DadoInvalido, "esquema SIDRA legado"):
            self.capturar()
        with sqlite3.connect(self.banco) as cx:
            sql_after = cx.execute("SELECT sql FROM sqlite_master WHERE name='capturas_sidra'").fetchone()[0]
            triggers = cx.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        self.assertEqual(sql_before, sql_after)
        self.assertEqual(triggers, 0)


if __name__ == "__main__":
    unittest.main()
