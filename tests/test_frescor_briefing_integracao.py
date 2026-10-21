"""Regressões da conciliação PR #13 (frescor) + PR #26 (preflight)."""
import hashlib
import unittest
from datetime import timedelta

from nivon.briefing_composto import montar_briefing
from nivon.editorial_preflight import avaliar_previa_editorial
from nivon.politica_frescor_briefing import LIMITES_FRESCURA, validar_frescor_indicador


AGORA = "2026-10-20T09:00:00-03:00"
FONTES = {
    "TESTE": {
        "status_direitos": "APROVADA",
        "operacoes": ["LEITURA", "PUBLICACAO_DERIVADA"],
    }
}


def indicador(secao, referencia):
    return {
        "fonte_id": "TESTE", "secao": secao,
        "titulo": "Indicador sintético auditável",
        "valor": "R$ 100,00/L" if secao == "DIESEL" else "100,00",
        "fonte": "Fonte sintética", "referencia": referencia,
    }


def edicao_com_cotacao(*, referencia, secao="BOLSAS", grupo="CHICAGO",
                      publicado="2026-10-20T05:00:00-03:00"):
    titulo = "Chicago Soja Teste" if grupo == "CHICAGO" else "Diesel Teste"
    texto = (
        "*RESUMO ESTRATÉGICO DO AGRONEGÓCIO — NIVON*\n" +
        titulo + ": R$ 100,00/L (R$/L), ref. " + referencia + "\n"
    )
    edicao = {
        "estado": "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO", "enviado": False,
        "gerado_em": AGORA, "texto": texto,
        "sha256": hashlib.sha256(texto.encode()).hexdigest()
    }
    reg = {
        "fonte_id": "TESTE", "direitos_publicacao": True,
        "evidencia_direitos_id": "PROVA_SINTETICA_20261020",
        "sha256_origem": "a"*64, "publicado_em": publicado,
        "coletado_em": AGORA, "grupo": grupo, "secao": secao,
        "titulo": titulo, "valor": "100", "unidade": "R$/L",
        "natureza": "OBSERVADO", "competencia": referencia[:10],
        "referencia_em": referencia,
        "fechamento_confirmado": True,
        "sessao_fechamento": referencia[:10],
        "ultima_sessao_concluida": referencia[:10],
        "periodo_identificado": True,
    }
    return {
        "edicao": edicao, "gerado_em": AGORA, "noticias": [],
        "cotacoes": [reg], "fretes": [],
    }


class TestPoliticaFrescorIntegrada(unittest.TestCase):
    def test_limites_importados_da_pr13_iguais_por_secao(self):
        esperado = {
            "BOLSAS": 96, "CAMBIO": 96, "PRECOS": 168,
            "SAFRA": 1080, "PORTOS": 48, "DIESEL": 384,
            "FERTILIZANTES": 1080, "CLIMA": 48,
            "LOGISTICA": 72, "GEOPOLITICA": 72,
        }
        self.assertEqual({k: v.total_seconds() / 3600
                          for k, v in LIMITES_FRESCURA.items()}, esperado)

    def test_cbot_90_dias_rejeitada_mesmo_com_fonte_declarada(self):
        x = montar_briefing(noticias=[], fontes=FONTES, data=AGORA,
                           indicadores=[indicador("BOLSAS", "2026-07-22T17:00:00-03:00")])
        self.assertEqual(x["indicadores_incluidos"], 0)
        self.assertNotIn("Indicador sintético auditável", x["texto"])
        self.assertTrue(any("indicador vencido" in e["motivo"]
                            for e in x["rejeicoes"]))

    def test_noticias_tem_janela_independente_da_cotacao(self):
        x = montar_briefing(noticias=[], fontes=FONTES, data=AGORA,
                           indicadores=[indicador("BOLSAS", "2026-10-19T17:00:00-03:00")])
        self.assertEqual(x["indicadores_incluidos"], 1)
        self.assertIn("Indicador sintético auditável", x["texto"])

    def test_portos_2025_e_diesel_17_dias_nao_publicam(self):
        for secao, data in [
            ("PORTOS", "2025-10-20T08:00:00-03:00"),
            ("DIESEL", "2026-10-03T08:59:59-03:00"),
        ]:
            with self.subTest(secao=secao):
                x = montar_briefing(noticias=[], fontes=FONTES, data=AGORA,
                                   indicadores=[indicador(secao, data)])
                self.assertEqual(x["indicadores_incluidos"], 0)
                self.assertTrue(any("indicador vencido" in e["motivo"]
                                    for e in x["rejeicoes"]))

    def test_exatamente_96_horas_e_um_segundo_mais_antigo(self):
        validar_frescor_indicador(
            secao="BOLSAS", referencia="2026-10-16T09:00:00-03:00",
            gerado_em=AGORA
        )
        with self.assertRaisesRegex(ValueError, "indicador vencido"):
            validar_frescor_indicador(
                secao="BOLSAS", referencia="2026-10-16T08:59:59-03:00",
                gerado_em=AGORA
            )

    def test_timestamp_futuro_e_naive_bloqueados(self):
        for referencia in ("2026-10-20T09:01:00-03:00", "2026-10-20T09:00:00"):
            with self.subTest(referencia=referencia):
                with self.assertRaises(ValueError):
                    validar_frescor_indicador(
                        secao="PRECOS", referencia=referencia, gerado_em=AGORA
                    )

    def test_preflight_cbot_fora_de_janela_mesmo_com_calendario_declarado(self):
        d = edicao_com_cotacao(
            referencia="2026-07-22T17:00:00-03:00",
            publicado="2026-10-20T05:00:00-03:00",
        )
        r = avaliar_previa_editorial(**d)
        self.assertFalse(r["apto_revisao"])
        self.assertTrue(any("COTACAO_0:indicador vencido" in e
                            for e in r["bloqueios"]))

    def test_preflight_diesel_tem_16_dias_e_nao_limite_de_precos_7_dias(self):
        d = edicao_com_cotacao(
            referencia="2026-10-11T15:00:00-03:00",
            secao="DIESEL", grupo="ENERGIA", publicado="2026-10-11T15:00:00-03:00",
        )
        d["cotacoes"][0]["fechamento_confirmado"] = False
        self.assertFalse(any("COTACAO_0" in e
                             for e in avaliar_previa_editorial(**d)["bloqueios"]))
        d["cotacoes"][0]["secao"] = "PRECOS"
        self.assertTrue(any("COTACAO_0:indicador vencido" in e
                            for e in avaliar_previa_editorial(**d)["bloqueios"]))

    def test_anp_amostra_nao_pode_fingir_secao_precos(self):
        d = edicao_com_cotacao(
            referencia="2026-10-19T15:00:00-03:00",
            secao="PRECOS", grupo="ENERGIA",
            publicado="2026-10-20T04:00:00-03:00",
        )
        d["cotacoes"][0]["classe_estatistica"] = "MEDIA_AMOSTRAL_MUNICIPAL_REVENDA"
        self.assertTrue(any("COTACAO_0:ANP:" in e
                            for e in avaliar_previa_editorial(**d)["bloqueios"]))

    def test_sessao_mais_recente_nao_inferida_de_limite_96h(self):
        d = edicao_com_cotacao(referencia="2026-10-19T17:00:00-03:00")
        d["cotacoes"][0]["fechamento_confirmado"] = False
        r = avaliar_previa_editorial(**d)
        self.assertTrue(any("último fechamento" in e for e in r["bloqueios"]))


if __name__ == "__main__":
    unittest.main()
