"""Auditor independente da extração CSV canônico v1 -> JSONL, sem rede.

Formato de ENSAIO NIVON, não é o formato oficial de CME, ICE ou CEPEA.
Recusa omissão/injeção de linhas e exige correspondência exata de cada
campo, inclusive preço decimal textual e localização byte-a-byte da linha.

Provar a transformação deste formato controlado NÃO equivale a comprovar
a extração de um formato de fornecedor real, nem sua autoria/licença.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import io
from typing import Mapping

from .evidencia_bruta_mercados import (
    ErroEvidenciaMercado, MAX_LINHAS, MAX_LINHA,
    _lote_jsonl_conferido, preparar_precos_com_artefatos,
)


class ErroExtracaoCSV(ErroEvidenciaMercado):
    """Linha ausente, posição falsa, preço alterado ou contrato inválido."""


COLUNAS = (
    "mercado", "produto", "contrato", "tipo", "unidade", "instrumento_id",
    "localidade_ibge", "ponto_cotacao_id", "qualidade_id",
    "condicao_entrega_id", "condicao_pagamento_id", "regime_tributario_id",
    "data_referencia", "competencia", "referencia_em", "publicacao_em",
    "coleta_em", "fonte_id", "fonte_url", "edicao_sha256",
    "revisao_de_sha256", "preco",
)
OPCIONAIS = frozenset({
    "contrato", "instrumento_id", "localidade_ibge", "ponto_cotacao_id",
    "qualidade_id", "condicao_entrega_id", "condicao_pagamento_id",
    "regime_tributario_id", "revisao_de_sha256",
})
METADADOS = frozenset({"raw_linha", "raw_linha_sha256"})
ALLOWED = frozenset(COLUNAS) | METADADOS
CSV_PARSER_ID = "NIVON_CSV_CANONICO_V1"
CSV_PARSER_VERSAO = "1"


def _csv_linhas(raw: bytes) -> list[dict]:
    if not isinstance(raw, bytes) or not raw or b"\x00" in raw or b"\r" in raw:
        raise ErroExtracaoCSV("arquivo CSV inválido, CRLF não previsto no contrato")
    linhas = raw.splitlines(keepends=True)
    if (not 2 <= len(linhas) <= MAX_LINHAS + 1 or
            any(not l.endswith(b"\n") or len(l) > MAX_LINHA or l == b"\n"
                for l in linhas)):
        raise ErroExtracaoCSV("CSV: número/tamanho/terminador de linhas inválido")
    try:
        s = [l[:-1].decode("utf-8", errors="strict") for l in linhas]
    except UnicodeDecodeError as exc:
        raise ErroExtracaoCSV("CSV: UTF-8 inválido") from exc
    if s[0].startswith("\ufeff"):
        raise ErroExtracaoCSV("CSV: BOM não permitido")
    parsed = []
    for n, line in enumerate(s, 1):
        try:
            campos = next(csv.reader(
                io.StringIO(line), delimiter=";", quotechar='"',
                strict=True,
            ))
        except (csv.Error, StopIteration) as exc:
            raise ErroExtracaoCSV("CSV: linha sintaticamente inválida") from exc
        # Sem aspas multilinha ou normalização implícita de quebra.
        if any("\n" in x or "\r" in x for x in campos):
            raise ErroExtracaoCSV("CSV: quebra interna de campo proibida")
        if len(campos) != len(COLUNAS):
            raise ErroExtracaoCSV("CSV: contagem de campos divergente")
        if n == 1:
            if tuple(campos) != COLUNAS:
                raise ErroExtracaoCSV("CSV: cabeçalho não canônico")
            continue
        row = {}
        for k, v in zip(COLUNAS, campos):
            if not v and k not in OPCIONAIS:
                raise ErroExtracaoCSV("CSV: campo obrigatório ausente")
            row[k] = None if not v and k in OPCIONAIS else v
        row["raw_linha"] = n
        row["raw_linha_sha256"] = sha256(linhas[n-1]).hexdigest()
        parsed.append(row)
    return parsed


def verificar_extracao_csv_canonico(
    arquivo_original: bytes, snapshot_jsonl: bytes, *,
    manifesto: Mapping, as_of: str,
) -> dict:
    """Audita 1:1 todas as linhas; só aceita parser_id do contrato CSV v1.

    A verificação usa parser CSV do Python independente do produtor do
    JSONL, não de um conector oficial. Os SHA do manifesto continuam
    declarações: uma âncora externa precisa autenticá-los.
    """
    if (not isinstance(manifesto, Mapping) or
            manifesto.get("parser_id") != CSV_PARSER_ID or
            manifesto.get("parser_versao") != CSV_PARSER_VERSAO):
        raise ErroExtracaoCSV("parser CSV v1 não corresponde ao manifesto")
    prova = preparar_precos_com_artefatos(
        arquivo_original, snapshot_jsonl, manifesto=manifesto, as_of=as_of)
    fonte = _csv_linhas(arquivo_original)
    convertido = _lote_jsonl_conferido(snapshot_jsonl)
    if len(fonte) != len(convertido):
        raise ErroExtracaoCSV("CSV: omissão ou acréscimo de observações normalizadas")
    hashes = []
    for raw, norm in zip(fonte, convertido):
        if set(norm) != ALLOWED:
            raise ErroExtracaoCSV("CSV: campos normalizados extras ou ausentes")
        if type(norm["raw_linha"]) is not int:
            raise ErroExtracaoCSV("CSV: raw_linha deve ser inteiro")
        if norm != raw:
            raise ErroExtracaoCSV(
                "CSV: divergência de preço, identidade, posição ou conteúdo"
            )
        hashes.append(raw["raw_linha_sha256"])
    return {
        **prova,
        "status": "EXTRACAO_CSV_CANONICA_CONFERIDA_OFFLINE_NAO_HOMOLOGADA",
        "evidencia_extracao_csv": {
            "schema": CSV_PARSER_ID,
            "versao": CSV_PARSER_VERSAO,
            "registros_conferidos": len(fonte),
            "linhas_sha256": hashes,
            "totalidade_linhas_csv_verificada": True,
            "campos_textuais_csv_verificados": True,
            "parser_oficial_mercado_validado": False,
            "origem_arquivo_autenticada": False,
            "direitos_publicacao_verificados": False,
        },
        "publicavel": False, "probabilidades_calibradas": None,
    }
