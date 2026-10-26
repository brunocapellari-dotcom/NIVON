"use strict";
/*
 * NIVON v1: observabilidade de GitHub Actions em repositório público.
 * Nunca confundir sucesso de workflow com produção, preço atualizado,
 * volume realizado, transferência efetiva ou dado validado no BigQuery.
 * API diretamente do navegador: sem backend, credenciais, tokens ou cobrança GCP.
 */
const REPO = "brunocapellari-dotcom/NIVON";
const ACTIONS_URL = "https://github.com/" + REPO + "/actions";
const API_URL = "https://api.github.com/repos/" + REPO + "/actions/runs?per_page=100";
const P0_WORKFLOWS=["cepea-neon-ingest.yml","imea-neon-stage.yml","conab-neon-ingest.yml"];
const P0_URLS=P0_WORKFLOWS.map(f=>"https://api.github.com/repos/"+REPO+"/actions/workflows/"+f+"/runs?branch=main&per_page=2");
const GROUPS = [
  {id:"cepea",name:"CEPEA • Preços físicos",area:"Mercados",detail:"Coleta primária de soja e milho; execução ≠ novo preço.",match:/CEPEA coleta primaria para Neon/i},
  {id:"imea",name:"IMEA • Mercado MT",area:"Mercados",detail:"Staging oficial; publicação não equivale à data de referência.",match:/IMEA - staging oficial Neon/i},
  {id:"conab",name:"CONAB • Safras e balanços",area:"Mercados",detail:"Edições, revisões e séries agrícolas verificadas.",match:/CONAB ingesta autenticada no Neon/i},
  {id:"ptax",name:"BCB • PTAX e câmbio",area:"Mercados",detail:"Coleta PTAX do Banco Central com rastreabilidade.",match:/PTAX direta Banco Central para BigQuery/i},
  {id:"agrocloud",name:"Fontes agrícolas • Google Cloud",area:"Mercados",detail:"Integração GCS/BigQuery com gates; execução pulada é bloqueio, não sucesso.",match:/CEPEA IMEA CONAB para Google Cloud/i},
  {id:"rail",name:"Ferrovias • ANTT",area:"Logística",detail:"Leitura da view SIADE; não comprova transbordo.",match:/Leitura ferroviaria BigQuery para o Painel/i},
  {id:"road",name:"Rodovias • ANTT",area:"Logística",detail:"Recortes RGI e MDF-e observados, sem soma entre modais.",match:/ANTT Rodovia RGI 2025 para Google Cloud/i},
  {id:"roadmon",name:"MDF-e • Monitor oficial",area:"Logística",detail:"Vigia da fonte oficial; monitoramento não é volume atualizado.",match:/Monitor oficial ANTT MDF-e/i},
  {id:"hydro",name:"Hidrovias • ANTAQ",area:"Logística",detail:"Recortes hidroviários: distinguir oficial e fonte secundária.",match:/Hidrovia secundaria 2025 no BigQuery/i},
  {id:"maritime",name:"Marítimo • Leitura BigQuery",area:"Marítimo",detail:"Revisões de line-up e PortWatch; não equivale a operação concluída.",match:/Readback Maritimo BigQuery no Painel/i},
  {id:"maritimestatus",name:"Marítimo • Radar de fontes",area:"Marítimo",detail:"Saúde de fontes marítimas; não é AIS/DUV confirmado.",match:/Vigia de fontes hidroviarias ANTAQ/i},
  {id:"gcp",name:"Google Cloud • Auditoria",area:"Infraestrutura",detail:"Metadados e contratos de tabelas; não comprova escrita no GCP.",match:/Auditoria GCP somente leitura/i}
];
const lookup = id => document.getElementById(id);
let allRuns = [];
let activeArea = "Todas";
let lastFetch = null;
const formatTime = iso => {
  if(!iso) return "Sem horário";
  const date = new Date(iso);
  if(!Number.isFinite(date.getTime())) return "Data não verificada";
  return new Intl.DateTimeFormat("pt-BR",{timeZone:"America/Cuiaba",day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(date);
};
function safeRunUrl(run){
  const url = String((run && run.html_url) || "");
  const re = /^https:\/\/github\.com\/brunocapellari-dotcom\/NIVON\/actions\/runs\/[0-9]+$/;
  return re.test(url)?url:ACTIONS_URL;
}
function classify(run){
  if(!run) return {key:"none",label:"Sem evidência"};
  if(run.status!=="completed") return {key:"running",label:"Executando"};
  if(run.conclusion==="success"){
    const age = (Date.now()-Date.parse(run.created_at))/86400000;
    if(Number.isFinite(age) && age>7) return {key:"skipped",label:"Sucesso antigo"};
    return {key:"success",label:"Concluído"};
  }
  if(run.conclusion==="failure" || run.conclusion==="timed_out" || run.conclusion==="action_required") return {key:"failure",label:"Falha / atenção"};
  if(run.conclusion==="cancelled" || run.conclusion==="skipped" || run.conclusion==="neutral") return {key:"skipped",label:"Não executado"};
  return {key:"running",label:"Pendente"};
}
function e(tag,cls,value){
  const node=document.createElement(tag);
  if(cls)node.className=cls;
  if(value!==undefined && value!==null)node.textContent=String(value);
  return node;
}
function latestFor(group){
  return allRuns.find(r=>typeof r.name==="string" && group.match.test(r.name));
}
function appendStatus(holder,status){
  const label=e("span","pill "+status.key,status.label);
  holder.appendChild(label);
}
function renderCards(){
  const holder=lookup("cards");
  holder.replaceChildren();
  const query=lookup("search").value.toLocaleLowerCase("pt-BR").trim();
  const groups=GROUPS.filter(g=>(activeArea==="Todas"||g.area===activeArea)
      && (g.name+" "+g.detail+" "+g.area).toLocaleLowerCase("pt-BR").includes(query));
  if(groups.length===0){holder.appendChild(e("div","empty","Nenhuma integração atende aos filtros."));return;}
  for(const group of groups){
    const run=latestFor(group),state=classify(run),card=e("article","source-card");
    const head=e("div","source-head");
    head.appendChild(e("span","source-category",group.area));
    appendStatus(head,state);
    card.appendChild(head);
    card.appendChild(e("h3","source-title",group.name));
    card.appendChild(e("p","source-note",group.detail));
    const bottom=e("div","source-footer");
    bottom.appendChild(e("span","source-time",run?"Execução: "+formatTime(run.created_at):"Sem registro nesta janela"));
    const link=e("a","source-link",run?"Ver prova ↗":"Ver ações ↗");
    link.href=safeRunUrl(run);link.target="_blank";link.rel="noopener noreferrer";
    bottom.appendChild(link);card.appendChild(bottom);holder.appendChild(card);
  }
}
function renderActivity(){
  const root=lookup("activity-rows");root.replaceChildren();
  const sources=GROUPS.map(group=>({group,run:latestFor(group)}))
    .filter(x=>x.run)
    .sort((a,b)=>new Date(b.run.created_at)-new Date(a.run.created_at)).slice(0,12);
  if(!sources.length){root.appendChild(e("p","empty","Sem evidência recente verificável."));return;}
  for(const {group,run} of sources){
    const row=e("div","activity-row");
    row.appendChild(e("span","item-name",group.name));
    row.appendChild(e("span","item-date",formatTime(run.created_at)));
    const status=e("span","");
    appendStatus(status,classify(run));row.appendChild(status);
    const link=e("a","text-link","Abrir ↗");
    link.href=safeRunUrl(run);link.target="_blank";link.rel="noopener noreferrer";
    row.appendChild(link);root.appendChild(row);
  }
}
function renderKpis(){
  const estados=GROUPS.map(g=>({run:latestFor(g)}));
  const found=estados.filter(x=>x.run);
  lookup("kpi-total").textContent=found.length+"/"+GROUPS.length;
  lookup("kpi-success").textContent=found.filter(x=>classify(x.run).key==="success").length;
  lookup("kpi-failed").textContent=found.filter(x=>classify(x.run).key==="failure").length;
  lookup("kpi-pending").textContent=estados.filter(x=>["skipped","none"].includes(classify(x.run).key)).length;
}
function clock(){
  lookup("clock").textContent=new Intl.DateTimeFormat("pt-BR",{
    timeZone:"America/Cuiaba",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"
  }).format(new Date())+" MT";
}
function render(){
  renderKpis();renderCards();renderActivity();
}
async function load(){
  const btn=lookup("refresh");
  btn.disabled=true;
  lookup("network-label").textContent="Conferindo execuções no GitHub…";
  lookup("network-dot").className="network-dot";
  try{
    const urls=[API_URL,...P0_URLS];
    const responses=await Promise.allSettled(urls.map(async url=>{
      const res=await fetch(url,{headers:{"Accept":"application/vnd.github+json"},
        cache:"no-store",signal:AbortSignal.timeout(12000)});
      if(!res.ok)throw new Error("GitHub retornou HTTP "+res.status);
      const data=await res.json();
      if(!data||!Array.isArray(data.workflow_runs))throw new Error("Resposta sem execuções");
      return data.workflow_runs;
    }));
    const available=responses.filter(r=>r.status==="fulfilled");
    if(!available.length)throw new Error("Fontes de execuções indisponíveis");
    const verified=available.flatMap(r=>r.value).filter(r=>r&&typeof r.name==="string"
      && r.repository&&r.repository.full_name===REPO
      && /^https:\/\/github\.com\/brunocapellari-dotcom\/NIVON\/actions\/runs\/[0-9]+$/.test(String(r.html_url||"")));
    if(!verified.length)throw new Error("Nenhuma evidência verificável");
    allRuns=[...new Map(verified.map(r=>[r.id,r])).values()]
      .sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
    lastFetch=new Date();
    const complete=available.length===urls.length;
    lookup("network-label").textContent=complete
      ?"Execuções GitHub verificadas — não equivalem a preços atualizados"
      :"Consulta parcial ("+available.length+"/"+urls.length+"); sem evidências não significa fonte saudável.";
    lookup("network-dot").className=complete?"network-dot good":"network-dot";
    lookup("updated-at").textContent="Consulta: "+formatTime(lastFetch.toISOString());
    render();
  }catch(err){
    lookup("network-label").textContent="Falha de acesso ao GitHub — não afirmar saúde dos pipelines.";
    lookup("network-dot").className="network-dot bad";
    lookup("updated-at").textContent="Verifique conectividade/limite de consultas.";
    // Não continuar mostrando status anterior como se fosse atual.
    allRuns=[];render();
    if(typeof console!=="undefined" && console.warn)console.warn("NIVON: telemetria indisponível",String(err));
  }finally{btn.disabled=false;}
}
function init(){
  clock();
  lookup("refresh").addEventListener("click",load);
  lookup("search").addEventListener("input",renderCards);
  for(const btn of document.querySelectorAll(".filter")){
    btn.addEventListener("click",()=>{
      activeArea=btn.dataset.area;
      for(const b of document.querySelectorAll(".filter")){
        const selected=b===btn;
        b.classList.toggle("active",selected);
        b.setAttribute("aria-pressed",String(selected));
      }
      renderCards();
    });
  }
  load();
  setInterval(clock,60000);
  // Limitar consultas públicas à API para evitar HTTP 403 por rate limit.
  setInterval(()=>{if(!document.hidden)load();},900000);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);
else init();
