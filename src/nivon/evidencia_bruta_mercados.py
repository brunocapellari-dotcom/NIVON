"""Evidência hash dos bytes brutos e do lote JSONL normalizado, OFFLINE.

Duas provas diferentes:
- o SHA-256 do arquivo original prova que estes bytes correspondem ao
  digest informado por uma origem confiável EXTERNA;
- o SHA-256 do lote JSONL prova que as linhas usadas na análise não foram
  alteradas depois da extração.
A correção do parser (raw -> JSONL), a origem, os direitos e a verdade das
cotações NÃO são automaticamente verificados por estas duas provas.
"""
from __future__ import annotations

from datetime import timezone
from hashlib import sha256
import json
from typing import Mapping

from .qualidade_mercados import preparar_serie_precos, _momento


class ErroEvidenciaMercado(ValueError):
    """Arquivo, manifest ou normalização sem prova íntegra."""


MANIFEST_FIELDS = frozenset({
    "schema", "fonte_id", "fonte_url", "raw_sha256",
    "normalizado_sha256", "capturado_em", "parser_id",
    "parser_versao", "direitos_status",
})
SCHEMA = "NIVON_MARKET_RAW_NORM_V1"
MAX_RAW = 12_000_000
MAX_JSONL = 8_000_000
MAX_LINHAS = 10_000
MAX_LINHA = 50_000


def _hash(v: object, nome: str) -> str:
    if (not isinstance(v, str) or len(v) != 64 or
            any(c not in "0123456789abcdef" for c in v)):
        raise ErroEvidenciaMercado(f"{nome}: SHA256 inválido")
    return v


def _texto(v: object, nome: str) -> str:
    if (not isinstance(v, str) or not 1 <= len(v) <= 120 or
            v.strip() != v):
        raise ErroEvidenciaMercado(f"{nome}: identificador inválido")
    return v


def _lote_jsonl_conferido(payload: bytes) -> list[dict]:
    if (not isinstance(payload, bytes) or not payload or
            len(payload) > MAX_JSONL or not payload.endswith(b"\n") or
            payload.startswith(b"\xef\xbb\xbf") or b"\x00" in payload):
        raise ErroEvidenciaMercado("JSONL ausente, não finalizado ou incompatível")
    partes = payload.split(b"\n")[:-1]
    if not 1 <= len(partes) <= MAX_LINHAS:
        raise ErroEvidenciaMercado("quantidade de registros JSONL inválida")
    saida = []

    def sem_campos_repetidos(pares):
        obj = {}
        for k, v in pares:
            if k in obj:
                raise ErroEvidenciaMercado("chave JSON repetida")
            obj[k] = v
        return obj

    def sem_constante_nao_finita(valor):
        raise ErroEvidenciaMercado("constante não finita no JSONL")

    for linha in partes:
        if not linha or len(linha) > MAX_LINHA:
            raise ErroEvidenciaMercado("linha JSONL ausente ou excessiva")
        try:
            obj = json.loads(
                linha.decode("utf-8", errors="strict"),
                object_pairs_hook=sem_campos_repetidos,
                parse_constant=sem_constante_nao_finita,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise ErroEvidenciaMercado("JSONL inválido") from exc
        if not isinstance(obj, dict):
            raise ErroEvidenciaMercado("linha JSONL deve ser objeto")
        saida.append(obj)
    return saida


def preparar_precos_com_artefatos(
    arquivo_original: bytes, snapshot_jsonl: bytes, *,
    manifesto: Mapping, as_of: str,
) -> dict:
    """Compara os bytes com o manifesto; usa EXATAMENTE as linhas verificadas.

    O snapshot_jsonl é o resultado do parser: mesmo com hash íntegro,
    não é uma cópia fiel certificada do arquivo de mercado original.
    """
    if not isinstance(manifesto, Mapping) or set(manifesto) != MANIFEST_FIELDS:
        raise ErroEvidenciaMercado("manifesto com campos ausentes ou inesperados")
    if manifesto["schema"] != SCHEMA or manifesto["direitos_status"] != "NAO_HOMOLOGADO":
        raise ErroEvidenciaMercado("schema ou status de direitos inválidos")
    fonte = _texto(manifesto["fonte_id"], "fonte_id")
    url = _texto(manifesto["fonte_url"], "fonte_url")
    _texto(manifesto["parser_id"], "parser_id")
    _texto(manifesto["parser_versao"], "parser_versao")
    try:
        capturado = _momento(manifesto["capturado_em"], "capturado_em")
        corte = _momento(as_of, "as_of")
    except ValueError as exc:
        raise ErroEvidenciaMercado("timestamp do snapshot inválido") from exc
    if capturado > corte:
        raise ErroEvidenciaMercado("snapshot coletado após as_of")
    if (not isinstance(arquivo_original, bytes) or not arquivo_original or
            len(arquivo_original) > MAX_RAW):
        raise ErroEvidenciaMercado("arquivo original ausente ou excessivo")
    raw_esperado = _hash(manifesto["raw_sha256"], "raw_sha256")
    norm_esperado = _hash(manifesto["normalizado_sha256"], "normalizado_sha256")
    if sha256(arquivo_original).hexdigest() != raw_esperado:
        raise ErroEvidenciaMercado("hash do arquivo original diverge")
    if (not isinstance(snapshot_jsonl, bytes) or
            sha256(snapshot_jsonl).hexdigest() != norm_esperado):
        raise ErroEvidenciaMercado("hash do snapshot normalizado diverge")
    rows = _lote_jsonl_conferido(snapshot_jsonl)
    for row in rows:
        if row.get("fonte_id") != fonte or row.get("fonte_url") != url:
            raise ErroEvidenciaMercado("fonte dos registros diverge do manifesto")
        try:
            coleta = _momento(row.get("coleta_em"), "coleta_em")
        except ValueError as exc:
            raise ErroEvidenciaMercado("timestamp da cotação inválido") from exc
        if coleta > capturado:
            raise ErroEvidenciaMercado("cotação extraída depois da captura do lote")
    preparado = preparar_serie_precos(rows, as_of=as_of)
    return {
        **preparado,
        "status": "SNAPSHOT_HASH_CONFERIDO_OFFLINE_NAO_HOMOLOGADO",
        "evidencia_arquivos": {
            "raw_sha256": raw_esperado,
            "normalizado_sha256": norm_esperado,
            "registros_jsonl": len(rows),
            "parser_id": manifesto["parser_id"],
            "parser_versao": manifesto["parser_versao"],
            "bytes_original_conferidos": True,
            "bytes_normalizados_conferidos": True,
            "fidelidade_parser_independente_verificada": False,
            "origem_remota_autenticada": False,
            "direitos_publicacao_verificados": False,
        },
        "publicavel": False,
        "probabilidades_calibradas": None,
    }
