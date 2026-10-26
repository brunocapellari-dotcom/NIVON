"use strict";
const byId = id => document.getElementById(id);
const text = (el,value) => { el.textContent = value == null ? "Não informado" : String(value); };
const element = (tag,cls,value) => {
  const n=document.createElement(tag);
  if(cls)n.className=cls;
  if(value!==undefined)text(n,value);
  return n;
};
function info(box,k,v){
  const row=element("div","rule");
  row.append(element("span","",k),element("span","",v));
  box.append(row);
}
const integer = n => typeof n==="number"&&Number.isFinite(n) ? new Intl.NumberFormat("pt-BR").format(n) : "Não disponível";
function renderRail(r){
  const target=byId("ferrovia");target.replaceChildren();
  if(!r){target.append(element("p","error","Fonte indisponível ou não validada."));return;}
  info(target,"Estado",r.estado);
  info(target,"Competência",r.competencia);
  info(target,"Linhas da view",integer(r.linhas_view));
  const polos=Array.isArray(r.polos)?r.polos:[];
  if(!polos.length){
    target.append(element("p","muted","Nenhuma observação neste recorte. Isso não representa volume zero."));
    return;
  }
  target.append(element("p","metriclabel","Polos identificados neste recorte (máximo 15)"));
  for(const p of polos){
    const id=p && p.polo && typeof p.polo.id==="string"?p.polo.id:"Polo não identificado";
    info(target,id,(p.toneladas_ferroviarias??"não informado")+" t (revisão atual)");
  }
}
function renderMaritime(r){
  const target=byId("maritimo");target.replaceChildren();
  if(!r){target.append(element("p","error","Fonte indisponível ou não validada."));return;}
  info(target,"Estado",r.estado);
  info(target,"Passagem",r.passagem);
  info(target,"Dias observados",integer(r.dias_distintos));
  info(target,"Revisões históricas",integer(r.revisoes_visiveis));
  const metric=element("div","metric",integer(r.transitos_ais_reportados));
  target.append(metric,element("p","metriclabel","Trânsitos AIS reportados no recorte (modelo FMI)"));
  info(target,"Volume estimado pelo modelo",r.volume_estimado_modelo_t==null?"Não disponível":r.volume_estimado_modelo_t+" t");
  target.append(element("p","muted",r.nota||"Não equivale a operação portuária concluída."));
}
byId("filtros").addEventListener("submit", async evt=>{
  evt.preventDefault();
  const button=byId("consultar"),status=byId("status");
  const token=byId("chave").value;
  if(token.length<24){text(status,"Informe uma credencial válida.");return;}
  button.disabled=true;
  text(status,"Consultando fontes autorizadas. Pode haver cobrança limitada no BigQuery.");
  const q=new URLSearchParams({mes:byId("mes").value,passagem:byId("passagem").value});
  try{
    const response=await fetch("/api/v1/resumo?"+q.toString(),{
      method:"GET",cache:"no-store",credentials:"same-origin",
      headers:{"Authorization":"Bearer "+token,"Accept":"application/json"},
    });
    const result=await response.json();
    if(!response.ok && !result.fontes){
      text(status,response.status===401?"Credencial inválida.":response.status===503?
        "Serviço ainda não autorizado ou fonte indisponível.":"Solicitação recusada.");
      renderRail(null);renderMaritime(null);return;
    }
    const data=result.fontes||{};
    renderRail(data.ferrovia);renderMaritime(data.maritimo);
    text(status, result.estado+" · "+result.consultas_reais_confirmadas+" fontes consultadas");
    text(byId("corte"),"Data/hora de corte (UTC): "+result.corte);
  }catch(e){
    text(status,"Não foi possível obter resposta. Nenhum valor foi presumido.");
    renderRail(null);renderMaritime(null);
  }finally{button.disabled=false;}
});
