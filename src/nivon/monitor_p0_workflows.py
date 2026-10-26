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
    # Pipelines Google Cloud: agenda derivada do próprio cron UTC do workflow.
    "MARITIMO_GCP": {"workflow":"maritimo-gcp-primeiro-lote.yml", "cron_utc":"17 */6 * * *"},
    "PTAX_GCP": {"workflow":"ptax-bcb-direto-gcp.yml", "cron_utc":"20 23 * * 1-5"},
    # Fechados por variáveis de aprovação: job pulado é gate, não saúde nem falha.
    "AGRO_GCP": {"workflow":"fontes-agro-gcp.yml", "cron_utc":"15 1 * * 2-6", "gated":True},
    "SGS11_GCP": {"workflow":"bcb-sgs11-gcp.yml", "cron_utc":"35 14 * * 1-5", "gated":True},
}
FAILURE_STATES = {"EXECUTION_FAILURE","NO_EXECUTIONS","EXECUTION_LAG","SCHEDULE_LAG",
                  "SCHEDULE_FAILURE","SCHEDULE_MISSING"}


def _cron_campo(campo, minimo, maximo):
    """Subconjunto de cron usado nos workflows: *, */n, a-b, listas e números."""
    valores = set()
    for parte in campo.split(","):
        passo = 1
        if "/" in parte:
            parte, texto_passo = parte.split("/", 1)
            passo = int(texto_passo)
            if passo < 1:
                raise ValueError("passo cron inválido")
        if parte == "*":
            inicio, fim = minimo, maximo
        elif "-" in parte:
            inicio, fim = (int(x) for x in parte.split("-", 1))
        else:
            inicio = fim = int(parte)
        if not minimo <= inicio <= fim <= maximo:
            raise ValueError("campo cron fora do intervalo")
        valores.update(range(inicio, fim + 1, passo))
    return valores


def cron_slots(cron, start, end):
    """Horários UTC de um cron de 5 campos com dia/mês livres, entre start e end."""
    partes = cron.split()
    if len(partes) != 5 or partes[2] != "*" or partes[3] != "*":
        raise ValueError("cron fora do subconjunto suportado")
    minutos = _cron_campo(partes[0], 0, 59)
    horas = _cron_campo(partes[1], 0, 23)
    # cron: 0=domingo; Python: 0=segunda.
    dias = {(d - 1) % 7 for d in _cron_campo(partes[4].replace("7", "0"), 0, 6)}
    inicio = start.astimezone(timezone.utc)
    fim = end.astimezone(timezone.utc)
    dia = inicio.date()
    out = []
    while dia <= fim.date():
        if dia.weekday() in dias:
            for hora in sorted(horas):
                for minuto in sorted(minutos):
                    slot = datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=timezone.utc)
                    if inicio <= slot <= fim:
                        out.append(slot)
        dia += timedelta(days=1)
    return out


def parse_time(iso):
    if not isinstance(iso, str) or not iso:
        raise ValueError("timestamp absent")
    return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(timezone.utc)


def expected_slots(start, end, product):
    """Agenda UTC-4 em dias úteis; não tenta adivinhar feriados."""
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise ValueError("janela inválida")
    cron = PLANS.get(product, {}).get("cron_utc")
    if cron:
        return cron_slots(cron, start, end)
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
    plan = PLANS[source]
    completed = [r for r in runs if r.get("status") == "completed"]
    if plan.get("gated"):
        ativos = [r for r in completed if r.get("conclusion") != "skipped"]
        if not ativos:
            pulados = sorted(completed, key=lambda r: r.get("created_at", ""), reverse=True)
            ultimo = pulados[0] if pulados else None
            return {
                "source":source,"workflow":plan["workflow"],"status":"GATED_NOT_ACTIVE",
                "latest_run":ultimo.get("id") if ultimo else None,
                "last_result":ultimo.get("conclusion") if ultimo else None,
                "last_event":ultimo.get("event") if ultimo else None,
                "last_execution_at":ultimo["created_at"] if ultimo else None,
                "last_scheduled_execution_at":None,
                "hours_since_last_execution":None,
                "data_freshness_evaluated":False,
            }
        # Depois da abertura do gate, um job pulado volta a ser ausência de execução.
        completed = ativos
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
        cutoff=now-timedelta(minutes=90)
        misses=expected_slots(latest_any_time,cutoff,source) if latest_any_time<=cutoff else []
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
    headers={"Accept":"application/vnd.github+json","User-Agent":"NIVON-P0-health",
             "X-GitHub-Api-Version":"2022-11-28"}
    if token:
        headers["Authorization"]="Bearer "+token
    request=Request(url,headers=headers)
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
    gated=[s["source"] for s in states if s["status"]=="GATED_NOT_ACTIVE"]
    if gated:
        lines.append("Gate de aprovação fechado (sem persistência ativa): "+", ".join(gated)+".")
    lines.append("Datas de preços/produção devem ser consultadas separadamente no Neon/BigQuery. Drive não é frescor.")
    return "\n".join(lines)+"\n"


def main():
    # Repositório público: sem token a API funciona com limite menor (uso local).
    token=os.environ.get("GITHUB_TOKEN")
    if not token and os.environ.get("GITHUB_ACTIONS")=="true":
        raise SystemExit("GITHUB_TOKEN ausente")
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
    problems=[r["source"] for r in output if r["status"] in FAILURE_STATES]
    if problems:
        raise SystemExit("P0_WORKFLOW_PROBLEMS="+",".join(problems))

if __name__=="__main__":
    main()
