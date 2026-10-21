"""Confronto diário INMET×NASA POWER somente com janelas físicas idênticas.

Não infere relógio de observação pelo rótulo UTC do dia. Este é um wrapper
obrigatório antes do confronto descritivo de grades, que permanece sem
homologação de QC/metadata ou habilidade de previsão.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from re import fullmatch

from .confronto_climatico_qc import confronto_diario_inmet_power
from .inmet_horario_qc import ErroINMETHorario


def _t(txt, label):
    if not isinstance(txt, str) or "T" not in txt:
        raise ErroINMETHorario(label + ": instante ISO e timezone obrigatórios")
    try:
        when = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroINMETHorario(label + ": instante inválido") from exc
    if when.tzinfo is None or when.utcoffset() is None:
        raise ErroINMETHorario(label + ": fuso obrigatório")
    return when.astimezone(timezone.utc)


def _intervalos(rows, *, expected_days, origem, sha_key, sha_values):
    if not isinstance(rows, (list, tuple)) or len(rows) != len(expected_days):
        raise ErroINMETHorario(origem + ": intervalos físicos incompletos")
    mapped = {}
    for item in rows:
        if not isinstance(item, dict) or set(item) != {
                "data_utc", "inicio_utc", "fim_utc", sha_key, "evidencia_convecao"}:
            raise ErroINMETHorario(origem + ": metadados de intervalo incompletos")
        d = item["data_utc"]
        try:
            if not isinstance(d, str) or date.fromisoformat(d).isoformat() != d:
                raise ValueError("dia inválido")
        except ValueError as exc:
            raise ErroINMETHorario(origem + ": dia UTC inválido") from exc
        if d in mapped or d not in expected_days:
            raise ErroINMETHorario(origem + ": dia duplicado ou inesperado")
        start = _t(item["inicio_utc"], origem + " início")
        end = _t(item["fim_utc"], origem + " fim")
        if (end - start).total_seconds() != 24 * 3600:
            raise ErroINMETHorario(origem + ": intervalo não é 24 horas")
        sha = item[sha_key]
        if (not isinstance(sha, str) or not fullmatch(r"[a-f0-9]{64}", sha)
                or sha != sha_values[d]):
            raise ErroINMETHorario(origem + ": SHA não coincide com o dado")
        ev = item["evidencia_convecao"]
        if not isinstance(ev, str) or not 12 <= len(ev.strip()) <= 240:
            raise ErroINMETHorario(origem + ": documentação de convenção obrigatória")
        mapped[d] = (start, end, ev, sha)
    if set(mapped) != expected_days:
        raise ErroINMETHorario(origem + ": intervalo ausente")
    return mapped


def confrontar_chuva_janelas_equivalentes(
    *, diario_inmet, grade_nasa, intervalos_estacao,
    intervalos_grade, coordenadas_estacao, qc_externo,
    fonte_coordenadas, corte_coleta,
):
    """Só delega se todos os intervalos de 24h coincidirem exatamente.

    A entrada de janelas deve ser construída por fonte autorizada, com
    convenção física documentada e SHA dos bytes associados. A prova é
    autodeclarada neste contrato e precisa de auditoria institucional.
    """
    if not isinstance(diario_inmet, dict) or not isinstance(diario_inmet.get("dias"), list):
        raise ErroINMETHorario("série da estação incompleta")
    if not isinstance(grade_nasa, list):
        raise ErroINMETHorario("série NASA incompleta")
    station_days = [r.get("data_utc") for r in diario_inmet["dias"] if isinstance(r, dict)]
    grid_days = [r.get("data_utc") for r in grade_nasa if isinstance(r, dict)]
    if (len(station_days) != len(diario_inmet["dias"])
            or len(grid_days) != len(grade_nasa)
            or len(station_days) != len(set(station_days))
            or len(grid_days) != len(set(grid_days))
            or set(station_days) != set(grid_days)
            or not station_days):
        raise ErroINMETHorario("dias de grade e estação heterogêneos/duplicados")
    if not all(r.get("comparacao_grade_permitida") is True
               for r in diario_inmet["dias"]):
        raise ErroINMETHorario("estação não confirma cobertura horária e convenção")
    sha = diario_inmet.get("raw_sha256")
    station_intervals = _intervalos(
        intervalos_estacao, expected_days=set(station_days),
        origem="INMET", sha_key="raw_csv_sha256",
        sha_values={d: sha for d in station_days})
    grid_intervals = _intervalos(
        intervalos_grade, expected_days=set(grid_days),
        origem="NASA_POWER", sha_key="conteudo_sha256",
        sha_values={r["data_utc"]: r.get("conteudo_sha256") for r in grade_nasa})
    for day in station_days:
        if station_intervals[day][:2] != grid_intervals[day][:2]:
            raise ErroINMETHorario(
                "INMET e NASA POWER não compartilham o mesmo intervalo físico de 24h")
    result = confronto_diario_inmet_power(
        diario_inmet=diario_inmet, grade_nasa=grade_nasa,
        coordenadas_estacao=coordenadas_estacao, qc_externo=qc_externo,
        fonte_coordenadas=fonte_coordenadas, corte_coleta=corte_coleta)
    return {
        **result,
        "janelas_fisicas_verificadas": len(station_days),
        "janelas_temporalmente_equivalentes": True,
        "evidencias_intervalo_auditadas_externamente": False,
        "homologado": False,
        "skill_preditiva_comprovada": False,
        "aviso": "Exatidão temporal contratual não atesta prova externa nem igualdade espacial estação/grade.",
    }
