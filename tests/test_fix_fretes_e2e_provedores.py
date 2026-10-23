"""Regressões E2E de correção da PR #42 — convergência logística NIVON.

Event fixtures sintéticas, atestações externas HMAC de teste e nenhuma
conexão ao WhatsApp, serviços, banco real, mensageria ou rede.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import unittest

from nivon.fretes_adapter_whatsapp import adaptar_evento_whatsapp
from nivon.fretes_atestacoes import hash_evento
from nivon.fretes_registros import consolidar_ofertas
from nivon.fretes_painel_pr30 import preparar_painel_pr30, ErroPainelFrete
from test_fretes_whatsapp_r01_e2e import (
    evento_sintetico, assinar, transformar, PSEUDO, KEYS, EMISSORES,
)


_ASSINATURA = frozenset({
    "assinatura_hmac_sha256", "versao_atestacao", "emissor_id",
    "emitido_em", "valido_ate",
})


def sem_assinatura(documento):
    return {k: v for k, v in documento.items() if k not in _ASSINATURA}


def oferta_atestada(provedor, *, evento_id="evt-compartilhado",
                   source_id="msg-distinta"):
    ev, res, direitos, coleta = evento_sintetico(
        date(2026, 10, 20), 1, 170
    )
    ev = deepcopy(ev)
    ev["event_id"] = evento_id
    ev["provenance"]["provider"] = provedor
    ev["provenance"]["source_event_id"] = source_id
    ev["source_event_ids"] = [source_id]

    res = sem_assinatura(res)
    res["event_id"] = evento_id
    res["source_event_id"] = source_id
    res["evento_sha256"] = hash_evento(ev)
    direitos = sem_assinatura(direitos)
    direitos["provider"] = provedor
    direitos["fonte_id"] = provedor
    return transformar(
        ev, assinar(res, "RESOLUCAO", coleta),
        assinar(direitos, "DIREITOS", coleta), coleta,
    )


class TestAuditoriaIntegracaoLogisticaIndependente(unittest.TestCase):
    def test_controle_evento_sintetico_atestado_individual_sem_envio(self):
        x = oferta_atestada("provider-A", source_id="mensagem-A")
        resultado = consolidar_ofertas([x])
        self.assertEqual(resultado["total_registros_individuais_deduplicados"], 1)
        self.assertEqual(resultado["registros"][0]["fonte_id"], "provider-A")
        self.assertEqual(resultado["registros"][0]["natureza"],
                         "FRETE_ANUNCIADO_NAO_CONTRATADO")

    def test_p0_cross_provider_duas_fontes_nao_viram_uma_oferta(self):
        # São dois eventos autorizados/assinados por provedores distintos,
        # com event_id local coincidente e source IDs diferentes.
        a = oferta_atestada("provider-A", source_id="mensagem-A")
        b = oferta_atestada("provider-B", source_id="mensagem-B")
        self.assertNotEqual(a.publicacao_id, b.publicacao_id)
        registro = consolidar_ofertas([a, b])
        self.assertEqual(registro["total_publicacoes_recebidas"], 2)
        self.assertEqual(registro["total_registros_divulgados"], 2)
        self.assertEqual(
            registro["total_registros_individuais_deduplicados"], 2,
            "P0: a integração R01 omitiu anúncio válido do segundo "
            "provedor sem prova global de republicação",
        )

    def test_p0_mesmos_ids_locais_de_provedores_distintos_nao_colidem(self):
        a = oferta_atestada("provider-A", source_id="id-local-123")
        b = oferta_atestada("provider-B", source_id="id-local-123")
        self.assertNotEqual(
            (a.oferta_id, a.registro_id, a.publicacao_id),
            (b.oferta_id, b.registro_id, b.publicacao_id),
            "P0: vetor completo de chaves não isola provedor",
        )
        for field in ("oferta_id", "registro_id", "publicacao_id"):
            with self.subTest(field=field):
                self.assertNotEqual(
                    getattr(a, field), getattr(b, field),
                    "P0: ID de evento/registro/publicação deve ser "
                    "escopado por tenant e provedor",
                )

    def test_p1_resultado_de_republicacao_nao_depende_da_ordem(self):
        a = oferta_atestada("provider-A", source_id="mensagem-A")
        # Republicação comprovada da MESMA oferta; metadata de postagem
        # posterior deve ser deterministicamente escolhida/preservada.
        b = replace(
            a,
            registro_id=a.registro_id + "-republicacao",
            publicacao_id=a.publicacao_id + "-republicacao",
            data_publicacao=a.data_publicacao + timedelta(minutes=4),
            data_coleta=a.data_coleta + timedelta(minutes=5),
        )
        direto = consolidar_ofertas([a, b])
        reverso = consolidar_ofertas([b, a])
        self.assertEqual(direto["republicacoes_confirmadas"], 1)
        self.assertEqual(reverso["republicacoes_confirmadas"], 1)
        self.assertEqual(
            direto["registros"], reverso["registros"],
            "P1: ordem de chegada dos lotes altera o representante "
            "e horário da oferta deduplicada, sem política determinística",
        )

    def test_controle_painel_bloqueia_collision_de_registro(self):
        a = oferta_atestada("provider-A", source_id="mensagem-A")
        b = oferta_atestada("provider-B", source_id="mensagem-B")
        # Teste positivo: o painel estatístico não recebe silenciosamente
        # dois registros com ID igual, embora a consolidação anterior perca um.
        # Forçar colisão artificial explícita para preservar o controle
        # negativo depois de corrigir o namespace por provedor.
        b_colisao = replace(b, registro_id=a.registro_id)
        with self.assertRaisesRegex(ErroPainelFrete, "duplicado"):
            preparar_painel_pr30(
                [a, b_colisao], origem_ibge="5107925", destino_ibge="5107602",
                descarga_entity_id="terminal:001", produto="SOJA",
                equipamento="RODOTREM", regime="PJ", pedagio="ADICIONAL",
                as_of=a.data_coleta + timedelta(days=1),
            )


if __name__ == "__main__":
    unittest.main()
