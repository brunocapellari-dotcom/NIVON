"""Proveniência SEMÂNTICA de texto original WhatsApp Cloud API, offline.

Admite APENAS o modelo de divulgação textual rotulada V1, com todos os
campos explícitos. Verifica bytes do webhook via assinatura Meta (chave
fornecida pelo runtime), ID e horário de uma mensagem, valores literais
e os dois atestadores do adaptador WhatsApp AI. Semântica de mensagem
livre, imagem, PDF, OCR, áudio ou texto ambíguo NÃO está homologada.

Nunca expõe número de telefone, nome bruto da fazenda, mensagem ou
tokens no resultado. São devolvidos somente digest e offsets do corpo,
não offsets dos bytes JSON originais. Não ativa coleta/armazenamento.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
import unicodedata
from typing import Mapping, Sequence

from .fretes_adapter_whatsapp import adaptar_evento_whatsapp, ErroAdaptadorFrete
from .fretes_registros import OfertaFrete
from .pipeline_fretes_quant import executar_lote_fretes_quant
from .whatsapp_webhook import verificar_assinatura

CAMPOS = frozenset((
    "FRETE", "PEDAGIO", "PRODUTO", "ORIGEM", "DESTINO", "EMBARQUE",
    "TRANSPORTADORA", "DESCARGA", "EQUIPAMENTO", "REGIME", "DATA",
))
_NUMERO = re.compile(r"R\$[ ]*([1-9][0-9]{0,8})(?:,([0-9]{1,2}))?[ ]*/t\Z", re.I)
_LINHA = re.compile(r"(?P<label>[A-Za-zÁÉÍÓÚÃÕÇáéíóúãõç ]{2,28}):[ \t]*(?P<valor>[^\r\n]+)\Z")
_ID_WHATSAPP = re.compile(r"[A-Za-z0-9_.:@-]{1,256}\Z")


def _nome(s: str) -> str:
    if not isinstance(s, str):
        raise ErroAdaptadorFrete("texto de evidência não informado")
    normal = unicodedata.normalize("NFKD", s.strip())
    return " ".join(
        "".join(ch for ch in normal if not unicodedata.combining(ch))
        .casefold().split()
    ).upper()


def _pares_unicos(pares):
    d = {}
    for k, v in pares:
        if k in d:
            raise ErroAdaptadorFrete("webhook original contém chave JSON duplicada")
        d[k] = v
    return d


def _numero(s: str, campo: str) -> Decimal:
    if not isinstance(s, str):
        raise ErroAdaptadorFrete(campo + ": literal monetário ausente")
    m = _NUMERO.fullmatch(s.strip())
    if m is None:
        raise ErroAdaptadorFrete(campo + ": requer R$ N,NN/t explícito")
    dec = m.group(1) + "." + (m.group(2) or "00").ljust(2, "0")
    return Decimal(dec)


def _somente_um(seq: object, nome: str) -> Mapping:
    if not isinstance(seq, list) or len(seq) != 1 or not isinstance(seq[0], Mapping):
        raise ErroAdaptadorFrete(nome + ": deve conter exatamente uma entrada")
    return seq[0]


def _valor_entidade(evento: Mapping, campo: str) -> str:
    entidades = evento.get("entities")
    if not isinstance(entidades, Mapping):
        raise ErroAdaptadorFrete("entidades originais ausentes")
    entidade = _somente_um(entidades.get(campo), campo)
    valor = entidade.get("raw_value")
    if not isinstance(valor, str) or not valor.strip():
        raise ErroAdaptadorFrete(campo + ": nome literal não fornecido")
    return valor


def _corpo_original(raw: bytes, signature: str, app_secret: str,
                    evento: Mapping, autorizacao: Mapping) -> str:
    if not isinstance(raw, bytes) or len(raw) > 128_000:
        raise ErroAdaptadorFrete("RAW de webhook excessivo ou inválido")
    # Verificador reutilizado da saída do WhatsApp; precisa de segredo
    # externo ao evento. HMAC assina os bytes JSON exatos, não texto remontado.
    verificar_assinatura(raw_body=raw, signature=signature,
                        app_secret=app_secret)
    try:
        root = json.loads(raw.decode("utf-8", "strict"),
                          object_pairs_hook=_pares_unicos,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ErroAdaptadorFrete("constante não finita no webhook")))
    except (ValueError, UnicodeError, TypeError) as exc:
        if isinstance(exc, ErroAdaptadorFrete):
            raise
        raise ErroAdaptadorFrete("RAW de webhook não é JSON UTF-8 válido") from exc
    if not isinstance(root, Mapping) or root.get("object") != "whatsapp_business_account":
        raise ErroAdaptadorFrete("não é webhook WhatsApp Cloud API")
    entry = _somente_um(root.get("entry"), "entry")
    # O ID da conta receptora só é aceito quando coberto pelo atestado
    # de DIREITOS, assinado por agente externo com chave independente.
    waba_autorizada = autorizacao.get("waba_id")
    if not isinstance(waba_autorizada, str) or not _ID_WHATSAPP.fullmatch(waba_autorizada):
        raise ErroAdaptadorFrete("WABA autorizada não atestada")
    if entry.get("id") != waba_autorizada:
        raise ErroAdaptadorFrete("webhook recebido por WABA diferente da autorização")
    change = _somente_um(entry.get("changes"), "changes")
    if change.get("field") != "messages":
        raise ErroAdaptadorFrete("webhook não contém mensagem")
    value = change.get("value")
    if not isinstance(value, Mapping) or value.get("statuses"):
        raise ErroAdaptadorFrete("statuses não são evidência comercial recebida")
    msg = _somente_um(value.get("messages") if isinstance(value, Mapping)
                       else None, "messages")
    provenance = evento.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ErroAdaptadorFrete("proveniência do evento não informada")
    mid = msg.get("id")
    if not isinstance(mid, str) or not _ID_WHATSAPP.fullmatch(mid) or (
        mid != provenance.get("source_event_id")):
        raise ErroAdaptadorFrete("ID da publicação não confere com o webhook")
    if msg.get("type") != "text" or not isinstance(msg.get("text"), Mapping):
        raise ErroAdaptadorFrete("somente mensagem de texto original é aceita")
    ts = msg.get("timestamp")
    if not isinstance(ts, str) or not re.fullmatch(r"[0-9]{10}", ts):
        raise ErroAdaptadorFrete("timestamp original da Meta inválido")
    try:
        original = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        informado = datetime.fromisoformat(
            str(evento.get("timestamp")).replace("Z", "+00:00"))
        if informado.tzinfo is None or informado.utcoffset() is None:
            raise ValueError("naive")
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise ErroAdaptadorFrete("tempo do webhook e evento inválidos") from exc
    if original != informado.astimezone(timezone.utc):
        raise ErroAdaptadorFrete("horário do evento não confere com o webhook")
    body = msg["text"].get("body")
    if not isinstance(body, str) or not 20 <= len(body) <= 32_000 or (
        "\r" in body or "\x00" in body
    ):
        raise ErroAdaptadorFrete("texto original ausente ou não canônico")
    return body


def _campos_rotulados(body: str) -> tuple[dict[str, str], dict[str, dict]]:
    values, locators = {}, {}
    cursor = 0
    for part in body.splitlines(keepends=True):
        content = part.rstrip("\n")
        m = _LINHA.fullmatch(content)
        if m is None:
            raise ErroAdaptadorFrete("texto livre/linha sem rótulo explícito")
        tag = _nome(m.group("label"))
        if tag not in CAMPOS or tag in values:
            raise ErroAdaptadorFrete("rótulo desconhecido ou repetido no RAW")
        valor = m.group("valor").strip()
        if not valor or len(valor) > 180:
            raise ErroAdaptadorFrete("valor de campo ausente/excessivo")
        ini = cursor + m.start("valor") + len(m.group("valor")) - len(m.group("valor").lstrip())
        fim = ini + len(valor)
        if body[ini:fim] != valor:
            raise ErroAdaptadorFrete("span literal inconsistente")
        values[tag] = valor
        locators[tag] = {
            "inicio_caractere_no_corpo": ini,
            "fim_caractere_no_corpo": fim,
            "trecho_sha256": sha256(valor.encode("utf-8")).hexdigest(),
        }
        cursor += len(part)
    if set(values) != CAMPOS:
        raise ErroAdaptadorFrete("divulgação textual não contém todas as condições econômicas")
    return values, locators


def conferir_webhook_frete_original(
    *, raw_webhook: bytes, signature: str, app_secret: str,
    evento: Mapping, resolucao: Mapping, autorizacao: Mapping,
    oferta: OfertaFrete,
) -> dict:
    """Verifica correspondência entre mensagem Meta assinada e oferta.

    A resolução dos IDs canônicos deve ter sido assinada em separado no
    adaptar_evento_whatsapp; esta prova liga a menção literal ao nome
    observado e à oferta. Não comprova cadastro empresarial ou geográfico.
    """
    if (not isinstance(evento, Mapping) or not isinstance(resolucao, Mapping)
            or not isinstance(autorizacao, Mapping)
            or not isinstance(oferta, OfertaFrete)):
        raise ErroAdaptadorFrete("evento/resolução/oferta sem contrato confiável")
    body = _corpo_original(raw_webhook, signature, app_secret, evento, autorizacao)
    valores, spans = _campos_rotulados(body)
    checks = {
        "PRODUTO": evento.get("product"),
        "ORIGEM": evento.get("origin", {}).get("raw_value") if isinstance(evento.get("origin"), Mapping) else None,
        "DESTINO": evento.get("destination", {}).get("raw_value") if isinstance(evento.get("destination"), Mapping) else None,
        "EMBARQUE": _valor_entidade(evento, "loading_point"),
        "TRANSPORTADORA": _valor_entidade(evento, "company"),
        "DESCARGA": resolucao.get("descarga_raw"),
        "EQUIPAMENTO": resolucao.get("equipamento"),
        "REGIME": resolucao.get("regime"),
        "DATA": resolucao.get("data_referencia_comercial"),
    }
    for label, expected in checks.items():
        if not isinstance(expected, str) or not expected.strip() or (
            _nome(valores[label]) != _nome(expected)
        ):
            raise ErroAdaptadorFrete("menção literal diverge do campo " + label)
    if valores["REGIME"] not in {"PJ", "PF"}:
        raise ErroAdaptadorFrete("regime deve estar explícito como PF ou PJ")
    if _numero(valores["FRETE"], "frete") != oferta.frete_base_brl_t:
        raise ErroAdaptadorFrete("frete anunciado diverge da fonte original")
    if _nome(valores["PEDAGIO"]) == "NAO INFORMADO":
        if oferta.pedagio_brl_t is not None or oferta.frete_cheio_brl_t is not None:
            raise ErroAdaptadorFrete("pedágio ausente foi inferido")
    elif _numero(valores["PEDAGIO"], "pedágio") != oferta.pedagio_brl_t:
        raise ErroAdaptadorFrete("pedágio diverge da fonte original")
    if oferta.pedagio_brl_t is not None and (
        oferta.frete_cheio_brl_t != oferta.frete_base_brl_t + oferta.pedagio_brl_t
    ):
        raise ErroAdaptadorFrete("frete cheio inconsistente")
    return {
        "status": "TEXTO_WHATSAPP_ROTULADO_CONFERIDO_OFFLINE",
        "webhook_raw_sha256": sha256(raw_webhook).hexdigest(),
        "corpo_sha256": sha256(body.encode("utf-8")).hexdigest(),
        "evidencias_por_campo": spans,
        "campos_literais_conferidos": len(spans),
        "hmac_meta_validado_sob_chave_runtime": True,
        "resolucao_id_canonico_validada_externamente": False,
        "origem_independente_de_producao_verificada": False,
        "direitos_reais_de_publicacao_comprovados": False,
        "texto_livre_nao_rotulado_homologado": False,
        "publicavel": False,
    }


def adaptar_divulgacao_whatsapp_original(
    *, raw_webhook: bytes, signature: str, app_secret: str,
    evento: Mapping, resolucao: Mapping, autorizacao: Mapping,
    data_coleta: datetime, chave_hmac: bytes, chaves_atestacao: Mapping,
    emissores_atestacao: Mapping,
) -> dict:
    """Converte evento apenas quando assinado e todos os campos batem."""
    oferta = adaptar_evento_whatsapp(
        evento, resolucao=resolucao, autorizacao=autorizacao,
        data_coleta=data_coleta, chave_hmac=chave_hmac,
        chaves_atestacao=chaves_atestacao,
        emissores_atestacao=emissores_atestacao,
    )
    prova = conferir_webhook_frete_original(
        raw_webhook=raw_webhook, signature=signature, app_secret=app_secret,
        evento=evento, resolucao=resolucao,
        autorizacao=autorizacao, oferta=oferta,
    )
    return {"oferta": oferta, "evidencia_textual": prova, "publicavel": False}


def executar_lote_whatsapp_rotulado_offline(
    amostras: Sequence[Mapping], *, as_of: datetime,
    chave_hmac: bytes, chaves_atestacao: Mapping,
    emissores_atestacao: Mapping, app_secret: str,
) -> dict:
    """Um lote completo, falha atômica sem série parcialmente liberada."""
    if not isinstance(amostras, (list, tuple)) or not 1 <= len(amostras) <= 1000:
        raise ErroAdaptadorFrete("lote de mensagens não é válido")
    ofertas, provas = [], []
    ids_de_origem, raws_vistos = set(), set()
    for pacote in amostras:
        if not isinstance(pacote, Mapping):
            raise ErroAdaptadorFrete("pacote de mensagem inválido")
        ev = pacote.get("evento")
        source = ev.get("provenance") if isinstance(ev, Mapping) else None
        origin_id = source.get("source_event_id") if isinstance(source, Mapping) else None
        if not isinstance(origin_id, str) or not _ID_WHATSAPP.fullmatch(origin_id):
            raise ErroAdaptadorFrete("ID da fonte ausente no lote")
        if origin_id in ids_de_origem:
            raise ErroAdaptadorFrete("republicação do mesmo source_event_id no lote")
        res = adaptar_divulgacao_whatsapp_original(
            raw_webhook=pacote["raw_webhook"],
            signature=pacote["signature"], app_secret=app_secret,
            evento=pacote["evento"], resolucao=pacote["resolucao"],
            autorizacao=pacote["autorizacao"], data_coleta=pacote["data_coleta"],
            chave_hmac=chave_hmac, chaves_atestacao=chaves_atestacao,
            emissores_atestacao=emissores_atestacao,
        )
        if res["oferta"].data_coleta > as_of:
            raise ErroAdaptadorFrete("observação ainda indisponível no corte")
        raw_sha = res["evidencia_textual"]["webhook_raw_sha256"]
        if raw_sha in raws_vistos:
            raise ErroAdaptadorFrete("RAW original repetido com IDs de origem distintos")
        ids_de_origem.add(origin_id)
        raws_vistos.add(raw_sha)
        ofertas.append(res["oferta"])
        provas.append(res["evidencia_textual"])
    resumo = executar_lote_fretes_quant(ofertas, as_of=as_of)
    if resumo["uso_preditivo_real_autorizado"] or resumo["publicavel"]:
        raise ErroAdaptadorFrete("fluxo de WhatsApp não pode promover previsão")
    return {
        **resumo, "webhooks_assinados_e_rotulados": len(provas),
        "digests_webhook": sorted(x["webhook_raw_sha256"] for x in provas),
        "verificacao_semantica": "TEXTO_WHATSAPP_ROTULADO_V1_OFFLINE",
        "raw_original_persistido_em_storage": False,
        "prova_externa_da_origem_homologada": False,
        "uso_preditivo_real_autorizado": False, "publicavel": False,
    }


def triar_lote_whatsapp_em_quarentena_offline(
    amostras: Sequence[Mapping], *, as_of: datetime,
    chave_hmac: bytes, chaves_atestacao: Mapping,
    emissores_atestacao: Mapping, app_secret: str,
) -> dict:
    """Separa anúncios originais verificáveis dos que exigem revisão.

    Não armazena os bytes; quarentena é APENAS estado de saída em
    memória. Não retorna texto, telefone ou aliases originais.
    Não dá permissão de coleta/produção. Um lote parcialmente válido
    só gera painéis descritivos dos registros efetivamente aceitos.
    Para bloqueio atômico total, usar executar_lote_whatsapp_rotulado_offline.
    """
    if not isinstance(amostras, (tuple, list)) or not 1 <= len(amostras) <= 1000:
        raise ErroAdaptadorFrete("lote de quarentena inválido")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ErroAdaptadorFrete("as_of de quarentena exige timezone")
    aceitas = []
    rejeitadas = []
    ids, raws = set(), set()
    for item in amostras:
        raw = item.get("raw_webhook") if isinstance(item, Mapping) else None
        fingerprint = (sha256(raw).hexdigest() if isinstance(raw, bytes)
                       else None)
        try:
            if not isinstance(item, Mapping):
                raise ErroAdaptadorFrete("pacote ausente")
            ev = item.get("evento")
            prov = ev.get("provenance") if isinstance(ev, Mapping) else None
            source = prov.get("source_event_id") if isinstance(prov, Mapping) else None
            if not isinstance(source, str) or not _ID_WHATSAPP.fullmatch(source):
                raise ErroAdaptadorFrete("source_event_id ausente")
            if source in ids or fingerprint in raws:
                raise ErroAdaptadorFrete("repetição de mensagem original")
            validado = adaptar_divulgacao_whatsapp_original(
                raw_webhook=raw, signature=item["signature"],
                app_secret=app_secret, evento=item["evento"],
                resolucao=item["resolucao"], autorizacao=item["autorizacao"],
                data_coleta=item["data_coleta"], chave_hmac=chave_hmac,
                chaves_atestacao=chaves_atestacao,
                emissores_atestacao=emissores_atestacao,
            )
            if validado["oferta"].data_coleta > as_of:
                raise ErroAdaptadorFrete("coleta indisponível no corte")
        except (ErroAdaptadorFrete, PermissionError, KeyError, TypeError, ValueError):
            # Sem mensagens/PII ou exceções contendo texto da fonte no
            # relatório. O digest é só identidade da evidência observada.
            rejeitadas.append({
                "raw_sha256":fingerprint,
                "status":"QUARENTENA_SEM_PROMOCAO",
                "revisao_semantica_ou_origem_necessaria":True,
            })
            continue
        aceitas.append(validado["oferta"])
        ids.add(source)
        raws.add(fingerprint)
    if aceitas:
        resumo = executar_lote_fretes_quant(aceitas, as_of=as_of)
    else:
        resumo = {
            "status":"LOTE_SEM_ANUNCIOS_ADMITIDOS",
            "n_series_individuais":0,"n_paineis_comerciais":0,
            "series_quantitativas":[],"tendencias_pareadas":[],
            "total_publicacoes_recebidas":0,
            "total_registros_divulgados":0,
            "total_registros_individuais_deduplicados":0,
            "pontos_unicos_por_municipio":[],
            "publicavel":False,"uso_preditivo_real_autorizado":False,
        }
    return {
        **resumo,
        "status":"TRIAGEM_WHATSAPP_OFFLINE_SEM_PERSISTENCIA",
        "mensagens_recebidas_no_lote":len(amostras),
        "anuncios_rotulados_admitidos":len(aceitas),
        "mensagens_em_quarentena":len(rejeitadas),
        "quarentena":rejeitadas,
        "raw_quarentena_persistido":False,
        "dados_pessoais_expostos_no_relatorio":False,
        "rejeitados_incluidos_nas_tendencias":False,
        "uso_preditivo_real_autorizado":False,
        "publicavel":False,
    }
