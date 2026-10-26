"""Monitor read-only: workflow verde nao equivale a dado persistido.

Sem credenciais GCP e sem escrita, analisa apenas passos do GitHub Actions.
Um passo exitoso confirma execucao declarada, nao integridade BigQuery.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

REPO = "brunocapellari-dotcom/NIVON"
FONTES = {
    "ANTT_FERROVIA": "antt-ferrovia-gcp.yml",
    "PTAX_DIRETA": "ptax-bcb-direto-gcp.yml",
    "PTAX_PONTE": "ptax-neon-private-export.yml",
    "AGRO_GCP": "fontes-agro-gcp.yml",
}
PALAVRAS_PERSISTENCIA = ("MERGE", "BIGQUERY", "PERSISTIR", "CARREGAR")
PALAVRAS_CONFERENCIA = ("CONFERIR", "READBACK", "CONCILIAR", "VERIFICAR")
PALAVRAS_AUXILIARES = ("INSTALAR", "SONDA", "PRE-FLIGHT", "PREFLIGHT",
                       "VALIDAR", "PREPARAR", "ANTES", "CUSTO",
                       "CONEXAO", "CREDENCIAL", "AUTENTICAR")


def avaliar(runs, jobs):
    """Retorna estado conservador, limitado aos dados de execucao da API."""
    schedule = [r for r in runs if r.get("event") == "schedule"]
    schedule.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    if not schedule:
        return {"status": "AGENDA_NAO_EXECUTADA", "run_id": None,
                "persistencia_confirmada": False}
    ultima = schedule[0]
    rid = ultima.get("id")
    if ultima.get("status") != "completed":
        status = "EXECUCAO_EM_ANDAMENTO"
    elif ultima.get("conclusion") == "failure":
        status = "FALHA"
    elif any(j.get("conclusion") == "skipped" for j in jobs):
        status = "PULADO_POR_GATE"
    elif any(s.get("conclusion") == "skipped" and
             (any(k in str(s.get("name", "")).upper() for k in PALAVRAS_PERSISTENCIA)
              or "GCP" in str(s.get("name", "")).upper())
             for j in jobs for s in j.get("steps", [])):
        status = "PULADO_POR_GATE"
    elif ultima.get("conclusion") != "success":
        status = "EXECUCAO_NAO_CONCLUIDA"
    else:
        etapas = [str(s.get("name", "")).upper()
                  for j in jobs for s in j.get("steps", [])
                  if s.get("conclusion") == "success"]
        cargas = [s for s in etapas if any(k in s for k in PALAVRAS_PERSISTENCIA)
                  and not any(k in s for k in PALAVRAS_AUXILIARES)]
        leituras = [s for s in etapas if any(k in s for k in PALAVRAS_CONFERENCIA)
                    and "BIGQUERY" in s]
        if not cargas:
            status = "SUCESSO_SEM_ETAPA_DE_ESCRITA"
        elif not leituras:
            status = "ESCRITA_DECLARADA_SEM_READBACK"
        else:
            status = "READBACK_DECLARADO_NAO_INDEPENDENTE"
    return {"status": status, "run_id": rid,
            "persistencia_confirmada": False,
            "observacao": "Nao substitui query independente no BigQuery",
            "conclusion": ultima.get("conclusion")}


def _get(path, token):
    req = Request("https://api.github.com/repos/" + REPO + path,
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "User-Agent": "nivon-auditoria-c1",
                           "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def coletar(token):
    saida = {}
    for fonte, workflow in FONTES.items():
        runs = _get("/actions/workflows/" + workflow + "/runs?branch=main&per_page=12", token)
        amostra = [r for r in runs.get("workflow_runs", []) if r.get("event") == "schedule"]
        amostra.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        jobs = []
        if amostra:
            info = _get("/actions/runs/" + str(amostra[0]["id"]) + "/jobs?per_page=50", token)
            jobs = info.get("jobs", [])
        saida[fonte] = avaliar(amostra, jobs)
    return saida


def main():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN necessario para ler steps")
    estados = coletar(token)
    output = Path("status_persistencia_gcp.json")
    output.write_text(json.dumps(estados, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    linhas = ["## NIVON — auditoria de passos GCP (sem acesso a dados)",
              "| Fonte | Estado da execucao | ID |",
              "|---|---|---|"]
    for nome, item in estados.items():
        linhas.append("| " + nome + " | " + item["status"] + " | " +
                      str(item.get("run_id") or "ausente") + " |")
    linhas.append("Nenhuma linha desta auditoria certifica GCS/BigQuery. Confirmar dados em query independente.")
    resumo = "\n".join(linhas) + "\n"
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resumo)
    print(resumo)
    bloqueados = {"FALHA", "PULADO_POR_GATE", "SUCESSO_SEM_ETAPA_DE_ESCRITA",
                  "AGENDA_NAO_EXECUTADA", "EXECUCAO_NAO_CONCLUIDA"}
    if any(s["status"] in bloqueados for s in estados.values()):
        raise SystemExit("PERSISTENCIA_GCP_NAO_DEMONSTRADA")


if __name__ == "__main__":
    main()
