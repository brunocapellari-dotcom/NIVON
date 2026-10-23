"""Ensaio RAW estruturado V1 → anúncio → HMAC → semântica → R01/Quant.

Todos os dados são artificiais, originalmente JSON. Não confundir com
captura de mensagens livres do WhatsApp, licença ou provedor autenticado.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import hmac
import json

from nivon.fretes_atestacoes import serializacao_canonica
from nivon.fretes_raw_ponte_quant import DOMINIO
from nivon.fretes_raw_semantica import CONTRATO
from nivon.fretes_registros import OfertaFrete, consolidar_ofertas
from nivon.pipeline_fretes_quant import executar_lote_fretes_quant
from nivon.quant_core import ErroQuantitativo

SEGREDO = b"ENSAIO_CRIPTOGRAFICO_APENAS_FIXTURE_" + b"x"*32
CORTE = datetime(2026,10,21,20,tzinfo=timezone.utc)
FONTE = "FONTE_ESTRUTURADA_FIXTURE_NAO_AUTORIZADA"


def anuncios():
    rows = []
    for regime in ("PF","PJ"):
        for i in range(7):
            dia = date(2026,10,1) + timedelta(days=i)
            pub = datetime(dia.year,dia.month,dia.day,16,tzinfo=timezone.utc)
            for ponto in (1,2):
                preco = Decimal(150+ponto*10+i*3)
                ident = f"{regime}:{i}:{ponto}"
                rows.append(OfertaFrete(
                    publicacao_id="pub:"+ident, registro_id="reg:"+ident,
                    oferta_id="oferta:"+ident,
                    municipio_ibge="5107925",
                    pickup_entity_id=f"fazenda:{ponto}",
                    transportadora_id=f"transportadora:{ponto}",
                    destino_ibge="5107602", descarga_entity_id="terminal:001",
                    produto="MILHO", equipamento="RODOTREM", regime=regime,
                    frete_base_brl_t=preco, pedagio_brl_t=Decimal("10"),
                    frete_cheio_brl_t=preco+10,
                    data_referencia=dia, data_publicacao=pub,
                    data_coleta=pub+timedelta(hours=1),fonte_id=FONTE,
                ))
    return rows


def _raw_estruturado(row):
    doc = {k:row[k] for k in (
        "registro_id","oferta_id","fonte_id","municipio_ibge",
        "pickup_entity_id","transportadora_id","destino_ibge",
        "descarga_entity_id","produto","equipamento","regime",
        "data_referencia","data_publicacao","frete_base_brl_t",
        "pedagio_brl_t","frete_cheio_brl_t"
    )}
    doc.update(
        tipo="FRETE_ANUNCIADO",contrato=CONTRATO,
        publicacao_id=row["publicacoes_origem"][0],
    )
    return json.dumps(doc,sort_keys=True,ensure_ascii=False).encode("utf-8")


def _assinar(rows):
    raws,recibos={},{}
    for row in consolidar_ofertas(rows)["registros"]:
        original=_raw_estruturado(row)
        rid=row["registro_id"]
        pub=datetime.fromisoformat(row["data_publicacao"])
        pacote={
            "versao":1,"emissor_id":"CAPTURA_FIXTURE",
            "registro_id":rid,"oferta_id":row["oferta_id"],
            "publicacao_id":row["publicacoes_origem"][0],
            "fonte_id":FONTE,"raw_sha256":sha256(original).hexdigest(),
            "publicado_em":row["data_publicacao"],
            "capturado_em":(pub+timedelta(minutes=10)).isoformat(),
            "emitido_em":(pub+timedelta(minutes=20)).isoformat(),
        }
        pacote["assinatura_hmac_sha256"]=hmac.new(
            SEGREDO,DOMINIO+serializacao_canonica(pacote),sha256
        ).hexdigest()
        raws[rid],recibos[rid]=original,pacote
    return raws,recibos


def _executar(rows,raws,recibos):
    return executar_lote_fretes_quant(
        rows,as_of=CORTE,raws=raws,recibos=recibos,
        chave_captura=SEGREDO,emissor_esperado="CAPTURA_FIXTURE",
        verificacao_semantica=CONTRATO,
    )


def executar():
    registros=anuncios()
    raws,recibos=_assinar(registros)
    ok=_executar(registros,raws,recibos)
    assert ok["total_registros_divulgados"]==28
    assert ok["n_series_individuais"]==4
    assert ok["n_paineis_comerciais"]==2
    assert ok["registros_semantica_estruturada_conferidos"]==28
    assert all(x["resultado"]["correspondencia_semantica_estruturada_verificada"]
               for x in ok["series_quantitativas"])
    assert all(not x["resultado"]["uso_preditivo_real_autorizado"]
               for x in ok["series_quantitativas"])
    assert ok["semantica_whatsapp_livre_comprovada"] is False
    assert ok["publicavel"] is False

    # Mesmo HMAC verdadeiro do RAW: alterar o VALOR NORMALIZADO, sem alterar
    # original, deve falhar. Este era o elo não verificado anteriormente.
    alterados=list(registros)
    alterados[0]=replace(
        alterados[0],
        frete_base_brl_t=alterados[0].frete_base_brl_t + Decimal(5),
        frete_cheio_brl_t=alterados[0].frete_cheio_brl_t + Decimal(5)
    )
    try:
        _executar(alterados,raws,recibos)
    except ErroQuantitativo as exc:
        assert "divergem" in str(exc)
    else:
        raise AssertionError("preço normalizado adulterado passou pelo RAW")

    # JSON com campo duplicado é ambíguo ainda que possua HMAC legítimo.
    rid=registros[0].registro_id
    raw_duplicado=raws[rid][:-1]+b',"produto":"SOJA"}'
    raws2,recibos2=_assinar(registros)
    raws2[rid]=raw_duplicado
    payload=recibos2[rid]
    payload["raw_sha256"]=sha256(raw_duplicado).hexdigest()
    unsigned={k:v for k,v in payload.items() if k!="assinatura_hmac_sha256"}
    payload["assinatura_hmac_sha256"]=hmac.new(
        SEGREDO,DOMINIO+serializacao_canonica(unsigned),sha256
    ).hexdigest()
    try:
        _executar(registros,raws2,recibos2)
    except ErroQuantitativo as exc:
        assert "duplicado" in str(exc)
    else:
        raise AssertionError("campo duplicado passou verificador semântico")

    # Sem parser específico, RAW WhatsApp livre jamais passa por JSON_V1.
    raws3,recibos3=_assinar(registros)
    raws3[rid]=b"Frete Milho 170 por tonelada PJ"
    payload=recibos3[rid]
    payload["raw_sha256"]=sha256(raws3[rid]).hexdigest()
    unsigned={k:v for k,v in payload.items() if k!="assinatura_hmac_sha256"}
    payload["assinatura_hmac_sha256"]=hmac.new(
        SEGREDO,DOMINIO+serializacao_canonica(unsigned),sha256
    ).hexdigest()
    try:
        _executar(registros,raws3,recibos3)
    except ErroQuantitativo:
        pass
    else:
        raise AssertionError("WhatsApp livre foi promovido a JSON estruturado")

    return {
        "status":"RAW_ESTRUTURADO_SEMANTICA_E2E_APROVADO_APENAS_SINTETICO",
        "registros_conferidos":28,"series_economicas":4,"paineis_r01":2,
        "etapas":[
            "consolidar_28_registros","obter_bytes_originais_json_v1",
            "verificar_28_hmac","conferir_17_campos_por_registro",
            "comparar_valores_decimal_exatos","separar_regimes_pf_pj",
            "gerar_series_individuais","parear_tendencias_r01",
            "rejeitar_preco_normalizado_adulterado",
            "rejeitar_json_ambíguo","rejeitar_whatsapp_livre",
            "bloquear_publicacao_previsao",
        ],
        "semantica_whatsapp_livre_comprovada":False,
        "dados_reais_coletados":False,"publicavel":False,
    }


if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,sort_keys=True))
