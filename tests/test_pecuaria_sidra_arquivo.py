"""Provas sinteticas do arquivo de evidencias; nao coleta dados IBGE."""
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

VAL = json.dumps([
    {"NC": "Nivel", "V": "Valor", "D1C": "UF"},
    {"NC": "1", "V": "100", "D1C": "1"},
]).encode()
META = json.dumps({"id": 1092, "nome": "APENAS MOCK"}).encode()
BASE = {
    "especie": "BOVINO", "tabela_sidra": "1092",
    "url_valores": "https://apisidra.ibge.gov.br/values/t/1092/n1/1/p/202602/v/allxp/h/y",
    "url_metadados": "https://servicodados.ibge.gov.br/api/v3/agregados/1092/metadados",
    "bruto_valores": VAL, "bruto_metadados": META,
    "publicacao_declarada": "2026-09-21T10:00:00-03:00",
    "coleta_declarada": "2026-10-21T08:15:00-04:00",
    "status_fonte": "APROVADA",
    "operacoes_autorizadas": {"LEITURA", "ARMAZENAMENTO"},
}


class TestArquivoAbateSIDRA(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.banco = Path(self.temp.name) / "evidencia-sidra.sqlite"

    def arquivar(self, **kw):
        return arquivar_pacote_sidra_offline(
            **dict(BASE, banco=self.banco, **kw))

    def test_roundtrip_sem_declarar_homologacao(self):
        capt = self.arquivar()
        self.assertEqual(capt["id"], 1)
        self.assertFalse(capt["dados_reais_verificados"])
        self.assertFalse(capt["timestamps_autenticados"])
        self.assertEqual(capt["status"], "ARQUIVADO_NAO_HOMOLOGADO")
        r = recuperar_pacote_sidra_offline(banco=self.banco, id_captura=1)
        self.assertEqual(r["bruto_valores"], VAL)
        self.assertEqual(r["bruto_metadados"], META)
        self.assertEqual(r["sha256_valores"], sha256(VAL).hexdigest())
        self.assertEqual(r["sha256_metadados"], sha256(META).hexdigest())
        self.assertFalse(r["dados_reais_verificados"])

    def test_retry_idempotente_nao_cria_registro_novo(self):
        a = self.arquivar()
        b = self.arquivar()
        self.assertEqual(a["id"], b["id"])
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], 1)

    def test_distinta_coleta_conserva_outra_edicao(self):
        x = self.arquivar()
        y = self.arquivar(coleta_declarada="2026-10-22T08:15:00-04:00")
        self.assertNotEqual(x["id"], y["id"])
        self.assertEqual(
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=x["id"])["bruto_valores"],
            VAL)

    def test_tabelas_1092_1093_1094_contrato(self):
        for i, especie in enumerate(("BOVINO", "SUINO", "FRANGO"), 1):
            table = {"BOVINO": "1092", "SUINO": "1093", "FRANGO": "1094"}[especie]
            p = self.arquivar(
                especie=especie, tabela_sidra=table,
                url_valores=f"https://apisidra.ibge.gov.br/values/t/{table}/n1/1/p/202602/v/allxp/h/y",
                url_metadados=f"https://servicodados.ibge.gov.br/api/v3/agregados/{table}/metadados",
                bruto_metadados=json.dumps({"id": table, "mock": True}).encode())
            self.assertEqual(p["id"], i)

    def test_nao_permite_mutar_ou_excluir(self):
        self.arquivar()
        with sqlite3.connect(self.banco) as cx:
            with self.assertRaises(sqlite3.IntegrityError):
                cx.execute("UPDATE capturas_sidra SET especie='FRANGO' WHERE id=1")
            with self.assertRaises(sqlite3.IntegrityError):
                cx.execute("DELETE FROM capturas_sidra WHERE id=1")

    def test_detecta_corrompimento_de_bytes(self):
        self.arquivar()
        # Apenas tentativa maliciosa simulada: remover trigger fora do contrato.
        with sqlite3.connect(self.banco) as cx:
            cx.execute("DROP TRIGGER sidra_sem_update")
            cx.execute("UPDATE capturas_sidra SET bruto_valores = ? WHERE id = 1",
                       (b'[{"V": "9"}]',))
        with self.assertRaisesRegex(DadoInvalido, "integridade"):
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=1)

    def test_nao_arquiva_sem_permissoes(self):
        for kw in ({"status_fonte": "PENDENTE"},
                   {"operacoes_autorizadas": {"LEITURA"}}):
            with self.assertRaises(PermissionError):
                self.arquivar(**kw)
        self.assertFalse(self.banco.exists())

    def test_rejeita_endpoints_nao_oficiais_e_mismatched(self):
        for kw in (
            {"url_valores": "http://apisidra.ibge.gov.br/values/t/1092/n1/1"},
            {"url_valores": "https://apisidra.ibge.gov.br.evil.com/values/t/1092/n1/1"},
            {"url_valores": "https://apisidra.ibge.gov.br/values/t/1093/n1/1"},
            {"url_metadados": "https://servicodados.ibge.gov.br/api/v3/agregados/1094/metadados"},
            {"url_valores": "https://apisidra.ibge.gov.br/values/t/1092/"},
            {"url_valores": "https://apisidra.ibge.gov.br/values/t/1092/n1/1?x=1"},
        ):
            with self.subTest(kw=kw), self.assertRaises(DadoInvalido):
                self.arquivar(**kw)

    def test_rejeita_json_indevido(self):
        for kw in (
            {"bruto_valores": b'{"results": []}'},
            {"bruto_valores": b'[1, 2]'},
            {"bruto_metadados": b"[]"},
            {"bruto_metadados": b"not-json"},
            {"bruto_valores": b'[]'},
        ):
            with self.subTest(kw=kw), self.assertRaises(DadoInvalido):
                self.arquivar(**kw)
        self.assertFalse(self.banco.exists())

    def test_rejeita_tempo_sem_fuso_e_retrogrado(self):
        for kw in (
            {"coleta_declarada": "2026-10-21T12:00:00"},
            {"publicacao_declarada": "2026-11-21T08:00:00Z"},
        ):
            with self.subTest(kw=kw), self.assertRaises(DadoInvalido):
                self.arquivar(**kw)

    def test_rejeita_limites_e_id_invalidos(self):
        with self.assertRaises(DadoInvalido):
            self.arquivar(max_valores_bytes=2)
        with self.assertRaises(DadoInvalido):
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=0)

    def test_nao_confunde_url_declarada_com_autenticidade(self):
        a = self.arquivar(bruto_metadados=b'{"id":"1092","mock":true}')
        self.assertFalse(a["dados_reais_verificados"])
        self.assertFalse(a["timestamps_autenticados"])



    def test_metadados_de_outro_agregado_rejeitados(self):
        with self.assertRaisesRegex(DadoInvalido, "ID coincidente"):
            self.arquivar(bruto_metadados=b'{"id":1093,"nome":"suino"}')
        with self.assertRaisesRegex(DadoInvalido, "ID coincidente"):
            self.arquivar(bruto_metadados=b'{"variaveis":[]}')
        self.assertFalse(self.banco.exists())


    def test_mesma_coleta_publicacao_divergente_falha_fechado(self):
        base = self.arquivar()
        with self.assertRaisesRegex(DadoInvalido, "captura conflitante"):
            self.arquivar(publicacao_declarada="2026-09-22T10:00:00-03:00")
        atual = recuperar_pacote_sidra_offline(banco=self.banco, id_captura=base["id"])
        self.assertEqual(atual["sha256_valores"], sha256(VAL).hexdigest())
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], 1)

    def test_mesma_coleta_conteudo_divergente_nao_cria_vintage(self):
        original = self.arquivar()
        with self.assertRaisesRegex(DadoInvalido, "captura conflitante"):
            self.arquivar(bruto_valores=json.dumps([
                {"NC": "Nivel", "V": "Valor", "D1C": "UF"},
                {"NC": "1", "V": "120", "D1C": "1"},
            ]).encode())
        with self.assertRaisesRegex(DadoInvalido, "captura conflitante"):
            self.arquivar(bruto_metadados=b'{"id":1092,"nome":"novo mock"}')
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], 1)
        self.assertEqual(
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=original["id"])["bruto_metadados"],
            META)

    def test_coleta_nova_publicacao_ou_conteudo_novo_preservados(self):
        a = self.arquivar()
        b = self.arquivar(
            coleta_declarada="2026-10-22T08:15:00-04:00",
            publicacao_declarada="2026-09-22T10:00:00-03:00",
            bruto_metadados=b'{"id":1092,"versao":"nova ficticia"}')
        self.assertNotEqual(a["id"], b["id"])
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                cx.execute("""INSERT INTO capturas_sidra(
                    especie,tabela_sidra,url_valores,url_metadados,
                    publicacao_declarada,coleta_declarada,sha256_valores,
                    sha256_metadados,bruto_valores,bruto_metadados,status
                ) SELECT especie,tabela_sidra,url_valores,url_metadados,
                  '2026-08-01T00:00:00+00:00',coleta_declarada,
                  sha256_valores,sha256_metadados,bruto_valores,
                  bruto_metadados,status FROM capturas_sidra WHERE id=1""")


    def test_schema_legado_nunca_migra_silenciosamente(self):
        with sqlite3.connect(self.banco) as cx:
            cx.execute("""CREATE TABLE capturas_sidra (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              especie TEXT, tabela_sidra TEXT,
              url_valores TEXT, url_metadados TEXT,
              publicacao_declarada TEXT, coleta_declarada TEXT,
              sha256_valores TEXT, sha256_metadados TEXT,
              bruto_valores BLOB, bruto_metadados BLOB, status TEXT,
              UNIQUE(especie,tabela_sidra,url_valores,url_metadados,
                     coleta_declarada,sha256_valores,sha256_metadados)
            )""")
        with self.assertRaisesRegex(DadoInvalido, "esquema SIDRA legado"):
            self.arquivar()
        with sqlite3.connect(self.banco) as cx:
            schema = cx.execute("SELECT sql FROM sqlite_master WHERE name='capturas_sidra'").fetchone()[0]
            self.assertIn("sha256_metadados)", schema)
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], 0)


    def test_leitura_inexistente_nao_cria_banco(self):
        self.assertFalse(self.banco.exists())
        with self.assertRaisesRegex(DadoInvalido, "inexistente"):
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=1)
        self.assertFalse(self.banco.exists())

    def test_leitura_nao_reconstroi_trigger_ausente(self):
        cap = self.arquivar()
        with sqlite3.connect(self.banco) as cx:
            cx.execute("DROP TRIGGER sidra_sem_update")
            versao_antes = cx.execute("PRAGMA schema_version").fetchone()[0]
        restaurado = recuperar_pacote_sidra_offline(
            banco=self.banco, id_captura=cap["id"])
        self.assertEqual(restaurado["sha256_valores"], sha256(VAL).hexdigest())
        with sqlite3.connect(self.banco) as cx:
            versao_depois = cx.execute("PRAGMA schema_version").fetchone()[0]
            triggers = {r[0] for r in cx.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertEqual(versao_antes, versao_depois)
        self.assertNotIn("sidra_sem_update", triggers)

    def test_leitura_banco_legado_nao_executa_ddl(self):
        with sqlite3.connect(self.banco) as cx:
            cx.execute("""CREATE TABLE capturas_sidra (
              id INTEGER PRIMARY KEY,
              especie TEXT, tabela_sidra TEXT,
              url_valores TEXT, url_metadados TEXT, coleta_declarada TEXT,
              sha256_valores TEXT, sha256_metadados TEXT,
              UNIQUE(especie, tabela_sidra, url_valores, url_metadados,
                     coleta_declarada, sha256_valores, sha256_metadados)
            )""")
            versao = cx.execute("PRAGMA schema_version").fetchone()[0]
        with self.assertRaisesRegex(DadoInvalido, "legado"):
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=1)
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("PRAGMA schema_version").fetchone()[0], versao)
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], 0)

    def test_leitura_id_ausente_nao_cria_ou_edita(self):
        self.arquivar()
        with sqlite3.connect(self.banco) as cx:
            antes = cx.execute("PRAGMA schema_version").fetchone()[0]
            n = cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0]
        with self.assertRaisesRegex(DadoInvalido, "nao encontrada"):
            recuperar_pacote_sidra_offline(banco=self.banco, id_captura=999)
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute("PRAGMA schema_version").fetchone()[0], antes)
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM capturas_sidra").fetchone()[0], n)

if __name__ == "__main__":
    unittest.main()
