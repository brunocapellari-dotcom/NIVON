"use strict";
const element=id=>document.getElementById(id);
const numeric=value=>value==null?"Sem dado":Number.isFinite(Number(value))?new Intl.NumberFormat("pt-BR",{maximumFractionDigits:0}).format(Number(value)):"Indisponível";
const text=(node,tag,value)=>{const child=document.createElement(tag);child.textContent=String(value==null?"Sem dado":value);node.appendChild(child)};
const tableRow=(target,values)=>{const row=document.createElement("tr");values.forEach(value=>text(row,"td",value));target.appendChild(row)};
document.querySelectorAll(".nav").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll(".nav,.tab").forEach(node=>node.classList.remove("active"));button.classList.add("active");element(button.dataset.id).classList.add("active")}));
async function update(){element("status").textContent="Consultando…";element("error").classList.add("hidden");element("refresh").disabled=true;
try{const response=await fetch("/api/v1/painel",{credentials:"same-origin",cache:"no-store"});if(!response.ok)throw Error("OFF");const data=await response.json();
if(data.estado!=="HISTORICO_EM_HOMOLOGACAO"||data.publicavel!==false||data.ano_referencia!==2025||!Array.isArray(data.rodovia_rgi_fluxos_top16)||!Array.isArray(data.polos))throw Error("CONTRATO");
element("ton").textContent=numeric(data.escopo_top16_rodoviario_toneladas);element("flows").textContent=numeric(data.rodovia_rgi_fluxos_top16.length);element("hubs").textContent=numeric(data.polos.length);element("asof").textContent=data.consulta_em_utc||"Indisponível";
for(const id of ["road","rail","notes","sources"])element(id).replaceChildren();
data.rodovia_rgi_fluxos_top16.forEach(row=>tableRow(element("road"),[(row.origem_rgi||"—")+" / "+(row.origem_uf||""),(row.destino_rgi||"—")+" / "+(row.destino_uf||""),numeric(row.toneladas_top16)+" t"]));
data.polos.forEach(row=>tableRow(element("rail"),[row.nome_polo,row.uf,row.ferrovia_origem_ton_2025==null?"Sem dado":numeric(row.ferrovia_origem_ton_2025)+" t",row.ferrovia_escopo==="ANTT_SIADE_ESTACAO_ORIGEM"?"Estação de origem":"Fora do recorte"]));
(data.avisos||[]).forEach(v=>text(element("notes"),"li",v));(data.fontes||[]).forEach(v=>text(element("sources"),"li",(v.fonte||"Fonte")+" · "+(v.modal||"Sem modal")+" · "+(v.granularidade||v.estado||"Sem detalhe")));
element("status").textContent="Recorte histórico consultado";
}catch(e){element("status").textContent="Leitura não disponível";element("error").classList.remove("hidden");["ton","flows","hubs","asof"].forEach(id=>element(id).textContent="—");["road","rail","notes","sources"].forEach(id=>element(id).replaceChildren())}finally{element("refresh").disabled=false}}
element("refresh").addEventListener("click",update);update();
