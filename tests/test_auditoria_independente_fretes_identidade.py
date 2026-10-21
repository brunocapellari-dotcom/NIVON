"""Auditoria independente de identidade e proveniência de anúncios de frete.

Todos os eventos são sintéticos e nenhuma interface WhatsApp real é acessada.
Testes adversariais intencionais: o contrato deve falhar fechado até correção.
"""
from __future__ import annotations

import unittest
import json
import hmac
from hashlib import sha256
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from nivon.fretes_registros import OfertaFrete, consolidar_ofertas
from nivon.fretes_adapter_whatsapp import adaptar_evento_whatsapp
from nivon.fretes_atestacoes import hash_evento


HMAC_TESTE = b"chave-exclusivamente-sintetica-com-mais-de-32-bytes"
CHAVES_ASSINATURA = {
    "DIREITOS": b"testes-rights-assinatura-20261021-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "RESOLUCAO": b"testes-resolucao-assinatura-20261021-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
}
EMISSORES = {"DIREITOS": "autoridade-direitos-sintetica",
            "RESOLUCAO": "autoridade-resolucao-sintetica"}


def atestar(documento, dominio):
    body = dict(documento)
    body.update({
        "versao_atestacao": 1, "emissor_id": EMISSORES[dominio],
        "emitido_em": "2026-10-19T00:00:00+00:00",
        "valido_ate": "2026-10-24T00:00:00+00:00",
    })
    raw = json.dumps(body, sort_keys=True, ensure_ascii=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    body["assinatura_hmac_sha256"] = hmac.new(
        CHAVES_ASSINATURA[dominio],
        b"NIVON_ATTESTATION_V1\x00" + dominio.encode("utf-8") + b"\x00" + raw,
        sha256,
    ).hexdigest()
    return body



def oferta(**modificacoes):
    dados = {
        "publicacao_id": "pub-01", "registro_id": "registro-01",
        "oferta_id": "oferta-canonica-01",
        "municipio_ibge": "5107925", "pickup_entity_id": "fazenda-01",
        "transportadora_id": "transportadora-01", "destino_ibge": "5107602",
        "descarga_entity_id": "terminal-01", "produto": "MILHO",
        "equipamento": "RODOTREM", "regime": "PJ",
        "frete_base_brl_t": Decimal("150.00"),
        "pedagio_brl_t": Decimal("10.00"),
        "frete_cheio_brl_t": Decimal("160.00"),
        "data_referencia": date(2026, 10, 20),
        "data_publicacao": datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
        "data_coleta": datetime(2026, 10, 20, 13, tzinfo=timezone.utc),
        "fonte_id": "PROVEDOR-A",
    }
    dados.update(modificacoes)
    return OfertaFrete(**dados)


def evento(provider="PROVEDOR-A", *, tenant="TENANT-001",
           momento="2026-10-20T12:00:00+00:00", origem_id=None):
    source = origem_id or "msg-" + provider
    e = {
        "tenant_id": tenant, "event_id": "evt-123", "version": 1,
        "classification": "FREIGHT_OFFER", "truth_classification": "OBSERVADO",
        "source_event_ids": [source], "rate_unit": "BRL/t",
        "rate": "150.00", "product": "MILHO", "timestamp": momento,
        "origin": {"canonical_id": "mun:5107925"},
        "destination": {"canonical_id": "mun:5107602"},
        "entities": {"company": [{"canonical_id": "transportadora-01"}],
                     "loading_point": [{"canonical_id": "fazenda-01"}]},
        "provenance": {"provider": provider, "source_event_id": source},
    }
    r = {
        "status": "VERIFICADA", "tenant_id": tenant, "event_id": "evt-123",
        "version": 1, "source_event_id": source, "prova_sha256": "a" * 64,
        "municipio_ibge": "5107925", "destino_ibge": "5107602",
        "pickup_entity_id": "fazenda-01",
        "transportadora_id": "transportadora-01",
        "descarga_entity_id": "terminal-01",
        "produto": "MILHO", "equipamento": "RODOTREM", "regime": "PJ",
        "rate_role": "BASE", "frete_base_brl_t": "150.00",
        "pedagio_tipo": "ADICIONAL_VALOR", "pedagio_brl_t": "10.00",
        "atualidade_comercial": "VERIFICADA_NO_CONTEUDO_ORIGINAL",
        "data_referencia_comercial": "2026-10-20",
    }
    a = {
        "tenant_id": tenant, "provider": provider, "status": "APROVADA",
        "operacoes_permitidas": ["LEITURA", "ARMAZENAMENTO", "ANALISE"],
        "fonte_id": provider, "comprovante_sha256": "b" * 64,
    }
    return e, r, a


def adaptar(provider="PROVEDOR-A", *, tenant="TENANT-001",
            momento="2026-10-20T12:00:00+00:00",
            coletado=datetime(2026, 10, 20, 13, tzinfo=timezone.utc)):
    e, r, a = evento(provider, tenant=tenant, momento=momento)
    r["evento_sha256"] = hash_evento(e)
    return adaptar_evento_whatsapp(
        e, resolucao=atestar(r, "RESOLUCAO"),
        autorizacao=atestar(a, "DIREITOS"),
        data_coleta=coletado, chave_hmac=HMAC_TESTE,
        chaves_atestacao=CHAVES_ASSINATURA,
        emissores_atestacao=EMISSORES,
    )


class TestAuditoriaIndependenteFreteIdentidade(unittest.TestCase):
    def test_controle_republicacao_mesma_oferta_e_mesma_fonte(self):
        a = oferta()
        b = replace(a, publicacao_id="pub-02", registro_id="registro-02")
        resultado = consolidar_ofertas([a, b])
        self.assertEqual(resultado["total_registros_individuais_deduplicados"], 1)
        self.assertEqual(resultado["republicacoes_confirmadas"], 1)

    def test_p0_fonte_distinta_sem_link_de_evidencia_nao_e_republicacao(self):
        a = oferta()
        # Mesmo identificador local pode ser reutilizado em outra fonte; não há
        # atestado externo de que sejam a mesma oferta econômica.
        b = replace(
            a, fonte_id="PROVEDOR-B", publicacao_id="pub-b",
            registro_id="registro-b",
        )
        resultado = consolidar_ofertas([a, b])
        self.assertEqual(
            resultado["total_registros_individuais_deduplicados"], 2,
            "P0: não deduplicar duas fontes distintas sem identidade "
            "global comprovada e proveniência vinculada",
        )

    def test_p0_mesmo_event_id_em_dois_provedores_nao_colide_hmac(self):
        a = adaptar("PROVEDOR-A")
        b = adaptar("PROVEDOR-B")
        self.assertNotEqual(
            a.oferta_id, b.oferta_id,
            "P0: namespace de event_id deve incorporar provider ou "
            "identidade global atestada",
        )
        self.assertNotEqual(
            a.registro_id, b.registro_id,
            "P0: IDs de registro não podem colidir entre provedores",
        )

    def test_controle_tenants_distintos_mantidos_separados(self):
        a = adaptar("PROVEDOR-A", tenant="TENANT-001")
        b = adaptar("PROVEDOR-A", tenant="TENANT-002")
        self.assertNotEqual(a.oferta_id, b.oferta_id)

    def test_p1_timezone_externo_nao_pode_invalidar_mesmo_instante(self):
        # 19/10 22h -12 = 20/10 10h UTC = 20/10 06h America/Cuiaba.
        # Validação por data do offset de entrada, não pelo fuso canônico,
        # rejeitaria erroneamente uma observação cronologicamente válida.
        x = adaptar(
            "PROVEDOR-A", momento="2026-10-19T22:00:00-12:00",
            coletado=datetime(2026, 10, 20, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(x.data_referencia.isoformat(), "2026-10-20")

    def test_controle_precos_por_estabelecimento_nunca_media_municipal(self):
        a = oferta()
        b = oferta(publicacao_id="pub-02", registro_id="registro-02",
                   oferta_id="oferta-02", pickup_entity_id="fazenda-02",
                   frete_base_brl_t=Decimal("180.00"),
                   frete_cheio_brl_t=Decimal("190.00"))
        resultado = consolidar_ofertas([a, b])
        self.assertEqual(
            {x["frete_base_brl_t"] for x in resultado["registros"]},
            {"150.00", "180.00"},
        )
        self.assertEqual(resultado["pontos_unicos_por_municipio"][0]["quantidade"], 2)
        self.assertNotIn("frete_medio_municipal", str(resultado))


if __name__ == "__main__":
    unittest.main()
