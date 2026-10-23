"""Painel de integridade das rotinas P0 a partir de execuções GitHub Actions.

Frescor da rotina != frescor do dado. Nunca converte last_run em data de
cotação ou produção. As agendas são avaliadas no fuso de Mato Grosso.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import os

MT = ZoneInfo("America/Cuiaba")
REPO = "brunocapellari-dotcom/NIVON"
PLANS = {
    "CEPEA": {"workflow":"cepea-neon-ingest.yml", "scheduled_hours":(19, 19), "expected_runs":2},
    "IMEA": {"workflow":"imea-neon-stage.yml", "scheduled_hours":(10, 19), "expected_runs":2},
    "CONAB": {"workflow":"conab-neon-ingest.yml", "scheduled_hours":(13,), "expected_runs":1},
}


def parse_time(iso):
    if not isinstance(iso, str) or not iso:
        raise ValueError("timestamp absent")
    return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(timezone.utc)


def expected_slots(start, end, product):
    """Agenda UTC-4 em dias úteis; não tenta adivinhar feriados."""
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise ValueError("janela inválida")
    hours = (19,19) if product == "CEPEA" else (10,19) if product == "IMEA" else (13,)
    # CEPEA publica soja e milho às 19h e 19h45, com tolerância operacional.
    minutes = (0,45) if product == "CEPEA" else (0,0) if product == "IMEA" else (0,)
    now_mt = end.astimezone(MT)
    day = start.astimezone(MT).date()
    out = []
    while day <= now_mt.date():
        if day.weekday() < 5:
            for hour,minute in zip(hours,minutes):
                slot = datetime(day.year,day.month,day.day,hour,minute,tzinfo=MT).astimezone(timezone.utc)
                if start <= slot <= end:
                    out.append(slot)
        day += timedelta(days=1)
    return out


def assess(source, runs, *, now=None):
    """Uma falha posterior ao sucesso não fica mascarada por testes de push."""
    if source not in PLANS:
        raise ValueError("fonte fora de P0")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("agora sem timezone")
    completed = [r for r in runs if r.get("status") == "completed"]
    completed.sort(key=lambda r: r.get("created_at",""),reverse=True)
    latest = completed[0] if completed else None
    scheduled = [r for r in completed if r.get("event") == "schedule"]
    scheduled.sort(key=lambda r:r.get("created_at",""),reverse=True)
    last_schedule = scheduled[0] if scheduled else None
    latest_any_time = parse_time(latest["created_at"]) if latest else None
    age_hours = round((now-latest_any_time).total_seconds()/3600,1) if latest_any_time else None
    # Contagem só dos slots com graça de 90 min; não confundir ausência de cron
    # com ausência de cotação/publicação em feriados.
    slots = expected_slots(now-timedelta(days=5),now-timedelta(minutes=90),source)
    recent_scheduled = [r for r in scheduled if parse_time(r["created_at"])>=now-timedelta(days=5)]
    if latest and latest.get("conclusion") != "success":
        status = "EXECUTION_FAILURE"
    elif not latest:
        status = "NO_EXECUTIONS"
    elif latest_any_time < now-timedelta(days=4):
        status = "EXECUTION_LAG"
    elif slots and not recent_scheduled:
        # Até duas janelas seguidas podem ficar pendentes após a ativação.
        # Depois de 2 horários vencidos sem qualquer disparo schedule,
        # a ausência do cron é falha operacional, mesmo que push tenha passado.
        misses = expected_slots(latest_any_time,now-timedelta(minutes=90),source)
        status = "SCHEDULE_MISSING" if len(misses)>=2 else "SCHEDULE_NOT_OBSERVED"
    elif slots and recent_scheduled:
        # Verifica slots recentes, não aceita um único cron antigo como saúde eterna.
        most_recent_slot = slots[-1]
        last_scheduled_time = parse_time(recent_scheduled[0]["created_at"])
        if last_scheduled_time < most_recent_slot - timedelta(hours=2):
            status = "SCHEDULE_LAG"
        elif recent_scheduled[0].get("conclusion")!="success":
            status = "SCHEDULE_FAILURE"
        else:
            status = "RUN_OK_NO_DATA_FRESHNESS_ASSERTION"
    else:
        status = "RUN_OK_SCHEDULE_PENDING"
    return {
        "source":source,"workflow":PLANS[source]["workflow"],
        "status":status,"latest_run":latest.get("id") if latest else None,
        "last_result":latest.get("conclusion") if latest else None,
        "last_event":latest.get("event") if latest else None,
        "last_execution_at":latest["created_at"] if latest else None,
        "last_scheduled_execution_at":last_schedule["created_at"] if last_schedule else None,
        "hours_since_last_execution":age_hours,
        "data_freshness_evaluated":False,
    }


def fetch_runs(workflow,token):
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs?branch=main&per_page=40"
    request=Request(url,headers={
        "Accept":"application/vnd.github+json","User-Agent":"NIVON-P0-health",
        "Authorization":"Bearer "+token,"X-GitHub-Api-Version":"2022-11-28"})
    with urlopen(request,timeout=20) as response:
        obj=json.load(response)
    return obj.get("workflow_runs",[])


def render_markdown(states):
    lines=["## Monitor P0 — GitHub Actions",
           "A execução do coletor não garante a atualização do dado original.",
           "| Fonte | Estado técnico | Última execução | Último resultado |",
           "|---|---|---|---|"]
    for s in states:
        lines.append(f"| {s['source']} | {s['status']} | {s['last_execution_at'] or 'Não há'} | {s['last_result'] or 'Não há'} |")
    lines.append("Datas de preços/produção devem ser consultadas separadamente no Neon. Drive não é frescor.")
    return "\n".join(lines)+"\n"


def main():
    token=os.environ.get("GITHUB_TOKEN")
    if not token:raise SystemExit("GITHUB_TOKEN ausente")
    output=[]
    for name,plan in PLANS.items():
        output.append(assess(name,fetch_runs(plan["workflow"],token)))
    Path("status_p0.json").write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n")
    summary=render_markdown(output)
    path=os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path,"a",encoding="utf-8") as f:f.write(summary)
    print(summary)
    print("P0_STATUS="+json.dumps({row["source"]:row["status"] for row in output}))
    problems=[r["source"] for r in output if r["status"] in
       {"EXECUTION_FAILURE","NO_EXECUTIONS","EXECUTION_LAG","SCHEDULE_LAG","SCHEDULE_FAILURE","SCHEDULE_MISSING"}]
    if problems:
        raise SystemExit("P0_WORKFLOW_PROBLEMS="+",".join(problems))

if __name__=="__main__":
    main()
