"""Adaptadores OFFLINE para consultas auxiliares BrasilAPI no NIVON.

Não faz HTTP, não autoriza full scan, nem transforma taxas sem data em cotações
atuais. Fontes primárias: Siscomex/NCM; BCB/PTAX/SGS; IBGE Localidades.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

NCM_URL_BASE = "https://brasilapi.com.br/api/ncm/v1/"
TAXAS_URL = "https://brasilapi.com.br/api/taxas/v1"
_CODIGO = re.compile(r"(?:[0-9]{8}|[0-9]{4}\.[0-9]{2}\.[0-9]{2})\Z")


class ErroBrasilAPI(ValueError):
    """JSON, semântica ou identificador não compatível com consulta pontual."""


def _objeto_unico(pares):
    saida = {}
    for chave, valor in pares:
        if chave in saida:
            raise ErroBrasilAPI("chave JSON duplicada")
        saida[chave] = valor
    return saida


def _payload(payload: bytes):
    if not isinstance(payload, bytes) or not (1 <= len(payload) <= 1_000_000):
        raise ErroBrasilAPI("resposta vazia ou maior que 1 MB")
    try:
        return json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_objeto_unico)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroBrasilAPI("JSON inválido") from exc


def _coleta(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroBrasilAPI("coleta exige ISO 8601 com timezone")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroBrasilAPI("carimbo de coleta inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroBrasilAPI("coleta sem fuso horário")
    return dt.astimezone(timezone.utc).isoformat()


def _codigo(valor: str) -> str:
    if not isinstance(valor, str) or _CODIGO.fullmatch(valor) is None:
        raise ErroBrasilAPI("NCM deve ter exatamente oito dígitos")
    return valor.replace(".", "")


def _data(valor: str, *, permitir_aberta: bool = False) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valor):
        raise ErroBrasilAPI("data NCM ausente ou inválida")
    if permitir_aberta and valor == "9999-12-31":
        return valor
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError as exc:
        raise ErroBrasilAPI("data NCM impossível") from exc


def normalizar_ncm_individual(payload: bytes, *, codigo_consultado: str,
                              coletado_em: str) -> dict:
    """Normaliza SOMENTE /ncm/v1/{code}; nunca invoca listagem integral.

    A tabela brasileira vigente e suas edições são responsabilidade do Siscomex.
    Não infere NCM válido hoje apenas porque a API respondeu.
    """
    codigo = _codigo(codigo_consultado)
    coleta = _coleta(coletado_em)
    dados = _payload(payload)
    if not isinstance(dados, dict) or _codigo(dados.get("codigo")) != codigo:
        raise ErroBrasilAPI("resposta não corresponde ao NCM consultado")
    descricao = dados.get("descricao")
    if not isinstance(descricao, str) or not descricao.strip() or len(descricao) > 800:
        raise ErroBrasilAPI("descrição NCM inválida")
    inicio = _data(dados.get("data_inicio"))
    fim = _data(dados.get("data_fim"), permitir_aberta=True)
    if fim < inicio:
        raise ErroBrasilAPI("vigência invertida")
    ato = {}
    for campo in ("tipo_ato", "numero_ato", "ano_ato"):
        valor = dados.get(campo)
        if valor is not None and (not isinstance(valor, str) or not 1 <= len(valor.strip()) <= 100):
            raise ErroBrasilAPI("ato normativo malformado")
        ato[campo] = valor
    return {
        "dataset_id": "BRASILAPI_NCM_CONSULTA",
        "fonte_id": "BRASILAPI",
        "origem_url": NCM_URL_BASE + codigo,
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "codigo_ncm": codigo,
        "descricao": descricao.strip(),
        "vigencia_inicio": inicio,
        "vigencia_fim": None if fim == "9999-12-31" else fim,
        "vigencia_sem_fim_definido": fim == "9999-12-31",
        **ato,
        "competencia": None,
        "referencia": None,
        "publicacao": None,
        "coleta": coleta,
        "estado": "REFERENCIA_AUXILIAR_NAO_HOMOLOGADA_CONTRA_SISCOMEX",
        "apto_publicacao_automatica": False,
    }


def normalizar_taxas_sem_data(payload: bytes, *, coletado_em: str) -> dict:
    """Inspeciona dados exploratórios SEM data de referência, não série temporal."""
    coleta = _coleta(coletado_em)
    dados = _payload(payload)
    if not isinstance(dados, list) or not (1 <= len(dados) <= 50):
        raise ErroBrasilAPI("taxas precisam formar lista limitada não vazia")
    saida, vistos = [], set()
    for item in dados:
        if not isinstance(item, dict) or not isinstance(item.get("nome"), str):
            raise ErroBrasilAPI("taxa sem identificação")
        nome = item["nome"].strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ -]{0,40}", nome):
            raise ErroBrasilAPI("nome de taxa inválido")
        if nome.upper() in vistos:
            raise ErroBrasilAPI("taxa repetida")
        vistos.add(nome.upper())
        valor = item.get("valor")
        if type(valor) not in (float, int):
            raise ErroBrasilAPI("valor de taxa não numérico")
        try:
            num = Decimal(str(valor))
        except InvalidOperation as exc:
            raise ErroBrasilAPI("valor inválido") from exc
        if not num.is_finite() or not -100 < num < 1000:
            raise ErroBrasilAPI("valor de taxa fora dos limites sanitários")
        # Campo 'valor' não possui competência, data ou unidade explícita.
        saida.append({"nome": nome, "valor_reportado": str(num), "unidade": None,
                      "competencia": None, "referencia": None, "publicacao": None})
    return {
        "dataset_id": "BRASILAPI_TAXAS_SEM_DATA",
        "fonte_id": "BRASILAPI",
        "origem_url": TAXAS_URL,
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "coleta": coleta,
        "indicadores": sorted(saida, key=lambda i: i["nome"]),
        "estado": "SEM_DATA_DE_REFERENCIA_BLOQUEADO_PARA_INDICADORES",
        "apto_briefing": False,
        "apto_tendencias": False,
        "apto_serie_historica": False,
    }
