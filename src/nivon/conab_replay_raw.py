"""Replay executável RAW->observações para intercâmbio CSV sintético da CONAB.

Contrato de LABORATÓRIO, NÃO layout oficial CONAB. Não aceita XLS/XLSX/PDF,
não solicita URL, não consulta rede, não registra direitos e não migra.
Somente prova que ESTE parser determinístico produziu os campos do CSV
efetivamente lido; não atesta que o CSV teve origem na CONAB.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .conab_agrobr import ErroProgresso, normalizar_progresso
from .conciliacao_progresso_stores import (
    ErroConciliacaoConab, _CHAVE, _normalizar_registro, _timestamp, _url,
)
from .verificador_bytes_origem import conferir_bytes_origem, ErroBytesOrigem

PARSER_ID = "NIVON_INTERCAMBIO_CSV_TESTE_V1"
CAMPOS_CSV = (
    "cultura", "safra", "operacao", "uf", "semana_atual",
    "pct_ano_anterior", "pct_semana_anterior", "pct_semana_atual",
    "pct_media_5_anos", "revisado", "n_estados", "cobertura_area_pct",
)
_PERCENTUAIS = frozenset(("pct_ano_anterior", "pct_semana_anterior",
                           "pct_semana_atual", "pct_media_5_anos",
                           "cobertura_area_pct"))
_FRACTION = re.compile(r"(?:0|1)(?:\.\d{1,6})?\Z")
_MAX_BYTES = 2_000_000
_MAX_ROWS = 5000


class ErroReplayConab(ValueError):
    pass


def _numero(texto: str, *, campo: str):
    if texto == "" and campo != "pct_semana_atual":
        return None
    if not isinstance(texto, str) or not _FRACTION.fullmatch(texto):
        raise ErroReplayConab(f"fração CSV inválida: {campo}")
    num = Decimal(texto)
    if num > 1:
        raise ErroReplayConab(f"percentual fora da fração: {campo}")
    return float(num)


def _extrair_csv(payload: bytes):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= _MAX_BYTES:
        raise ErroReplayConab("CSV sintético vazio, não bytes ou maior que 2 MB")
    if b"\x00" in payload:
        raise ErroReplayConab("CSV contém bytes binários")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroReplayConab("CSV precisa ser UTF-8") from exc
    stream = io.StringIO(content, newline="")
    try:
        reader = csv.reader(stream, dialect="excel", strict=True)
        header = next(reader, [])
        if tuple(header) != CAMPOS_CSV:
            raise ErroReplayConab("cabeçalho CSV de intercâmbio não corresponde ao contrato")
        results = []
        for values in reader:
            if not values or (len(values) == 1 and not values[0].strip()):
                raise ErroReplayConab("linha CSV vazia não permitida")
            if len(values) != len(CAMPOS_CSV):
                raise ErroReplayConab("número de colunas CSV inválido")
            if len(results) >= _MAX_ROWS:
                raise ErroReplayConab("CSV excede limite de 5000 linhas")
            row = dict(zip(CAMPOS_CSV, values))
            for field in ("cultura", "safra", "operacao", "uf", "semana_atual"):
                if not row[field] or row[field] != row[field].strip():
                    raise ErroReplayConab("chave textual vazia ou com espaços marginais")
            for field in _PERCENTUAIS:
                row[field] = _numero(row[field], campo=field)
            if row["revisado"] not in ("", "true", "false"):
                raise ErroReplayConab("revisado CSV deve ser true, false ou vazio")
            row["revisado"] = (
                None if row["revisado"] == "" else row["revisado"] == "true"
            )
            states = row["n_estados"]
            if states and (not states.isascii() or not states.isdecimal()
                           or str(int(states)) != states or not 1 <= int(states) <= 27):
                raise ErroReplayConab("quantidade de estados CSV inválida")
            row["n_estados"] = int(states) if states else None
            if row["uf"] == "MEDIA_ESTADOS":
                if row["n_estados"] is None:
                    raise ErroReplayConab("MEDIA_ESTADOS exige cobertura declarada")
            elif row["n_estados"] is not None or row["cobertura_area_pct"] is not None:
                raise ErroReplayConab("cobertura de estados indevida para UF")
            results.append(row)
    except (csv.Error, StopIteration) as exc:
        raise ErroReplayConab("CSV malformado") from exc
    if not results:
        raise ErroReplayConab("CSV sem observações")
    return results


def reexecutar_csv_conab(payload: bytes, *, sha256_origem: str,
                         url_origem: str, coletado_em: str,
                         publicado_em: str | None) -> dict:
    """Lê efetivamente os bytes e produz mapa semântico verificável.

    Data de publicação e URL são insumos externos e NÃO extraídos do CSV.
    A versão de parser é uma ID fixa e o SHA de código é informativo,
    não assinatura/autenticidade de distribuição.
    """
    try:
        conferir_bytes_origem(payload=payload, sha256_informado=sha256_origem,
                              tamanho_informado=len(payload), mime="text/csv")
        _url(url_origem)
        coleta = _timestamp(coletado_em)
        pub = _timestamp(publicado_em) if publicado_em is not None else None
        if pub is not None and pub > coleta:
            raise ErroReplayConab("publicação posterior à coleta")
        raw_rows = _extrair_csv(payload)
        normalizados = normalizar_progresso(
            raw_rows, fonte_url=url_origem, coletado_em=coleta,
            publicado_em=pub.isoformat() if pub is not None else None,
        )
        semantic = {}
        for r in normalizados:
            clean = dict(r)
            clean.pop("coleta")
            key, serial, _ = _normalizar_registro(json.dumps(
                clean, sort_keys=True, ensure_ascii=False, allow_nan=False))
            if key in semantic:
                raise ErroReplayConab("chave de observação repetida")
            semantic[key] = serial
    except (ErroProgresso, ErroConciliacaoConab, ErroBytesOrigem) as exc:
        raise ErroReplayConab("CSV/observação não cumpre contrato de replay") from exc
    # Não serializar resultados para o relatório de auditoria; o chamador
    # pode cotejar o mapa, sem divulgar percentuais no resumo.
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "parser_id": PARSER_ID,
        "parser_codigo_sha256": code_hash,
        "raw_sha256": sha256_origem,
        "observacoes": len(semantic),
        "mapa_semantico": semantic,
        "origem_conab_comprovada": False,
        "formato_oficial_conab_homologado": False,
        "direitos_de_uso_verificados": False,
        "publicacao_extraida_do_arquivo": False,
        "migracao_permitida": False,
    }
