"""Restrição noturna da execução de agentes; sem cron nem API de relógio externa.

Somente iniciações de tarefas em America/Cuiaba de 20:00 a 06:00.
Reserva tempo para testes e integração antes do encerramento da janela.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = "America/Cuiaba"
START_HOUR = 20
END_HOUR = 6
VALID_ZONE = ZoneInfo(TIMEZONE)


def local_now(at=None):
    if at is None:
        return datetime.now(VALID_ZONE)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Horário deve incluir fuso")
    return at.astimezone(VALID_ZONE)


def window(at=None):
    """Return active status and next close/open in MT time."""
    current = local_now(at)
    start = current.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    end = current.replace(hour=END_HOUR, minute=0, second=0, microsecond=0)
    if current >= start:
        return {"active": True, "opens": start, "closes": end + timedelta(days=1)}
    if current < end:
        return {"active": True, "opens": start - timedelta(days=1), "closes": end}
    return {"active": False, "opens": start, "closes": end + timedelta(days=1)}


def minutes_left(at=None):
    current = local_now(at)
    state = window(current)
    if not state["active"]:
        return 0
    return max(0.0, (state["closes"] - current).total_seconds() / 60)


def may_begin(at=None, *, per_task_minutes=15):
    """Conservative margin for validation and local integration after CLI."""
    if not 2 <= per_task_minutes <= 60:
        raise ValueError("Tempo por tarefa inválido")
    reserve_minutes = per_task_minutes + 15
    return minutes_left(at) >= reserve_minutes


def status(at=None, *, per_task_minutes=15):
    current = local_now(at)
    state = window(current)
    return {
        "timezone": TIMEZONE,
        "local_time": current.isoformat(timespec="seconds"),
        "window": "20:00-06:00",
        "active": state["active"],
        "may_begin_task": may_begin(current, per_task_minutes=per_task_minutes),
        "next_open": state["opens"].isoformat(timespec="seconds"),
        "current_or_next_close": state["closes"].isoformat(timespec="seconds"),
    }
