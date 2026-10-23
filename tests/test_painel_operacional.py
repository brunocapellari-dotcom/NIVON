"""Testes ponta-a-ponta offline: fontes e numericos sao todos sinteticos."""
from __future__ import annotations

import unittest

from nivon.painel_operacional import (
    ErroMotor, montar_painel, pressao_portuaria, resumo_logistico, tendencia_precos,
)


AS_OF = "2026-10-23T12:00:00Z"


def preco(dia, valor, **alteracoes):
    obj = {
        "identidade": "oferta-" + str(dia),
        "data_referencia": f"2026-10-{dia:02d}",
        "data_publicacao": f"2026-10-{dia:02d}T09:00:00Z",
        "data_coleta": f"2026-10-{dia:02d}T10:00:00Z",
        "valor": str(valor),
        "unidade": "R$/t",
        "natureza": "INFORMADO",
        "campos": {
            "serie_id": "RONDONOPOLIS_SANTOS_SOJA_A",
            "classe": "FRETE_ANUNCIADO", "produto": "SOJA",
            "origem": "RONDONOPOLIS", "destino": "SANTOS",
            "transportadora": "OPERADOR_A", "equipamento": "GRANELEIRO",
            "regime": "PJ", "modal": "RODOVIARIO", "terminal": "TERMINAL_X",
            "contrato": None,
        },
    }
    for k, v in alteracoes.items():
        if k in obj["campos"]:
            obj["campos"][k] = v
        else:
            obj[k] = v
    return obj


def seis_precos():
    return [preco(10, 100), preco(11, 100), preco(12, 100),
            preco(17, 105), preco(18, 110), preco(20, 110)]


def porto(**changes):
    s = {
        "porto_id": "SANTOS",
        "data_referencia": "2026-10-23T10:00:00Z",
        "fonte_ais": "AISSTREAM_PILOTO",
        "navios_aguardando": 3, "navios_aproximando": 2, "navios_atracados": 1,
        "historico_navios_aguardando": [1] * 15 + [4] * 15,
        "geocercas_validadas": True, "mmsi_unicos": True,
        "conciliacao_ais_operacao": "0.96",
        "lineup_validado": False, "lineup_72h": 16,
    }
    return s | changes


class PainelOperacionalTests(unittest.TestCase):
    def test_tendencia_alta_sombra_e_serie_mesma_condicao(self):
        r = tendencia_precos(seis_precos(), classe="FRETE_ANUNCIADO",
                             serie_id="RONDONOPOLIS_SANTOS_SOJA_A", as_of=AS_OF)
        self.assertEqual(r["status"], "SHADOW_READY")
        self.assertFalse(r["publicavel"])
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["dias_validos"], 6)
        self.assertEqual(r["unidade"], "R$/t")

    def test_frete_maximo_no_dia_sem_dizer_que_foi_negociado(self):
        linhas = seis_precos() + [preco(20, 130, identidade="nova-divulgacao")]
        r = tendencia_precos(linhas, classe="FRETE_ANUNCIADO",
                             serie_id="RONDONOPOLIS_SANTOS_SOJA_A", as_of=AS_OF)
        self.assertGreater(float(r["variacao_pct"]), 0)
        self.assertEqual(r["regra_intradia"], "MAIOR_ANUNCIO_MESMAS_CONDICOES")
        self.assertEqual(r["natureza_resultado"], "INFERIDO")

    def test_sem_vazamento_de_revisoes_futuras(self):
        linhas = seis_precos() + [
            preco(10, 10000, data_coleta="2026-10-24T10:00:00Z"),
            preco(12, 9999, identidade="futura", data_publicacao="2026-10-24T09:00:00Z"),
        ]
        r = tendencia_precos(linhas, classe="FRETE_ANUNCIADO",
                             serie_id="RONDONOPOLIS_SANTOS_SOJA_A", as_of=AS_OF)
        self.assertEqual(r["dias_validos"], 6)
        self.assertEqual(r["registros_excluidos"], 2)
        self.assertLess(float(r["variacao_pct"]), 15)

    def test_frete_outra_transportadora_e_unidade_recusadas(self):
        for mudanca in ({"transportadora": "OPERADOR_B"}, {"unidade": "USD/bu"},
                        {"regime": "PF"}, {"terminal": "OUTRO"}):
            with self.subTest(diferenca=mudanca), self.assertRaises(ErroMotor):
                tendencia_precos(seis_precos() + [preco(21, 200, **mudanca)],
                                 classe="FRETE_ANUNCIADO",
                                 serie_id="RONDONOPOLIS_SANTOS_SOJA_A", as_of=AS_OF)

    def test_ausencia_nao_vira_zero_e_estimativa_nao_viram_fatos(self):
        linhas = seis_precos()
        linhas[0] = preco(10, 0, natureza="ESTIMADO")
        linhas[1] = preco(11, 100, data_publicacao=None)
        r = tendencia_precos(linhas, classe="FRETE_ANUNCIADO",
                             serie_id="RONDONOPOLIS_SANTOS_SOJA_A", as_of=AS_OF)
        self.assertEqual(r["status"], "DADOS_INSUFICIENTES")
        self.assertEqual(r["dias_validos"], 4)

    def test_nao_comparar_contratos_cbot(self):
        rows = [preco(d, 100 + d, classe="CBOT", contrato="Z26", unidade="cents/bu")
                for d in (10, 11, 12, 17, 18, 20)]
        r = tendencia_precos(rows, classe="CBOT",
                             serie_id="RONDONOPOLIS_SANTOS_SOJA_A", as_of=AS_OF)
        self.assertEqual(r["status"], "SHADOW_READY")
        with self.assertRaises(ErroMotor):
            tendencia_precos(rows + [preco(21, 110, classe="CBOT", contrato="H27",
                                          unidade="cents/bu")],
                             classe="CBOT", serie_id="RONDONOPOLIS_SANTOS_SOJA_A",
                             as_of=AS_OF)

    def test_indice_portuario_sombra_reconciliado(self):
        r = pressao_portuaria(porto(), as_of=AS_OF)
        self.assertEqual(r["status"], "SHADOW_READY")
        self.assertEqual(r["indice_pressao"], "40.20")
        self.assertEqual(r["percentil_historico"], "50.00")
        self.assertFalse(r["lineup_utilizado"])
        self.assertIsNone(r["lineup_72h_informado"])

    def test_cdp_nao_validado_nao_contamina_indice(self):
        primeiro = pressao_portuaria(porto(lineup_72h=2), as_of=AS_OF)
        segundo = pressao_portuaria(porto(lineup_72h=100), as_of=AS_OF)
        self.assertEqual(primeiro["indice_pressao"], segundo["indice_pressao"])

    def test_gates_de_ais_geofence_conciliacao_historico(self):
        for caso in (
            {"geocercas_validadas": False}, {"mmsi_unicos": False},
            {"conciliacao_ais_operacao": "0.72"},
            {"historico_navios_aguardando": [1, 2]},
            {"data_referencia": "2026-10-22T11:00:00Z"},
        ):
            with self.subTest(gate=caso):
                r = pressao_portuaria(porto(**caso), as_of=AS_OF)
                self.assertIsNone(r["indice_pressao"])
                self.assertFalse(r["publicavel"])

    def test_negar_contagens_invalidas_e_futuro(self):
        for dados in ({"navios_aguardando": -2}, {"navios_atracados": 1.3},
                      {"data_referencia": "2026-10-24T00:00:00Z"}):
            with self.subTest(dados=dados), self.assertRaises(ErroMotor):
                pressao_portuaria(porto(**dados), as_of=AS_OF)

    def test_resumo_corredores_sem_total_intermodal(self):
        r = resumo_logistico({
            "estado": "RECORTE_IMPORTADO_NAO_HOMOLOGADO",
            "recorte": "mt_ncm_amostra", "competencia": "2026-09",
            "sha256_origem": "sha-sintetico",
            "resumo_polos": [{"polo": {"id": "MT_RONDONOPOLIS_FERRO"},
                             "toneladas_no_recorte": "12"}],
        })
        self.assertEqual(r["recorte"], "mt_ncm_amostra")
        self.assertNotIn("total_toneladas", r)
        self.assertIn("nao atribuir transbordo", r["restricao"])

    def test_painel_e2e_tres_frentes_sem_somar_universos(self):
        pacote = {
            "corredores": {"estado": "RECORTE_IMPORTADO_NAO_HOMOLOGADO",
                          "recorte": "mt_sintetico", "competencia": "2026-09",
                          "resumo_polos": []},
            "portos": [porto()],
            "series": [{"classe": "FRETE_ANUNCIADO",
                        "serie_id": "RONDONOPOLIS_SANTOS_SOJA_A",
                        "observacoes": seis_precos()}],
        }
        r = montar_painel(pacote, as_of=AS_OF)
        self.assertEqual(r["status"], "ANALISE_SHADOW_NAO_HOMOLOGADA")
        self.assertEqual(r["maritimo"][0]["status"], "SHADOW_READY")
        self.assertEqual(r["quantitativo"][0]["tendencia"], "ALTA")
        self.assertEqual(r["logistica"]["recorte"], "mt_sintetico")
        self.assertNotIn("volume_intermodal_total", r)
        with self.assertRaises(ErroMotor):
            montar_painel(pacote | {"portos": [porto(), porto()]}, as_of=AS_OF)


if __name__ == "__main__":
    unittest.main()
