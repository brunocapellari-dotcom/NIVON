"""E2E estritamente sintético: WhatsApp AI -> atestação -> NIVON -> R01.

Este teste NÃO prova provedor conectado, licenças reais, consentimento,
autenticidade de documentos RAW, nem autorização de publicação.
"""
from __future__ import annotations

import hmac
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from nivon.fretes_adapter_whatsapp import adaptar_evento_whatsapp, ErroAdaptadorFrete
from nivon.fretes_atestacoes import hash_evento
from nivon.fretes_integracao_r01 import tendencia_ofertas_pareadas
from nivon.fretes_registros import consolidar_ofertas

PSEUDO = b"only-synthetic-pseudonym-key-0000000000000000001"
KEYS = {
    "DIREITOS": b"only-synthetic-rights-key-000000000000000000001",
    "RESOLUCAO": b"only-synthetic-resolver-key-0000000000000000001",
}
EMISSORES = {"DIREITOS": "fixture-rights", "RESOLUCAO": "fixture-resolver"}


def assinar(data: dict, domain: str, received: datetime) -> dict:
    issued = received - timedelta(minutes=3)
    valid = received + timedelta(days=2)
    signed = {
        **data, "versao_atestacao": 1,
        "emissor_id": EMISSORES[domain],
        "emitido_em": issued.isoformat(),
        "valido_ate": valid.isoformat(),
    }
    payload = json.dumps(signed, sort_keys=True, ensure_ascii=True,
                         allow_nan=False, separators=(",", ":")).encode()
    signed["assinatura_hmac_sha256"] = hmac.new(
        KEYS[domain],
        b"NIVON_ATTESTATION_V1\x00" + domain.encode() + b"\x00" + payload,
        sha256,
    ).hexdigest()
    return signed


def evento_sintetico(dia: date, i: int, base: int):
    publicado = datetime(dia.year, dia.month, dia.day, 15, tzinfo=timezone.utc)
    coletado = publicado + timedelta(minutes=7)
    msg = f"msg-{dia.isoformat()}-{i}"
    codigo = f"evt-{dia.isoformat()}-{i}"
    pickup, carrier = f"ponto:{i}", f"carrier:{i}"
    ev = {
        "tenant_id": "tenant-fixture", "event_id": codigo, "version": 1,
        "classification": "FREIGHT_OFFER", "truth_classification": "OBSERVADO",
        "source_event_ids": [msg], "rate_unit": "BRL/t",
        "rate": str(base), "product": "SOJA", "timestamp": publicado.isoformat(),
        "origin": {"canonical_id": "mun:5107925", "raw_value": "origem fictícia"},
        "destination": {"canonical_id": "mun:5107602", "raw_value": "destino fictício"},
        "entities": {
            "loading_point": [{"canonical_id": pickup}],
            "company": [{"canonical_id": carrier}],
        },
        "provenance": {"provider": "fixture", "source_event_id": msg},
    }
    res = {
        "status": "VERIFICADA", "tenant_id": ev["tenant_id"],
        "event_id": codigo, "version": 1, "source_event_id": msg,
        "prova_sha256": "a"*64, "evento_sha256": hash_evento(ev),
        "municipio_ibge": "5107925", "destino_ibge": "5107602",
        "pickup_entity_id": pickup, "transportadora_id": carrier,
        "descarga_entity_id": "terminal:001", "produto": "SOJA",
        "equipamento": "RODOTREM", "regime": "PJ", "rate_role": "BASE",
        "frete_base_brl_t": str(base),
        "pedagio_tipo": "ADICIONAL_VALOR", "pedagio_brl_t": "10",
        "atualidade_comercial": "VERIFICADA_NO_CONTEUDO_ORIGINAL",
        "data_referencia_comercial": dia.isoformat(),
    }
    rights = {
        "status": "APROVADA", "tenant_id": ev["tenant_id"],
        "provider": "fixture", "fonte_id": "WHATSAPP_FIXTURE",
        "operacoes_permitidas": ["LEITURA", "ARMAZENAMENTO", "ANALISE"],
        "comprovante_sha256": "b"*64,
    }
    return ev, assinar(res, "RESOLUCAO", coletado), assinar(rights, "DIREITOS", coletado), coletado


def transformar(ev, res, rights, coletado):
    return adaptar_evento_whatsapp(
        ev, resolucao=res, autorizacao=rights,
        data_coleta=coletado, chave_hmac=PSEUDO,
        chaves_atestacao=KEYS, emissores_atestacao=EMISSORES,
    )


class TestCanalCompletoOffline(unittest.TestCase):
    def test_fluxo_sintetico_12_eventos_duas_entidades_seis_dias(self):
        dados = []
        inicio = date(2026, 10, 12)
        for j in range(6):
            dia = inicio + timedelta(days=j)
            for i in (1, 2):
                ev, res, rights, coleta = evento_sintetico(dia, i, 150+i*10+j*3)
                dados.append(transformar(ev, res, rights, coleta))
        agregados = consolidar_ofertas(dados)
        self.assertEqual(agregados["total_publicacoes_recebidas"], 12)
        self.assertEqual(agregados["total_registros_individuais_deduplicados"], 12)
        self.assertEqual(agregados["pontos_unicos_por_municipio_destino"][0]["quantidade"], 2)
        self.assertEqual(agregados["transportadoras"], 2)
        self.assertEqual(len(agregados["registros"]), 12)
        self.assertTrue(all(x["natureza"] == "FRETE_ANUNCIADO_NAO_CONTRATADO"
                            for x in agregados["registros"]))
        analise = tendencia_ofertas_pareadas(
            dados, origem_ibge="5107925", destino_ibge="5107602",
            descarga_entity_id="terminal:001", produto="SOJA",
            equipamento="RODOTREM", regime="PJ", pedagio="ADICIONAL",
            as_of=datetime(2026, 10, 20, 10, tzinfo=timezone.utc),
            janela=6, minimo_pares=2, tolerancia_absoluta=2,
        )
        self.assertEqual(analise["tendencia"], "ALTA")
        self.assertEqual(analise["motor"], "R01_CANONICO_PR30_CONTROLES_PR18")
        self.assertEqual(analise["metrica_tendencia"],
                         "VARIACAO_PAREADA_POR_ESTABELECIMENTO_TRANSPORTADORA")
        self.assertEqual(len(analise["identidades_comparaveis"]), 2)
        self.assertFalse(analise["publicavel"])
        self.assertIsNone(analise["probabilidades_calibradas"])
        self.assertNotIn("frete_medio_municipal", str(analise))

    def test_atestacao_fabricada_em_mensagem_nao_substitui_emissor_externo(self):
        ev, res, rights, coleta = evento_sintetico(date(2026,10,17),1,175)
        # Um atacante pode copiar metadados mas não a chave independente.
        res["transportadora_id"] = "carrier:forjado"
        with self.assertRaisesRegex(ErroAdaptadorFrete, "assinatura"):
            transformar(ev, res, rights, coleta)

    def test_republicacao_de_2024_em_2026_falha_antes_da_tendencia(self):
        ev, res, rights, coleta = evento_sintetico(date(2026,10,17),1,175)
        res["data_referencia_comercial"] = "2024-10-17"
        res = assinar({k:v for k,v in res.items()
                      if k not in {"versao_atestacao","emissor_id","emitido_em",
                                   "valido_ate","assinatura_hmac_sha256"}},
                      "RESOLUCAO", coleta)
        with self.assertRaisesRegex(ErroAdaptadorFrete, "antigo"):
            transformar(ev, res, rights, coleta)


if __name__ == "__main__":
    unittest.main()
