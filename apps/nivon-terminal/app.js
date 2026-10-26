/* NIVON / Prévia pública. Somente metadados de execuções GitHub públicas. */
(function () {
  "use strict";
  const repository = "brunocapellari-dotcom/NIVON";
  const base = "https://api.github.com/repos/" + repository + "/actions/workflows/";
  const configs = [
    { label: "CEPEA", description: "Preços físicos soja e milho", workflow: "cepea-neon-ingest.yml" },
    { label: "IMEA", description: "Preços e comercialização", workflow: "imea-neon-stage.yml" },
    { label: "CONAB", description: "Safra, oferta e demanda", workflow: "conab-neon-ingest.yml" },
    { label: "BCB / PTAX", description: "Câmbio de referência", workflow: "ptax-bcb-direto-gcp.yml" },
    { label: "ANTT / GCP", description: "Carga e auditoria ferroviária", workflow: "nivon-antt-auditoria-historico-gcp.yml" }
  ];
  const container = document.getElementById("source-grid");
  const message = document.getElementById("source-meta");
  const refresh = document.getElementById("refresh");
  if (!container || !message || !refresh) return;
  let busy = false;

  function node(tag, className, content) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (content !== undefined) result.textContent = content;
    return result;
  }
  function dateValue(iso) {
    if (typeof iso !== "string") return "Data indisponível";
    const parsed = new Date(iso);
    if (!Number.isFinite(parsed.getTime())) return "Data indisponível";
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
      timeZone: "America/Cuiaba"
    }).format(parsed) + " (MT)";
  }
  function describe(run) {
    if (!run) return { state: "unknown", label: "Sem execução", detail: "Sem evidência na consulta" };
    if (run.status !== "completed") {
      return { state: "unknown", label: "Em andamento", detail: "Execução ainda não concluída" };
    }
    if (run.conclusion !== "success") {
      return { state: "bad", label: "Falha técnica", detail: "Resultado: " + String(run.conclusion || "não informado") };
    }
    if (run.event === "push" || run.event === "pull_request") {
      return { state: "ok", label: "CI aprovada", detail: "Teste de código; coleta real não confirmada" };
    }
    return { state: "ok", label: "Executado", detail: "Job concluído; frescor da fonte não comprovado" };
  }
  function render(config, run, error) {
    const card = node("article", "source");
    const top = node("div", "source-head");
    const title = node("strong", "", config.label);
    const status = describe(run);
    if (error) {
      status.state = "unknown";
      status.label = "Sem consulta";
      status.detail = "API indisponível ou limite de chamadas";
    }
    top.append(title, node("span", "state " + status.state, status.label));
    const desc = node("p", "", config.description);
    const caption = node("small", "", status.detail);
    const stamp = node("small", "", run ? "Última execução: " + dateValue(run.created_at) : "Sem data verificável");
    const link = node("a", "", "Ver execução no GitHub ↗");
    const safeRunId = run && Number.isSafeInteger(run.id) && run.id > 0 ? String(run.id) : null;
    link.href = safeRunId ?
      "https://github.com/" + repository + "/actions/runs/" + safeRunId :
      "https://github.com/" + repository + "/actions/workflows/" + config.workflow;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    card.append(top, desc, caption, stamp, link);
    return card;
  }
  async function loadSource(config) {
    const endpoint = base + encodeURIComponent(config.workflow) + "/runs?branch=main&per_page=10";
    const response = await fetch(endpoint, {
      method: "GET", headers: { Accept: "application/vnd.github+json" },
      cache: "no-store", credentials: "omit"
    });
    if (!response.ok) throw new Error("HTTP_" + response.status);
    const json = await response.json();
    if (!json || !Array.isArray(json.workflow_runs)) throw new Error("INVALID_RESPONSE");
    const runs = json.workflow_runs.filter(function (run) {
      return run && typeof run === "object" &&
        (run.event === "schedule" || run.event === "workflow_dispatch");
    });
    /* Se só houve CI, exibir explicitamente CI, nunca inferir coleta. */
    return runs.length ? runs[0] : json.workflow_runs[0] || null;
  }
  async function update() {
    if (busy) return;
    busy = true;
    refresh.disabled = true;
    refresh.textContent = "Consultando…";
    message.textContent = "Consultando execuções públicas. Sem acesso a credenciais ou dados privados.";
    const results = await Promise.all(configs.map(async function (config) {
      try {
        const run = await loadSource(config);
        return render(config, run, false);
      } catch (_) {
        return render(config, null, true);
      }
    }));
    container.replaceChildren(...results);
    message.textContent = "Consultado em " + dateValue(new Date().toISOString()) +
      ". Estado técnico de execução; não equivale a frescor ou homologação dos indicadores.";
    refresh.textContent = "Atualizar verificações ↻";
    refresh.disabled = false;
    busy = false;
  }
  refresh.addEventListener("click", update);
  update();
})();
