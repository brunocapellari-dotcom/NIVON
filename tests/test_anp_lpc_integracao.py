"""Integração ANP LPC com XLSX sintético: sem rede nem dado de posto."""
import io
import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256

from nivon.anp_lpc_pipeline import ErroIntegracaoLPC, integrar_lpc_semanal_offline
from nivon.anp_semanal_store import inicializar_store_anp, consultar_preco_semanal

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

HEADER = [
    "DATA INICIAL", "DATA FINAL", "ESTADO", "MUNICÍPIO",
    "PRODUTO", "NÚMERO DE POSTOS PESQUISADOS", "UNIDADE DE MEDIDA",
    "PREÇO MÉDIO REVENDA",
]


def fixture(start=date(2026, 10, 4), *,
            preco="5,90", estado="MATO GROSSO", periodo_xlsx=None,
            documento="MUNICIPIOS", produto="OLEO DIESEL S10"):
    end = start + timedelta(days=6)
    excel_start = periodo_xlsx if periodo_xlsx is not None else start
    excel_end = excel_start + timedelta(days=6)
    arquivo_url = (
        "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
        f"precos/arquivos-lpc/2026/resumo_semanal_lpc_{start}_{end}.xlsx"
    )
    wb = Workbook()
    w = wb.active
    w.title = documento
    for _ in range(6):
        w.append(["METADADOS SINTETICOS"])
    w.append(HEADER)
    w.append([excel_start, excel_end, estado, "SINOP",
              produto, 8, "R$/l", preco])
    w.append([excel_start, excel_end, estado, "SORRISO",
              "OLEO DIESEL", 7, "R$/l", 5.75])
    memoria = io.BytesIO()
    wb.save(memoria)
    wb.close()
    xlsx = memoria.getvalue()
    html = (
        "<html><body><h1>Indice ANP de fixture somente sintética</h1>"
        "<p>Levantamentos de revenda por semana, sem publicar valor real.</p>"
        f'<a href="{arquivo_url}/view">Resumo semanal municipal</a>'
        "</body></html>"
    ).encode()
    published = datetime(
        end.year, end.month, end.day, 12, tzinfo=timezone.utc
    ) + timedelta(days=2)
    index_capture = published + timedelta(hours=1)
    file_capture = index_capture + timedelta(minutes=15)
    return dict(
        html_indice=html, xlsx=xlsx, arquivo_url=arquivo_url, ano=2026,
        coletado_indice_em=index_capture.isoformat(),
        coletado_arquivo_em=file_capture.isoformat(),
        publicado_em=published.isoformat(),
        indice_sha256_esperado=sha256(html).hexdigest(),
        arquivo_sha256_esperado=sha256(xlsx).hexdigest(),
        prova_publicacao_sha256="e"*64,
    )


@unittest.skipIf(Workbook is None, "openpyxl opcional ausente")
class TestIntegracaoANPLPC(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        inicializar_store_anp(self.db)

    def tearDown(self):
        self.db.close()

    def executar(self, config=None, **changes):
        k = fixture() if config is None else config
        return integrar_lpc_semanal_offline(self.db, **{**k, **changes})

    def test_indice_xlsx_historico_semana_oficial(self):
        k = fixture()
        o = self.executar(k)
        self.assertEqual(o["status"], "LPC_SINTETICO_INTEGRADO_OFFLINE")
        self.assertEqual(o["semana_inicio_oficial"], "2026-10-04")
        self.assertEqual(o["semana_fim_oficial"], "2026-10-10")
        self.assertEqual(o["observacoes"], 2)
        self.assertTrue(o["indice_registrado"])
        self.assertEqual(o["indice_sha256"], sha256(k["html_indice"]).hexdigest())
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_indices").fetchone()[0], 1)
        self.assertEqual(o["arquivo_sha256"], sha256(k["xlsx"]).hexdigest())
        self.assertFalse(o["publicavel"])
        self.assertFalse(o["fonte_real_baixada"])
        self.assertFalse(o["semana_calendario_inferida"])
        self.assertEqual(o["classe_origem"], "FIXTURE_SINTETICA_SEM_HOMOLOGACAO")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_observacoes").fetchone()[0], 2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 1)
        self.assertEqual(consultar_preco_semanal(
            self.db, municipio="SINOP", uf="MT", produto="DIESEL S10",
            as_of="2026-10-15T12:00:00+00:00",
        )["status"], "SEM_EDICAO_REAL_ASOF")

    def test_tres_semanas_artificiais_distintas_sem_inferir_semana(self):
        weeks = [
            date(2026, 9, 20), date(2026, 9, 27), date(2026, 10, 4),
        ]
        receipts = [self.executar(fixture(start=d)) for d in weeks]
        self.assertEqual([x["semana_inicio_oficial"] for x in receipts],
                         [d.isoformat() for d in weeks])
        self.assertEqual(len({x["arquivo_sha256"] for x in receipts}), 3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_observacoes").fetchone()[0], 6)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_capturas").fetchone()[0], 3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_indices").fetchone()[0], 3)

    def test_reprocessamento_identico_nao_gera_dupla_captura(self):
        k = fixture()
        self.assertTrue(self.executar(k)["captura_nova"])
        segunda = self.executar(k)
        self.assertFalse(segunda["captura_nova"])
        self.assertFalse(segunda["indice_registrado"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_observacoes").fetchone()[0], 2)

    def test_mesmo_xlsx_novo_snapshot_indice_persiste_sem_duplicar_observacoes(self):
        k = fixture()
        self.executar(k)
        novo_html = k["html_indice"] + b" "
        novo = {**k, "html_indice": novo_html,
                "indice_sha256_esperado": sha256(novo_html).hexdigest()}
        saida = self.executar(novo)
        self.assertFalse(saida["captura_nova"])
        self.assertTrue(saida["indice_registrado"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_indices").fetchone()[0], 2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_observacoes").fetchone()[0], 2)

    def test_falha_no_indice_reverte_edicao_e_observacoes_atomicamente(self):
        self.db.executescript("""
            CREATE TRIGGER simular_falha_indice
            BEFORE INSERT ON anp_semanal_indices
            BEGIN SELECT RAISE(ABORT, 'falha sintética na gravação do índice'); END;
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.executar()
        for nome in ("anp_semanal_edicoes", "anp_semanal_indices",
                     "anp_semanal_capturas", "anp_semanal_observacoes"):
            self.assertEqual(self.db.execute(
                f"SELECT COUNT(*) FROM {nome}").fetchone()[0], 0)

    def test_semana_do_excel_deve_ser_a_mesma_do_link_indice(self):
        with self.assertRaisesRegex(ErroIntegracaoLPC, "período"):
            self.executar(fixture(periodo_xlsx=date(2026, 9, 27)))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_excel_com_aba_trocada_rejeitado(self):
        with self.assertRaisesRegex(ValueError, "MUNICIPIOS"):
            self.executar(fixture(documento="OUTRO"))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_sha_adulterado_bloqueia_antes_de_gravar(self):
        for key in ("indice_sha256_esperado", "arquivo_sha256_esperado"):
            with self.subTest(key=key), self.assertRaisesRegex(
                ErroIntegracaoLPC, "SHA"
            ):
                self.executar(**{key: "f"*64})
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_link_inventado_nao_pode_ser_persistido(self):
        with self.assertRaisesRegex(ErroIntegracaoLPC, "ausente"):
            self.executar(arquivo_url="https://www.gov.br/anp/falso.xlsx")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_vintage_no_futuro_ou_ordem_de_coleta_invertida(self):
        k = fixture()
        for change in (
            {"publicado_em": "2026-10-22T10:00:00+00:00"},
            {"coletado_indice_em": "2026-10-13T16:00:00+00:00"},
            {"coletado_arquivo_em": "2026-10-12T10:00:00+00:00"},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(
                ErroIntegracaoLPC, "cronologia"
            ):
                self.executar(k, **change)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_arquivo_html_waf_nao_e_indice(self):
        html = b"<html><body>Request Rejected</body></html>" * 5
        with self.assertRaises(ValueError):
            self.executar(
                html_indice=html,
                indice_sha256_esperado=sha256(html).hexdigest(),
            )
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_contrato_sintetico_nao_promove_direitos_reais(self):
        with self.assertRaisesRegex(PermissionError, "bloqueada"):
            self.executar(classe="REAL_AUTORIZADO")
        with self.assertRaisesRegex(PermissionError, "bloqueada"):
            self.executar(classe="REAL")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_s10_e_comum_nao_viram_unico_preco(self):
        self.executar()
        l = self.db.execute(
            "SELECT produto, preco_medio, postos "
            "FROM anp_semanal_observacoes ORDER BY produto"
        ).fetchall()
        self.assertEqual([x[0] for x in l], ["DIESEL", "DIESEL S10"])
        self.assertNotEqual(l[0][1], l[1][1])

    def test_ausencia_municipio_nao_inventa_preco_zero(self):
        with self.assertRaisesRegex(ValueError, "zero"):
            self.executar(municipios_mt=frozenset({"LUCAS DO RIO VERDE"}))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
