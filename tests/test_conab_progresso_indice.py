import unittest

from nivon.conab_progresso_indice import (
    BASE, ErroIndiceConab, descobrir_indice, consolidar_paginas,
)

CAPTURA = "2026-10-20T18:00:00-03:00"


def entrada(inicio="12/10", fim="18/10/26", sufixo="primeiro",
            mod="19/10/2026 19h20"):
    return (
        f'<article><a href="{BASE}/acompanhamento-das-lavouras-{sufixo}">'
        f'Acompanhamento das Lavouras - {inicio} a {fim}</a>'
        f'<span>— última modificação {mod}</span></article>'
    )


class TestIndiceSemanalConab(unittest.TestCase):
    def test_descoberta_oficial_preserva_tempo_e_hash(self):
        x = descobrir_indice("<html>" + entrada() + "</html>", coletado_em=CAPTURA)
        self.assertEqual(x["capturado_em_utc"], "2026-10-20T21:00:00+00:00")
        self.assertEqual(x["registros"][0]["fim_semana"], "2026-10-18")
        self.assertEqual(x["registros"][0]["inicio_semana"], "2026-10-12")
        self.assertIn("última modificação", x["registros"][0]["ultima_modificacao_texto"])
        self.assertIsNone(x["registros"][0]["publicacao_utc"])
        self.assertFalse(x["registros"][0]["dados_agricolas_disponiveis"])
        self.assertEqual(len(x["indice_sha256"]), 64)

    def test_bolsa_24h_nao_pode_herdar_modificacao_como_publicacao(self):
        x = descobrir_indice(entrada(), coletado_em=CAPTURA)
        self.assertIsNone(x["registros"][0]["publicacao_utc"])

    def test_paginacao_historica_permitida(self):
        x = descobrir_indice(entrada(), coletado_em=CAPTURA,
                             url_indice=BASE + "?b_start:int=20")
        self.assertEqual(len(x["registros"]), 1)

    def test_paginacao_nao_autorizada_bloqueada(self):
        for url in (BASE + "?foo=20", BASE + "?b_start:int=-20",
                    BASE + "?b_start:int=25", BASE + "?b_start:int=99999",
                    "https://evil.example" + BASE[18:],
                    BASE + "?b_start:int=20&b_start:int=40"):
            with self.subTest(url=url), self.assertRaises(ErroIndiceConab):
                descobrir_indice(entrada(), coletado_em=CAPTURA, url_indice=url)

    def test_host_externo_de_boletim_rejeitado(self):
        html = entrada().replace(BASE + "/acompanhamento",
                                  "https://outro.invalid/acompanhamento")
        with self.assertRaises(ErroIndiceConab):
            descobrir_indice(html, coletado_em=CAPTURA)

    def test_nao_inventa_publicacao_se_metadado_ausente(self):
        x = descobrir_indice(entrada().replace(
            "— última modificação 19/10/2026 19h20", "sem hora oficial"),
            coletado_em=CAPTURA)
        self.assertIsNone(x["registros"][0]["ultima_modificacao_texto"])
        self.assertIsNone(x["registros"][0]["publicacao_utc"])

    def test_falha_se_html_nao_contem_registro(self):
        with self.assertRaises(ErroIndiceConab):
            descobrir_indice("<html>sem boletins</html>", coletado_em=CAPTURA)

    def test_rejeita_semana_invalida(self):
        for i, f in (("11/10", "18/10/26"), ("12/10", "17/10/26"),
                     ("35/10", "18/10/26")):
            with self.subTest(inicio=i, fim=f), self.assertRaises(
                    (ErroIndiceConab, ValueError)):
                descobrir_indice(entrada(i, f), coletado_em=CAPTURA)

    def test_virada_de_ano(self):
        x = descobrir_indice(entrada("28/12", "03/01/27"), coletado_em=CAPTURA)
        self.assertEqual(x["registros"][0]["inicio_semana"], "2026-12-28")
        self.assertEqual(x["registros"][0]["fim_semana"], "2027-01-03")

    def test_duplicata_identica_nao_conta_duas_vezes(self):
        x = descobrir_indice(entrada() + entrada(), coletado_em=CAPTURA)
        self.assertEqual(len(x["registros"]), 1)

    def test_duas_urls_na_mesma_semana_viram_conflito(self):
        with self.assertRaises(ErroIndiceConab):
            descobrir_indice(entrada() + entrada(sufixo="segundo"),
                             coletado_em=CAPTURA)

    def test_lacunas_nao_sao_interpoladas(self):
        page1 = entrada() + entrada("28/09", "04/10/26", sufixo="antigo")
        x = consolidar_paginas([{
            "html": page1, "url_indice": BASE, "coletado_em": CAPTURA,
        }])
        self.assertEqual(x["lacunas_na_sequencia"], ["2026-10-11"])
        self.assertFalse(x["coleta_real_dos_boletins"])
        self.assertFalse(x["publicacao_historica_comprovada"])

    def test_paginas_repetidas_bloqueadas(self):
        p = {"html": entrada(), "url_indice": BASE, "coletado_em": CAPTURA}
        with self.assertRaises(ErroIndiceConab):
            consolidar_paginas([p, p])

    def test_semana_conflitante_entre_paginas(self):
        pages = [
            {"html": entrada(), "url_indice": BASE, "coletado_em": CAPTURA},
            {"html": entrada(sufixo="outro"), "url_indice": BASE + "?b_start:int=20",
             "coletado_em": CAPTURA},
        ]
        with self.assertRaises(ErroIndiceConab):
            consolidar_paginas(pages)

    def test_nao_associa_modificacao_apos_link_nao_relacionado(self):
        html = (entrada().replace(
            "<span>— última modificação 19/10/2026 19h20</span>",
            '<a href="/outra-pagina">Outro recurso</a>'
            '<span>— última modificação 19/10/2026 19h20</span>'))
        item = descobrir_indice(html, coletado_em=CAPTURA)["registros"][0]
        self.assertIsNone(item["ultima_modificacao_texto"])

    def test_timestamps_sem_timezone_bloqueados(self):
        with self.assertRaises(ErroIndiceConab):
            descobrir_indice(entrada(), coletado_em="2026-10-20T12:00:00")

    def test_sem_rede_ou_dados_por_inferencia(self):
        x = consolidar_paginas([{
            "html": entrada(), "url_indice": BASE, "coletado_em": CAPTURA,
        }])
        self.assertEqual(x["boletins_identificados"], 1)
        self.assertIsNone(x["registros"][0]["publicacao_utc"])


if __name__ == "__main__":
    unittest.main()
