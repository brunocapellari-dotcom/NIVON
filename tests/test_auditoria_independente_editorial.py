"""Auditoria independente: pré-homologação editorial PR #26.

Fixtures sintéticas deliberadas. A aprovação de revisão NÃO equivale a envio.
Os quatro cenários hostis novos foram escolhidos a partir de inspeção do código;
devem falhar até que os contratos de frescor e de sessão sejam corrigidos.
"""
from __future__ import annotations

import hashlib
import unittest

from nivon.editorial_preflight import avaliar_previa_editorial

AGORA = "2026-10-20T15:00:00-03:00"
ORIGEM = {
    "fonte_id": "PROVEDOR_SINTETICO",
    "direitos_publicacao": True,
    "evidencia_direitos_id": "LICENCA_TESTE_NAO_REAL",
    "sha256_origem": "a" * 64,
}


def pacote_base():
    noticia = {
        **ORIGEM,
        "publicado_em": "2026-10-20T11:30:00-03:00",
        "coletado_em": "2026-10-20T12:00:00-03:00",
        "titulo": "Plantio sintético avança em Mato Grosso",
        "url": "https://example.org/safra-inventada",
        "evento_id": "EVENTO_SINTETICO_001",
        "publicacao_original_verificada": True,
    }
    cotacao = {
        **ORIGEM,
        "publicado_em": "2026-10-19T17:30:00-03:00",
        "coletado_em": "2026-10-20T08:00:00-03:00",
        "grupo": "CHICAGO",
        "titulo": "Chicago Milho Sintético",
        "valor": "450",
        "unidade": "USc/bu",
        "competencia": "2026-10-19",
        "natureza": "OBSERVADO",
        "referencia_em": "2026-10-19T17:00:00-03:00",
        "sessao_fechamento": "2026-10-19",
        "ultima_sessao_concluida": "2026-10-19",
        "fechamento_confirmado": True,
    }
    frete = {
        **ORIGEM,
        "publicado_em": "2026-10-20T10:00:00-03:00",
        "coletado_em": "2026-10-20T10:15:00-03:00",
        "origem": "Sorriso", "uf_origem": "MT",
        "destino": "Dom Aquino", "uf_destino": "MT",
        "pickup_entity_id": "ESTABELECIMENTO_SINTETICO_001",
        "transportadora": "TRANSPORTADORA_SINTETICA_001",
        "produto": "MILHO", "equipamento": "BITREM",
        "regime_pf_pj": "PJ", "condicao_pedagio": "INCLUSO",
        "tipo": "FRETE_ANUNCIADO",
        "valor_rs_t": "130",
        "referencia_em": "2026-10-20T09:00:00-03:00",
        "volume_t_dia": "800", "classificacao_volume": "REFERENCIA",
        "volume_realizado": False,
    }
    texto = (
        "*RESUMO ESTRATÉGICO DO AGRONEGÓCIO — NIVON*\n"
        "Chicago Milho Sintético: 450 USc/bu, fechamento em 19/10/2026\n"
        "Plantio sintético avança em Mato Grosso\n"
        "Sorriso/MT → Dom Aquino/MT: R$ 130/t, 800 t/dia "
        "(volume REFERENCIA), ref. 20/10/2026\n"
    )
    edicao = {
        "estado": "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO",
        "gerado_em": AGORA,
        "texto": texto,
        "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "enviado": False,
    }
    return {"edicao": edicao, "gerado_em": AGORA, "noticias": [noticia],
            "cotacoes": [cotacao], "fretes": [frete]}


def alterar_texto(pacote, anterior, novo):
    texto = pacote["edicao"]["texto"].replace(anterior, novo)
    assert texto != pacote["edicao"]["texto"]
    pacote["edicao"]["texto"] = texto
    pacote["edicao"]["sha256"] = hashlib.sha256(texto.encode("utf-8")).hexdigest()


class TestAuditoriaPreflightIndependente(unittest.TestCase):
    def test_controle_pacote_sintetico_coerente_apto_somente_a_revisao(self):
        resultado = avaliar_previa_editorial(**pacote_base())
        self.assertTrue(resultado["apto_revisao"], resultado["bloqueios"])
        self.assertEqual(resultado["modo"], "OFFLINE_SEM_ENVIO")

    def test_p0_cotacao_de_90_dias_nao_e_fechamento_atual(self):
        p = pacote_base()
        c = p["cotacoes"][0]
        c["referencia_em"] = "2026-07-20T17:00:00-03:00"
        c["sessao_fechamento"] = c["ultima_sessao_concluida"] = "2026-07-20"
        c["competencia"] = "2026-07-20"
        alterar_texto(p, "fechamento em 19/10/2026", "fechamento em 20/07/2026")
        resultado = avaliar_previa_editorial(**p)
        self.assertFalse(
            resultado["apto_revisao"],
            "P0: alegar último fechamento sem prova externa verificável não torna "
            "uma cotação de 90 dias atual",
        )

    def test_p0_anuncio_de_2024_nao_deve_ser_frete_corrente(self):
        p = pacote_base()
        p["fretes"][0]["referencia_em"] = "2024-10-20T09:00:00-03:00"
        alterar_texto(p, "ref. 20/10/2026", "ref. 20/10/2024")
        resultado = avaliar_previa_editorial(**p)
        self.assertFalse(
            resultado["apto_revisao"],
            "P0: republicação atual de anúncio histórico não é preço corrente",
        )

    def test_p1_sessao_local_antes_meia_noite_nao_e_dia_utc(self):
        p = pacote_base()
        p["cotacoes"][0]["referencia_em"] = "2026-10-19T23:30:00-03:00"
        # 23:30 local = 02:30Z no dia seguinte, enquanto a sessão é 19/10.
        resultado = avaliar_previa_editorial(**p)
        self.assertTrue(
            resultado["apto_revisao"],
            "P1: calendário da bolsa e data da sessão não podem ser comparados "
            "automaticamente à data UTC do timestamp da cotação",
        )

    def test_p0_volume_observado_precisa_evidencia_propria(self):
        p = pacote_base()
        p["fretes"][0]["classificacao_volume"] = "OBSERVADO"
        p["fretes"][0]["volume_realizado"] = True
        alterar_texto(p, "volume REFERENCIA", "volume OBSERVADO")
        resultado = avaliar_previa_editorial(**p)
        self.assertFalse(
            resultado["apto_revisao"],
            "P0: volume realizado/observado exige evidência operacional "
            "distinta da mera alegação da fonte",
        )


if __name__ == "__main__":
    unittest.main()
