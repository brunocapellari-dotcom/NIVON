"""Três XLSX inteiramente sintéticos, sem baixar dados ANP reais."""
import unittest
from datetime import date
from hashlib import sha256

from nivon.anp_lpc_homologacao import auditar_tres_edicoes_lpc, ErroHomologacaoLPC

from test_anp_lpc_integracao import fixture, Workbook


def lote():
    start = (date(2026, 9, 27), date(2026, 10, 4), date(2026, 10, 11))
    fontes = [fixture(start=d) for d in start]
    html = ("<html><body><h1>Snapshot fictício para teste de fontes</h1>" +
            "".join('<a href="' + f["arquivo_url"] + '/view">Resumo semanal</a>'
                    for f in fontes) + "</body></html>").encode()
    edicoes = [
        {
            "url": f["arquivo_url"], "xlsx": f["xlsx"],
            "sha256": f["arquivo_sha256_esperado"],
            "publicado_em": f["publicado_em"],
            "coletado_em": "2026-10-20T14:00:00+00:00",
            "prova_publicacao_sha256": "e"*64,
        }
        for f in fontes
    ]
    return {
        "indice_html": html,
        "indice_sha256_esperado": sha256(html).hexdigest(),
        "capturado_indice_em": "2026-10-20T13:00:00+00:00",
        "edicoes": edicoes, "ano": 2026,
        "as_of": "2026-10-20T15:00:00+00:00",
    }


@unittest.skipIf(Workbook is None, "leitor XLSX opcional ausente")
class TestPreHomologacaoANP(unittest.TestCase):
    def executar(self, source=None, **changes):
        return auditar_tres_edicoes_lpc(**{**(source or lote()), **changes})

    def test_tres_semanas_distintas_sem_promover_para_real(self):
        r = self.executar()
        self.assertEqual(r["numero_edicoes"], 3)
        self.assertEqual(r["semana_inicial"], "2026-09-27")
        self.assertEqual(r["semana_final"], "2026-10-17")
        self.assertTrue(r["semana_oficial"])
        self.assertFalse(r["semana_inferida_csv_mensal"])
        self.assertFalse(r["layout_real_homologado"])
        self.assertFalse(r["datas_publicacao_independentemente_comprovadas"])
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["dados_reais_persistidos"])
        self.assertEqual(r["lacunas_cobertura"], [])
        self.assertNotIn("5.75", str(r))
        self.assertNotIn("5.9", str(r))
        self.assertEqual(len(r["edicoes"]), 3)
        self.assertTrue(all(x["registros_municipio_produto"] == 2
                            for x in r["edicoes"]))

    def test_erro_se_apenas_duas_ou_quatro_edicoes(self):
        for count in (0, 2, 4):
            with self.subTest(count=count), self.assertRaisesRegex(
                    ErroHomologacaoLPC, "exatamente três"):
                self.executar(edicoes=(lote()["edicoes"]*2)[:count])

    def test_nao_considerar_periodos_saltados_tres_semanas_validas(self):
        f = fixture(start=date(2026, 9, 20))
        src = lote()
        old = src["edicoes"][0]
        src["edicoes"][0] = {
            **old, "url": f["arquivo_url"],
            "xlsx": f["xlsx"], "sha256": sha256(f["xlsx"]).hexdigest(),
            "publicado_em": f["publicado_em"],
        }
        html = src["indice_html"].decode() + (
            '<a href="' + f["arquivo_url"] + '/view">Histórico</a>')
        src["indice_html"] = html.encode()
        src["indice_sha256_esperado"] = sha256(src["indice_html"]).hexdigest()
        with self.assertRaisesRegex(ErroHomologacaoLPC, "consecutivas"):
            self.executar(src)

    def test_regra_de_indice_e_hashes_de_lote(self):
        r = lote()
        with self.assertRaisesRegex(ErroHomologacaoLPC, "SHA do índice"):
            self.executar(r, indice_sha256_esperado="0"*64)
        r = lote()
        r["edicoes"][0]["sha256"] = "1"*64
        with self.assertRaisesRegex(ErroHomologacaoLPC, "SHA divergente"):
            self.executar(r)
        r = lote()
        r["edicoes"][0]["url"] = "https://fake.example/semana.xlsx"
        with self.assertRaisesRegex(ErroHomologacaoLPC, "não listado"):
            self.executar(r)

    def test_corte_point_in_time_bloqueia_datas_futuras(self):
        r = lote()
        with self.assertRaisesRegex(ErroHomologacaoLPC, "corte as_of"):
            self.executar(r, as_of="2026-10-19T10:00:00+00:00")
        with self.assertRaisesRegex(ErroHomologacaoLPC, "cronologicamente"):
            self.executar(r, as_of="2026-10-20T13:15:00+00:00")

    def test_inconsistencia_de_data_publicacao_declarada(self):
        r = lote()
        r["edicoes"][1]["publicado_em"] = "2026-10-22T09:00:00+00:00"
        with self.assertRaisesRegex(ErroHomologacaoLPC, "cronologicamente"):
            self.executar(r)

    def test_reutilizacao_mesmos_bytes_como_outra_semana_bloqueia(self):
        r = lote()
        r["edicoes"][1]["xlsx"] = r["edicoes"][0]["xlsx"]
        r["edicoes"][1]["sha256"] = r["edicoes"][0]["sha256"]
        with self.assertRaisesRegex(ErroHomologacaoLPC, "reapresentado"):
            self.executar(r)

    def test_status_de_lacuna_municipal_nao_inventa_zero(self):
        # Segunda edição: SINOP muda produto observado; não inferir que
        # DIESEL S10 esteve cotado onde não há amostra para aquela semana.
        f = fixture(start=date(2026, 10, 4), produto="OLEO DIESEL")
        r = lote()
        r["edicoes"][1]["xlsx"] = f["xlsx"]
        r["edicoes"][1]["sha256"] = sha256(f["xlsx"]).hexdigest()
        out = self.executar(r)
        self.assertTrue(out["lacunas_cobertura"])
        self.assertEqual(out["lacunas_cobertura"][0]["municipio"], "SINOP")
        self.assertFalse(out["publicavel"])

    def test_rejeita_semana_xlsx_diferente_de_url(self):
        f = fixture(start=date(2026, 10, 11),
                    periodo_xlsx=date(2026, 10, 4), preco="6,11")
        r = lote()
        r["edicoes"][2]["xlsx"] = f["xlsx"]
        r["edicoes"][2]["sha256"] = sha256(f["xlsx"]).hexdigest()
        with self.assertRaisesRegex(ErroHomologacaoLPC, "difere do índice"):
            self.executar(r)


if __name__ == "__main__":
    unittest.main()
