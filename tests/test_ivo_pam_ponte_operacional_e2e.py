"""Integração real de módulos: SQLite operacional -> bytes/recibos -> revisão.

Todos os valores são fixtures; testes não usam rede ou banco canônico.
"""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.ivo_pam_operacao import abrir_operacao_pam, processar_captura_pam
from nivon.ivo_pam_ponte_operacional import (
    ErroPonteOperacionalPAM, main, revisar_capturas_pam,
)
from nivon.sidra_pam import planejar_pam_1612

T = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)


def plano(m="5107958", ano=2021, categoria="2713", variavel="214"):
    return planejar_pam_1612(
        municipio_ibge=m, ano=ano, codigo_produto_c81=categoria,
        codigo_variavel=variavel,
    )


def bytes_sidra(plan, value="200"):
    return json.dumps([
        {"D1C": "Município (Código)", "D2C": "Variável (Código)",
         "D3C": "Ano (Código)",
         "D4C": "Produto das lavouras temporárias (Código)",
         "V": "Valor", "MN": "Unidade de Medida"},
        {"D1C": plan["municipio_ibge"], "D2C": plan["variavel"],
         "D3C": str(plan["ano"]), "D4C": plan["categoria_c81"],
         "V": value,
         "MN": "Toneladas" if plan["variavel"] == "214" else "Hectares"},
    ], ensure_ascii=False).encode("utf-8")


class TestPonteOperacionalPAM(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cofre = self.root / "cofre"
        self.dbfile = self.root / "operacional.sqlite"
        self.db = abrir_operacao_pam(self.dbfile)
        self.addCleanup(self.db.close)
        self.p1 = plano()
        self.p2 = plano("5105259", 2024)

    def insert(self, p=None, value="200", date=T, source="TRANSPORTE_TESTE"):
        p = p or self.p1
        return processar_captura_pam(
            db=self.db, raiz=self.cofre, plano=p,
            payload=bytes_sidra(p, value),
            coletado_em=date, origem=source,
        )

    def test_multiplas_capturas_produzem_fila_por_vintage(self):
        self.insert()
        self.insert(self.p2, "700", source="ARQUIVO_LOCAL")
        r = revisar_capturas_pam(db=self.db, raiz=self.cofre)
        self.assertEqual(r["capturas_consideradas"], 2)
        self.assertEqual(r["versoes_sqlite_auditadas"], 2)
        self.assertEqual(r["mudancas_observadas"], 0)
        self.assertEqual(len(r["itens"]), 2)
        self.assertTrue(all(x["estado"] ==
            "CAPTURA_OPERACIONAL_REVISADA_SEM_HOMOLOGACAO" for x in r["itens"]))
        self.assertTrue(all(not x["liberado_para_promocao"] for x in r["itens"]))
        self.assertFalse(r["dados_reais_homologados"])
        self.assertFalse(r["permissao_publicacao_concedida"])
        self.assertNotIn("valor_candidato", str(r))
        self.assertEqual(len(r["manifesto_sha256"]), 64)

    def test_alteracao_de_valor_representa_captura_nao_data_de_publicacao(self):
        self.insert()
        self.insert(value="280", date=T + timedelta(hours=1))
        result = revisar_capturas_pam(db=self.db, raiz=self.cofre)
        self.assertEqual(result["capturas_consideradas"], 2)
        self.assertEqual(result["mudancas_observadas"], 1)
        self.assertEqual(result["itens"][-1]["mudanca_operacional"], "VALOR_ALTERADO")
        self.assertFalse(result["publicacao_oficial_comprovada"])
        self.assertEqual(
            {x["sha256_original"] for x in result["itens"]}.__len__(), 2
        )

    def test_cutoff_historico_nao_vaza_captura_posterior(self):
        self.insert()
        self.insert(value="280", date=T + timedelta(hours=1))
        before = revisar_capturas_pam(
            db=self.db, raiz=self.cofre, corte_coleta=T + timedelta(minutes=5))
        after = revisar_capturas_pam(
            db=self.db, raiz=self.cofre, corte_coleta=T + timedelta(hours=2))
        self.assertEqual(before["capturas_consideradas"], 1)
        self.assertEqual(before["mudancas_observadas"], 0)
        self.assertEqual(after["capturas_consideradas"], 2)
        self.assertEqual(after["mudancas_observadas"], 1)
        self.assertNotIn(after["itens"][-1]["sha256_original"], str(before))

    def test_recoleta_idempotente_preserva_um_sha_duas_capturas(self):
        self.insert()
        self.insert(date=T + timedelta(minutes=2))
        result = revisar_capturas_pam(db=self.db, raiz=self.cofre)
        self.assertEqual(result["capturas_consideradas"], 2)
        self.assertEqual(result["versoes_sqlite_auditadas"], 1)
        self.assertEqual(result["itens"][1]["mudanca_operacional"], "SEM_ALTERACAO")
        self.assertEqual(result["itens"][0]["recibo_sha256"],
                         result["itens"][1]["recibo_sha256"])

    def test_corromper_valor_no_sqlite_impede_fila(self):
        self.insert()
        self.db.execute("UPDATE pam_vintages SET valor=999")
        self.db.commit()
        with self.assertRaises(ErroPonteOperacionalPAM):
            revisar_capturas_pam(db=self.db, raiz=self.cofre)

    def test_corromper_bytes_impede_fila(self):
        record = self.insert()
        object_file = self.cofre / "objetos_sha256" / (record["sha256"] + ".bin")
        object_file.write_bytes(b"alterado")
        with self.assertRaises(ErroPonteOperacionalPAM):
            revisar_capturas_pam(db=self.db, raiz=self.cofre)

    def test_corte_timezone_invalido_falha_fechado(self):
        self.insert()
        with self.assertRaises(ErroPonteOperacionalPAM):
            revisar_capturas_pam(
                db=self.db, raiz=self.cofre,
                corte_coleta=T.replace(tzinfo=None),
            )

    def test_limite_de_capturas_excede_capacidade_sem_resultado_parcial(self):
        self.insert()
        self.insert(self.p2)
        with self.assertRaises(ErroPonteOperacionalPAM):
            revisar_capturas_pam(db=self.db, raiz=self.cofre, max_capturas=1)

    def test_vazio_nao_inventa_capturas(self):
        result = revisar_capturas_pam(db=self.db, raiz=self.cofre)
        self.assertEqual(result["capturas_consideradas"], 0)
        self.assertEqual(result["itens"], [])
        self.assertFalse(result["dados_reais_homologados"])

    def test_cli_usa_sqlite_readonly_e_nao_sobrescreve_relatorio(self):
        self.insert()
        self.db.commit()
        out = self.root / "revisao.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--db", str(self.dbfile),
                "--acervo", str(self.cofre),
                "--saida", str(out),
            ]), 0)
        self.assertEqual(json.loads(out.read_text())["capturas_consideradas"], 1)
        self.assertEqual(out.read_text().count("liberado_para_promocao"), 1)
        prev = out.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--db", str(self.dbfile),
                "--acervo", str(self.cofre),
                "--saida", str(out),
            ]), 0)
        self.assertEqual(prev, out.read_bytes())
        out.write_text("tampered")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--db", str(self.dbfile),
                "--acervo", str(self.cofre),
                "--saida", str(out),
            ]), 2)

    def test_cli_banco_ausente_nao_cria_banco_falso(self):
        phantom = self.root / "inexistente.db"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--db", str(phantom),
                "--acervo", str(self.cofre),
                "--saida", str(self.root / "fila.json"),
            ]), 2)
        self.assertFalse(phantom.exists())


if __name__ == "__main__":
    unittest.main()
