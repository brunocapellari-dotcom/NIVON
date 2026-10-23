"""Prova de interoperabilidade: leitura ferroviaria, saude AIS e fila prevista."""
from __future__ import annotations
import unittest

from nivon.maritimo_painel_avancado import avaliar_porto_avancado
from nivon.painel_operacional import ErroMotor, montar_painel, pressao_portuaria
from nivon.ponte_painel_fontes import analisar_fontes
from test_painel_operacional import AS_OF, porto


def porto_com_telemetria(**kwargs):
    return porto(**({
        "saude_coletor": {
            "intervalo_esperado_minutos": 60,
            "ultimo_sucesso_em": "2026-10-23T11:45:00Z",
            "ultimo_registro_em": "2026-10-23T11:50:00Z",
        },
        "horas_espera_observadas": [2, 4, 8],
        "taxas_atendimento_observadas_h": [0.15 + (i % 3) * 0.01 for i in range(60)],
        "chegadas_acumuladas_previstas": {"6": 2, "24": 5, "48": 9},
    } | kwargs))


def rodo():
    return {
        "estado": "RECORTE_IMPORTADO_NAO_HOMOLOGADO",
        "recorte": "mt_2026", "competencia": "2026-09",
        "resumo_polos": [{"polo": {"id": "MT_RONDONOPOLIS_FERRO",
                    "modal_destino": "FERROVIARIO"},
                    "sentido": "DESTINO", "toneladas_no_recorte": "120",
                    "principais_origens": [{"origem": "Sorriso",
                                             "toneladas_no_recorte": "120"}]}]
    }


def ferro():
    return {
        "competencia": "2026-09", "qualidade": "TU_DECLARADA_FONTE_PRIMARIA_REQUER_CONCILIACAO",
        "polos_ferroviarios": [{
            "polo": {"id": "MT_RONDONOPOLIS_FERRO"},
            "toneladas_ferroviarias": "90",
            "mercadorias": [{"mercadoria_fonte": "SOJA",
                             "toneladas_ferroviarias": "90"}]
        }]
    }


class IntegracaoAvancadaTests(unittest.TestCase):
    def test_ais_saude_validada_usa_vqi_herdado_e_projecoes_shadow(self):
        s = porto_com_telemetria()
        anterior = pressao_portuaria(s, as_of=AS_OF)
        extra = avaliar_porto_avancado(s, as_of=AS_OF, pressao=anterior)
        self.assertEqual(extra["status"], "SHADOW_READY")
        self.assertEqual(extra["status_saude_fonte"], "FRESH")
        self.assertEqual(extra["vqi"]["status"], "SHADOW_READY")
        self.assertEqual(extra["vqi"]["publication_mode"], "SHADOW")
        self.assertEqual(extra["fila_6_24_48h"]["status"], "SHADOW_READY")
        self.assertEqual([p["horizon_hours"] for p in extra["fila_6_24_48h"]["points"]],
                         [6, 24, 48])
        self.assertFalse(extra["publicavel"])
        self.assertFalse(extra["regras"]["lineup_entrou_no_score"])
        self.assertFalse(extra["regras"]["previsao_calibrada"])
        painel = montar_painel({"portos": [s]}, as_of=AS_OF)
        self.assertEqual(painel["maritimo"][0]["indice_pressao"], anterior["indice_pressao"])
        self.assertEqual(painel["maritimo"][0]["avancado"]["status"], "SHADOW_READY")

    def test_lineup_cdp_nao_muda_vqi_nem_forecast(self):
        a = porto_com_telemetria(lineup_72h=5, lineup_validado=False)
        b = porto_com_telemetria(lineup_72h=100, lineup_validado=False)
        ea = avaliar_porto_avancado(a, as_of=AS_OF,
                                   pressao=pressao_portuaria(a, as_of=AS_OF))
        eb = avaliar_porto_avancado(b, as_of=AS_OF,
                                   pressao=pressao_portuaria(b, as_of=AS_OF))
        self.assertEqual(ea["vqi"], eb["vqi"])
        self.assertEqual(ea["fila_6_24_48h"], eb["fila_6_24_48h"])

    def test_ausencia_telemetria_ou_taxas_bloqueia_estimativa(self):
        sem_saude = porto_com_telemetria(saude_coletor=None)
        x = avaliar_porto_avancado(sem_saude, as_of=AS_OF,
                                  pressao=pressao_portuaria(sem_saude, as_of=AS_OF))
        self.assertIsNone(x["vqi"]["vqi"])
        self.assertTrue(all(v["waiting_expected"] is None for v in x["fila_6_24_48h"]["points"]))
        sem_chegadas = porto_com_telemetria(chegadas_acumuladas_previstas=None)
        y = avaliar_porto_avancado(sem_chegadas, as_of=AS_OF,
                                  pressao=pressao_portuaria(sem_chegadas, as_of=AS_OF))
        self.assertEqual(y["fila_6_24_48h"]["status"], "DATA_GATED")

    def test_amostras_malformadas_nao_publicam(self):
        for invalidos in (
            {"taxas_atendimento_observadas_h": [float("nan")]},
            {"taxas_atendimento_observadas_h": [-0.1] * 30},
            {"chegadas_acumuladas_previstas": {"6": 5, "24": 2, "48": 10}},
            {"saude_coletor": {
                "intervalo_esperado_minutos": 60,
                "ultimo_sucesso_em": "2026-10-24T00:00:00Z",
            }},
        ):
            with self.subTest(invalidos=invalidos), self.assertRaises(ErroMotor):
                s = porto_com_telemetria(**invalidos)
                avaliar_porto_avancado(s, as_of=AS_OF,
                                      pressao=pressao_portuaria(s, as_of=AS_OF))

    def test_estacoes_ferroviarias_e_rodoviarias_sem_soma(self):
        result = analisar_fontes({"corredores": rodo(), "ferrovia": ferro()}, as_of=AS_OF)
        self.assertEqual(result["conciliacao_intermodal"]["estado"],
                         "COMPARACAO_EXPLORATORIA_NAO_BALANCO")
        p = result["conciliacao_intermodal"]["dados"][0]
        self.assertEqual(p["toneladas_rodoviarias_destino_geografico"], "120")
        self.assertEqual(p["toneladas_ferroviarias_estacao_origem"], "90")
        self.assertFalse(p["soma_entre_modais_permitida"])
        self.assertFalse(p["transbordo_confirmado"])
        self.assertNotIn("toneladas_intermodal_total", result)

    def test_staging_existente_consultado_sem_download(self):
        chamados = []
        def ler(pasta, **kw):
            chamados.append((pasta, kw))
            return ferro()
        config = {"corredores": rodo(),
                  "ferrovia_staging": {"pasta": "stage/privado", "ano": 2026,
                                      "competencia": "2026-09"}}
        resp = analisar_fontes(config, as_of=AS_OF, leitor_ferrovia=ler)
        self.assertEqual(resp["conciliacao_intermodal"]["dados"][0]
                         ["toneladas_ferroviarias_estacao_origem"], "90")
        self.assertEqual(chamados[0][1]["ano"], 2026)
        self.assertEqual(chamados[0][1]["limite"], 1000)
        self.assertEqual(chamados[0][1]["uf_origem"], "MT")

    def test_incompatibilidade_periodo_bloqueia_comparacao(self):
        diverso = ferro() | {"competencia": "2026-08"}
        with self.assertRaises(ValueError):
            analisar_fontes({"corredores": rodo(), "ferrovia": diverso}, as_of=AS_OF)
        orfao = analisar_fontes({"ferrovia": ferro()}, as_of=AS_OF)
        self.assertEqual(orfao["conciliacao_intermodal"]["estado"], "DADOS_INSUFICIENTES")


if __name__ == "__main__":
    unittest.main()
