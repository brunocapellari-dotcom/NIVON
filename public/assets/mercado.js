"use strict";
/* Valores econômicos de BCB/SGS somente: não derivar PTAX, não inventar preços. */
(function(){
  const keys=[
    ["ptax_usd_venda","mkt-usd-value","mkt-usd-meta","BRL/USD"],
    ["selic_diaria","mkt-selic-value","mkt-selic-meta","% ao dia"],
  ];
  const node=id=>document.getElementById(id);
  const number=(val,max)=>new Intl.NumberFormat("pt-BR",{
    minimumFractionDigits:2,maximumFractionDigits:max,
  }).format(val);
  let busy=false;
  async function loadMarket(){
    if(busy)return;
    busy=true;
    const status=node("mkt-status");
    if(!status){busy=false;return;}
    status.textContent="Consultando indicadores oficiais…";
    try{
      const res=await fetch("/api/mercado",{
        method:"GET",headers:{"Accept":"application/json"},
        cache:"no-store",signal:AbortSignal.timeout(9000)
      });
      const data=await res.json();
      if(!data||typeof data!=="object"||!data.series||typeof data.series!=="object"){
        throw Error("CONTRATO_MERCADO_AUSENTE");
      }
      for(const [key,valueId,metaId,unit] of keys){
        const serie=data.series[key];
        const value=node(valueId),meta=node(metaId);
        if(!value||!meta)continue;
        if(serie&&Number.isFinite(serie.value)&&serie.value>=0
           &&typeof serie.referencia==="string"
           &&/^20\d{2}-\d{2}-\d{2}$/.test(serie.referencia)
           &&serie.unit===unit
           &&["INFORMADO","SOURCE_LAG"].includes(serie.status)){
          value.textContent=number(serie.value,key==="selic_diaria"?6:4);
          meta.textContent=serie.referencia+" · "+unit+
            (serie.status==="SOURCE_LAG"?" · SOURCE_LAG ("+serie.idade_dias+" dias)":" · INFORMADO");
        }else{
          value.textContent="—";
          meta.textContent="FONTE_INDISPONIVEL · sem valor atual";
        }
      }
      status.textContent=data.status==="DISPONIVEL"
        ?"Leitura oficial realizada. Dados com referência individual; não equivalem à atualização do BigQuery."
        :data.status==="PARCIAL"
          ?"Consulta parcial: algumas séries estão indisponíveis."
          :"Fonte indisponível. Nenhum valor presumido.";
    }catch(_){
      for(const [,valueId,metaId] of keys){
        if(node(valueId))node(valueId).textContent="—";
        if(node(metaId))node(metaId).textContent="FONTE_INDISPONIVEL";
      }
      status.textContent="Falha na consulta de mercado. Nenhum valor foi estimado.";
    }finally{busy=false;}
  }
  if(document.readyState==="loading")
    document.addEventListener("DOMContentLoaded",()=>{
      loadMarket();
      node("refresh")?.addEventListener("click",loadMarket);
    });
  else{
    loadMarket();
    node("refresh")?.addEventListener("click",loadMarket);
  }
})();
