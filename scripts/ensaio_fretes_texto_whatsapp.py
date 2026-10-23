"""Ensaio de 28 divulgações ROTULADAS Meta → WhatsApp AI → R01/Quant.

Fixtures usam HMAC Meta e atestação independentes, todas sintéticas;
nenhuma conexão Meta, telefone real, upload, custo ou publicação.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json

from nivon.fretes_atestacoes import hash_evento, serializacao_canonica
from nivon.fretes_texto_original_whatsapp import (
    adaptar_divulgacao_whatsapp_original,
    executar_lote_whatsapp_rotulado_offline,
    triar_lote_whatsapp_em_quarentena_offline,
)

META_SECRET = "meta-fixture-secret-do-not-use-outside-tests-0123456789"
PSEUDO_KEY = b"WA-FREIGHT-PSEUDONYM-TEST-ONLY-012345678901"
ATTEST_KEYS = {
    "DIREITOS": b"WA-FREIGHT-RIGHTS-TEST-ONLY-01234567890",
    "RESOLUCAO": b"WA-FREIGHT-RESOLVER-TEST-ONLY-987654321",
}
EMISSORES = {"DIREITOS": "rights-fixture", "RESOLUCAO": "resolver-fixture"}
ASOF = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def _atestar(data: dict, domain: str, when: datetime) -> dict:
    p = dict(data)
    p.update(
        versao_atestacao=1, emissor_id=EMISSORES[domain],
        emitido_em=(when+timedelta(minutes=1)).isoformat(),
        valido_ate=(when+timedelta(days=1)).isoformat(),
    )
    p["assinatura_hmac_sha256"] = hmac.new(
        ATTEST_KEYS[domain],
        b"NIVON_ATTESTATION_V1\x00" + domain.encode() + b"\x00"
        + serializacao_canonica(p),
        sha256,
    ).hexdigest()
    return p


def _webhook(body: str, mid: str, pub: datetime) -> tuple[bytes, str]:
    packet = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-fixture",
            "changes": [{
                "field": "messages",
                "value": {"messages": [{
                    "id": mid, "timestamp": str(int(pub.timestamp())),
                    "type": "text", "text": {"body": body},
                    "from": "55TESTE_NAO_REAL",
                }]},
            }],
        }],
    }
    raw = json.dumps(packet, ensure_ascii=False, sort_keys=True).encode("utf-8")
    signature = "sha256=" + hmac.new(
        META_SECRET.encode(), raw, sha256,
    ).hexdigest()
    return raw, signature


def gerar_fixture(regime: str, dia_idx: int, ponto: int) -> dict:
    pub = datetime(2026,10,12,20,tzinfo=timezone.utc)+timedelta(days=dia_idx)
    preco = 145 + 10*ponto + 3*dia_idx
    ponto_nome = f"FAZENDA TESTE {ponto}"
    transportadora_nome = f"TRANSPORTADORA FICTICIA {ponto}"
    mid = f"wamid.test.{regime}.{dia_idx}.{ponto}"
    event_id = f"evento-{regime}-{dia_idx}-{ponto}"
    body = "\n".join((
        f"FRETE: R$ {preco},00/t",
        "PEDÁGIO: R$ 10,00/t",
        "PRODUTO: MILHO",
        "ORIGEM: Sorriso-MT",
        "DESTINO: Rondonopolis-MT",
        f"EMBARQUE: {ponto_nome}",
        f"TRANSPORTADORA: {transportadora_nome}",
        "DESCARGA: TERMINAL TESTE",
        "EQUIPAMENTO: RODOTREM",
        f"REGIME: {regime}",
        f"DATA: {pub.date().isoformat()}",
    ))
    event = {
        "tenant_id": "tenant-sintetico", "event_id": event_id, "version": 1,
        "classification": "FREIGHT_OFFER",
        "truth_classification": "OBSERVADO",
        "source_event_ids": [mid], "rate_unit": "BRL/t",
        "rate": f"{preco}.00", "product": "MILHO",
        "timestamp": pub.isoformat(),
        "origin": {"canonical_id": "mun:5107925", "raw_value": "Sorriso-MT"},
        "destination": {"canonical_id": "mun:5107602", "raw_value": "Rondonopolis-MT"},
        "entities": {
            "company": [{"canonical_id": f"transp:{ponto}", "raw_value": transportadora_nome}],
            "loading_point": [{"canonical_id": f"fazenda:{ponto}", "raw_value": ponto_nome}],
        },
        "provenance": {"provider":"fixture","source_event_id":mid},
    }
    res = {
        "status":"VERIFICADA","tenant_id":"tenant-sintetico",
        "event_id":event_id,"version":1,"source_event_id":mid,
        "prova_sha256":"a"*64,
        "municipio_ibge":"5107925","destino_ibge":"5107602",
        "pickup_entity_id":f"fazenda:{ponto}",
        "transportadora_id":f"transp:{ponto}",
        "descarga_entity_id":"terminal:001",
        "descarga_raw":"TERMINAL TESTE",
        "produto":"MILHO","equipamento":"RODOTREM","regime":regime,
        "rate_role":"BASE","frete_base_brl_t":f"{preco}.00",
        "pedagio_tipo":"ADICIONAL_VALOR","pedagio_brl_t":"10.00",
        "atualidade_comercial":"VERIFICADA_NO_CONTEUDO_ORIGINAL",
        "data_referencia_comercial":pub.date().isoformat(),
        "evento_sha256":hash_evento(event),
    }
    auth = {
        "tenant_id":"tenant-sintetico","provider":"fixture",
        "waba_id":"waba-fixture",
        "status":"APROVADA",
        "operacoes_permitidas":["LEITURA","ARMAZENAMENTO","ANALISE"],
        "fonte_id":"WA_TESTES_SEM_DIREITOS_REAIS",
        "comprovante_sha256":"b"*64,
    }
    raw, signature = _webhook(body, mid, pub)
    return {
        "raw_webhook":raw,"signature":signature,
        "evento":event,"resolucao":_atestar(res,"RESOLUCAO",pub),
        "autorizacao":_atestar(auth,"DIREITOS",pub),
        "data_coleta":pub+timedelta(minutes=5),
    }


def reemitir_pacote(p: dict, *, alterar_texto=None,
                   alterar_evento=None, alterar_resolucao=None) -> dict:
    p = deepcopy(p)
    if alterar_evento is not None:
        alterar_evento(p["evento"])
    if alterar_resolucao is not None:
        r={k:v for k,v in p["resolucao"].items()
           if k not in {"versao_atestacao","emissor_id","emitido_em",
                        "valido_ate","assinatura_hmac_sha256"}}
        alterar_resolucao(r)
        pub=datetime.fromisoformat(p["evento"]["timestamp"])
        p["resolucao"]=_atestar(r,"RESOLUCAO",pub)
    pub=datetime.fromisoformat(p["evento"]["timestamp"])
    doc=json.loads(p["raw_webhook"])
    text=doc["entry"][0]["changes"][0]["value"]["messages"][0]["text"]
    if alterar_texto is not None:
        text["body"]=alterar_texto(text["body"])
    p["raw_webhook"]=json.dumps(doc,sort_keys=True,ensure_ascii=False).encode("utf-8")
    p["signature"]="sha256="+hmac.new(
        META_SECRET.encode(),p["raw_webhook"],sha256).hexdigest()
    return p


def _adapter(p):
    return adaptar_divulgacao_whatsapp_original(
        **p, app_secret=META_SECRET,
        chave_hmac=PSEUDO_KEY,
        chaves_atestacao=ATTEST_KEYS,
        emissores_atestacao=EMISSORES,
    )


def executar() -> dict:
    pacotes=[gerar_fixture(regime,dia,ponto)
             for regime in ("PF","PJ")
             for dia in range(7) for ponto in (1,2)]
    prova=_adapter(pacotes[0])
    assert prova["evidencia_textual"]["campos_literais_conferidos"]==11
    assert "FAZENDA TESTE" not in str(prova["evidencia_textual"])
    r=executar_lote_whatsapp_rotulado_offline(
        pacotes,as_of=ASOF,chave_hmac=PSEUDO_KEY,
        chaves_atestacao=ATTEST_KEYS,emissores_atestacao=EMISSORES,
        app_secret=META_SECRET,
    )
    assert r["webhooks_assinados_e_rotulados"]==28
    assert r["n_series_individuais"]==4
    assert r["n_paineis_comerciais"]==2
    assert all(x["resultado"]["status"]=="BLOQUEADO_SHA_EDICAO_AUSENTE"
               for x in r["series_quantitativas"])
    assert not r["publicavel"] and not r["uso_preditivo_real_autorizado"]
    assert r["prova_externa_da_origem_homologada"] is False
    from nivon.fretes_adapter_whatsapp import ErroAdaptadorFrete

    invalidos = [
        reemitir_pacote(pacotes[0],alterar_texto=lambda t:t.replace("R$ 155,00/t","R$ 999,00/t")),
        reemitir_pacote(pacotes[0],alterar_texto=lambda t:t+"\nFRETE: R$ 155,00/t"),
        reemitir_pacote(pacotes[0],alterar_texto=lambda t:t.replace("PEDÁGIO: R$ 10,00/t\n","")),
        reemitir_pacote(pacotes[0],alterar_texto=lambda t:"Frete de milho, consulte condições."),
    ]
    resultados=[]
    for entrada in invalidos:
        try:
            _adapter(entrada)
        except (ErroAdaptadorFrete, PermissionError):
            resultados.append("BLOQUEADO")
        else:
            raise AssertionError("anúncio divergente ou ambíguo foi aceito")
    forged=deepcopy(pacotes[0])
    forged["raw_webhook"] += b" "
    try:
        _adapter(forged)
    except PermissionError:
        assinatura_bloqueada=True
    else:
        raise AssertionError("assinatura Meta adulterada foi aceita")
    # Fluxo não-atômico de quarentena offline: mantém evidências válidas
    # em série individual e segrega mensagem livre/republicação original.
    triagem=triar_lote_whatsapp_em_quarentena_offline(
        pacotes+[invalidos[-1],deepcopy(pacotes[0])],
        as_of=ASOF,chave_hmac=PSEUDO_KEY,
        chaves_atestacao=ATTEST_KEYS,
        emissores_atestacao=EMISSORES,app_secret=META_SECRET,
    )
    assert triagem["anuncios_rotulados_admitidos"]==28
    assert triagem["mensagens_em_quarentena"]==2
    assert triagem["n_series_individuais"]==4
    assert triagem["n_paineis_comerciais"]==2
    assert not triagem["publicavel"]
    assert "FAZENDA TESTE" not in str(triagem["quarentena"])
    return {
        "status":"WHATSAPP_ORIGINAL_ROTULADO_E2E_OFFLINE",
        "webhooks_sinteticos_assinados":28,
        "campos_literais_por_mensagem":11,
        "series_economicas":4, "paineis_r01":2,
        "amostras_adversariais_rejeitadas":len(resultados)+int(assinatura_bloqueada),
        "triagem_quarentena_admitidas":triagem["anuncios_rotulados_admitidos"],
        "triagem_quarentena_rejeitadas":triagem["mensagens_em_quarentena"],
        "texto_livre_sem_rotulos_homologado":False,
        "webhook_real_recebido":False,"publicavel":False,
        "cloud_upload_realizado":False,
    }


if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,sort_keys=True))
