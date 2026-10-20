import copy
import unittest

from nivon.conab_progresso_indice import BASE, ErroIndiceConab, consolidar_paginas
from nivon.conab_progresso_delta import planejar_delta


def link(inicio="05/10", fim="11/10/26", path="semanal-a",
         hora="12/10/2026 19h04"):
    return (f'<a href="{BASE}/{path}">'
            f'Acompanhamento das Lavouras - {inicio} a {fim}</a>'
            f' — última modificação {hora}')


def captura(html, data="2026-10-19T23:00:00Z", pagina=BASE):
    return consolidar_paginas([{
        "html": f"<html>{html}</html>",
        "url_indice": pagina,
        "coletado_em": data,
    }])


class TestDeltaConab(unittest.TestCase):
    def setUp(self):
        self.old = captura(link())
        self.new = captura(link(), data="2026-10-20T23:00:00Z")

    def test_primeira_captura_sinaliza_link_novo_sem_permissao(self):
        r = planejar_delta(None, self.new)
        self.assertEqual(r["por_situacao"], {"NOVO_LINK": 1})
        self.assertFalse(r["autorizacao_execucao"])
        self.assertEqual(r["dados_de_progresso_coletados"], 0)
        self.assertTrue(r["itens"][0]["candidato_verificacao_manual"])
        self.assertFalse(r["itens"][0]["direito_de_coleta_verificado"])

    def test_mesmo_link_e_metadado_nao_atestam_bytes_identicos(self):
        r = planejar_delta(self.old, self.new)
        self.assertEqual(r["por_situacao"], {"SEM_ALTERACAO_VISIVEL": 1})
        self.assertFalse(r["itens"][0]["arquivo_original_verificado"])
        self.assertFalse(r["itens"][0]["candidato_verificacao_manual"])
        self.assertFalse(r["remocao_de_boletins_comprovada"])

    def test_detecta_semana_nova(self):
        new = captura(link() + link("12/10", "18/10/26", path="b",
                                   hora="19/10/2026 19h20"),
                      data="2026-10-20T23:00:00Z")
        r = planejar_delta(self.old, new)
        self.assertEqual(r["por_situacao"]["NOVO_LINK"], 1)
        self.assertEqual(r["por_situacao"]["SEM_ALTERACAO_VISIVEL"], 1)

    def test_detecta_url_revisada_sem_chamar_dado_revisado(self):
        new = captura(link(path="c"), data="2026-10-20T23:00:00Z")
        r = planejar_delta(self.old, new)
        self.assertEqual(r["por_situacao"], {"URL_ALTERADA": 1})
        self.assertEqual(r["itens"][0]["url_anterior"], BASE + "/semanal-a")
        self.assertEqual(r["itens"][0]["url_atual"], BASE + "/c")
        self.assertEqual(r["dados_de_progresso_coletados"], 0)

    def test_detecta_texto_de_modificacao_alterado(self):
        new = captura(link(hora="20/10/2026 20h30"),
                      data="2026-10-20T23:00:00Z")
        self.assertEqual(planejar_delta(self.old, new)["por_situacao"],
                         {"METADADO_ALTERADO": 1})

    def test_ausencia_na_amostra_nao_e_remocao(self):
        old = captura(link() + link("12/10", "18/10/26", "b",
                                    "19/10/2026 19h20"))
        new = captura(link(), data="2026-10-20T23:00:00Z")
        r = planejar_delta(old, new)
        self.assertEqual(r["por_situacao"]["NAO_VISIVEL_NA_AMOSTRA_ATUAL"], 1)
        self.assertFalse(r["remocao_de_boletins_comprovada"])
        ausente = [x for x in r["itens"] if x["situacao"] ==
                   "NAO_VISIVEL_NA_AMOSTRA_ATUAL"][0]
        self.assertIsNone(ausente["url_atual"])
        self.assertFalse(ausente["candidato_verificacao_manual"])

    def test_indice_html_mutado_sem_delta_identificavel(self):
        novo = captura(link() + "<p>texto do portal atualizado</p>",
                       data="2026-10-20T23:00:00Z")
        self.assertTrue(planejar_delta(self.old, novo)["indice_alterado_sem_delta_visivel"])

    def test_indice_exatamente_igual_sem_aviso_indevido(self):
        self.assertFalse(planejar_delta(self.old, self.new)["indice_alterado_sem_delta_visivel"])

    def test_sem_retrocesso_cronologico(self):
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.new, self.old)

    def test_captura_simultanea_divergente(self):
        igual = captura(link(path="distinto"))
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, igual)

    def test_captura_simultanea_identica_idempotente(self):
        self.assertEqual(planejar_delta(self.old, self.old)["por_situacao"],
                         {"SEM_ALTERACAO_VISIVEL": 1})

    def test_nao_aceita_manifesto_que_afirma_publicacao(self):
        falso = copy.deepcopy(self.new)
        falso["registros"][0]["publicacao_utc"] = "2026-10-12T19:04:00Z"
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)

    def test_nao_aceita_dados_reais_simulados_no_indice(self):
        falso = copy.deepcopy(self.new)
        falso["registros"][0]["dados_agricolas_disponiveis"] = True
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)

    def test_nao_aceita_captura_sem_hash_valido(self):
        falso = copy.deepcopy(self.new)
        falso["paginas_capturadas"][0]["indice_sha256"] = "a" * 63
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)

    def test_nao_aceita_url_boletim_externa(self):
        falso = copy.deepcopy(self.new)
        falso["registros"][0]["url_boletim"] = "https://evil.invalid/file.pdf"
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)

    def test_nao_aceita_lacunas_substituidas_por_zero(self):
        falso = copy.deepcopy(self.new)
        falso["lacunas_na_sequencia"] = ["2026-10-04"]
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)

    def test_nao_aceita_boletins_duplicados(self):
        falso = copy.deepcopy(self.new)
        falso["registros"].append(copy.deepcopy(falso["registros"][0]))
        falso["boletins_identificados"] += 1
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)

    def test_nao_aceita_datas_captura_intercaladas(self):
        passado = captura(link(), "2026-10-19T21:00:00Z")
        atual = consolidar_paginas([
            {"html": link(), "url_indice": BASE, "coletado_em": "2026-10-19T19:00:00Z"},
            {"html": link("12/10", "18/10/26", "b", "19/10/2026 19h20"),
             "url_indice": BASE + "?b_start:int=20",
             "coletado_em": "2026-10-19T23:00:00Z"},
        ])
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(passado, atual)

    def test_rejeita_identidade_de_dataset_maliciosa(self):
        falso = copy.deepcopy(self.new)
        falso["dataset_id"] = "OUTRO"
        with self.assertRaises(ErroIndiceConab):
            planejar_delta(self.old, falso)


if __name__ == "__main__":
    unittest.main()
