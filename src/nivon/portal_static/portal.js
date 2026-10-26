"use strict";
const byId = (id) => document.getElementById(id);
const sections = ["mercado", "logistica", "maritimo", "clima"];
function node(tag, cls, value) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (value !== undefined && value !== null) n.textContent = String(value);
  return n;
}
function clear() {
  for (const id of sections) byId(id).replaceChildren(node("p", "empty", "Sem dados homologados para este módulo. Não foi atribuído valor zero."));
}
function formatValue(value) {
  const s = String(value);
  if (!/^\d+(\.\d+)?$/.test(s)) return "—";
  const n = Number(s);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("pt-BR", {maximumFractionDigits:2}).format(n);
}
function addItem(item) {
  if (!item || item.publicavel !== false || !sections.includes(item.grupo)) return;
  const root = byId(item.grupo);
  const first = root.querySelector(".empty");
  if (first) first.remove();
  const metric = node("article", "metric");
  metric.append(node("span", "label", item.titulo));
  const v = node("strong", "value", formatValue(item.valor) + " ");
  v.append(node("span", "unit", item.unidade));
  metric.append(v);
  metric.append(node("span", "meta", item.fonte + " · " + item.referencia + " · " + item.natureza));
  metric.append(node("p", "caveat", item.ressalva));
  root.append(metric);
}
async function refresh() {
  clear();
  byId("status").textContent = "Consultando snapshot";
  try {
    const res = await fetch("/api/v1/painel", {cache:"no-store", credentials:"same-origin"});
    if (!res.ok) throw new Error("Fonte indisponível");
    const data = await res.json();
    if (data.modo !== "INTERNO_SHADOW" || data.publicavel !== false || data.go_live_publico !== false)
      throw new Error("Contrato de publicação incompatível");
    for (const it of data.indicadores || []) addItem(it);
    byId("fontes").textContent = String((data.fontes_consultadas || []).length) + " fontes consultadas";
    byId("gerado").textContent = new Date(data.gerado_em).toLocaleString("pt-BR", {dateStyle:"short",timeStyle:"short"});
    const stale = data.frescor_snapshot !== "ATUAL";
    byId("frescor").textContent = stale ? "Snapshot defasado — revisão necessária" : "Snapshot interno gerado há menos de 24h";
    byId("status").textContent = stale ? "Snapshot defasado" : "Monitoramento interno ativo";
    const warning = (data.avisos || []).join(" ");
    byId("aviso").textContent = "DADOS NÃO HOMOLOGADOS PARA PUBLICAÇÃO EXTERNA. " + (warning || "Indicadores restritos à revisão interna e com ressalvas por fonte.");
  } catch (_) {
    byId("status").textContent = "Sem snapshot válido";
    byId("frescor").textContent = "Dados não disponíveis; nenhuma observação presumida";
    byId("gerado").textContent = "Sem dados disponíveis";
    byId("fontes").textContent = "0 fontes consultadas";
    byId("aviso").textContent = "SEM DADOS VERIFICÁVEIS. Portal acessível, mas ainda sem leitura operacional autorizada.";
  }
}
byId("atualizar").addEventListener("click", refresh);
refresh();
setInterval(refresh, 300000);
