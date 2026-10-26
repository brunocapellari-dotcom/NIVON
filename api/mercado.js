"use strict";
/* NIVON: leitura de duas séries públicas BCB; sem credenciais ou persistência.
   Não substitui o pipeline canônico do Google Cloud. */
const SERIES = Object.freeze([
  {key:"ptax_usd_venda",code:1,label:"Dólar de referência · venda",unit:"BRL/USD"},
  {key:"selic_diaria",code:11,label:"Selic efetiva diária",unit:"% ao dia"}
]);
const MAX_BODY=12000;

function parseLatest(raw, now=new Date()) {
  if (!Array.isArray(raw) || raw.length<1 || raw.length>20) throw Error("FORMATO_SERIE_INVALIDO");
  const entries=raw.map(x=>{
    if (!x || typeof x!=="object" || Array.isArray(x) ||
        typeof x.data!=="string" || typeof x.valor!=="string") throw Error("VALOR_SERIE_INVALIDO");
    const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(x.data);
    if (!m) throw Error("DATA_SERIE_INVALIDA");
    const year=Number(m[3]),month=Number(m[2]),day=Number(m[1]);
    const stamp=Date.UTC(year,month-1,day), check=new Date(stamp);
    if (check.getUTCFullYear()!==year || check.getUTCMonth()+1!==month ||
        check.getUTCDate()!==day || stamp>now.getTime()) throw Error("DATA_SERIE_INVALIDA");
    if (!/^\d{1,5}(?:[,.]\d{1,10})?$/.test(x.valor)) throw Error("DECIMAL_SERIE_INVALIDO");
    const value=Number(x.valor.replace(",","."));
    if (!Number.isFinite(value) || value<0) throw Error("DECIMAL_SERIE_INVALIDO");
    return {referencia:m[3]+"-"+m[2]+"-"+m[1],value,time:stamp};
  });
  entries.sort((a,b)=>b.time-a.time);
  const latest=entries[0];
  const ageDays=Math.floor((Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate())-latest.time)/86400000);
  return {value:latest.value,referencia:latest.referencia,idade_dias:ageDays,
    status:ageDays>5?"SOURCE_LAG":"INFORMADO"};
}
async function fetchSerie(series,now=new Date(),request=fetch) {
  const url="https://api.bcb.gov.br/dados/serie/bcdata.sgs."+
    series.code+"/dados/ultimos/5?formato=json";
  const response=await request(url,{method:"GET",redirect:"error",
    headers:{"Accept":"application/json"},signal:AbortSignal.timeout(6000)});
  if (!response.ok || Number(response.headers?.get?.("content-length")||0)>MAX_BODY) {
    throw Error("BCB_HTTP_INDISPONIVEL");
  }
  const type=String(response.headers?.get?.("content-type")||"");
  if (!type.toLowerCase().includes("json")) throw Error("BCB_CONTEUDO_NAO_JSON");
  const body=await response.text();
  if (body.length>MAX_BODY || !body.trimStart().startsWith("[")) throw Error("BCB_CONTRATO_INESPERADO");
  const data=parseLatest(JSON.parse(body),now);
  if ((series.key==="selic_diaria" && data.value>10) ||
      (series.key==="ptax_usd_venda" && data.value>100)) throw Error("BCB_VALOR_FORA_DA_ESCALA");
  const slug=series.code===11?"11-taxa-de-juros---selic":
    "1-taxa-de-cambio---livre---dolar-americano-venda---diario";
  return {key:series.key,label:series.label,code:series.code,unit:series.unit,
    ...data,fonte:"Banco Central do Brasil (SGS)",
    fonte_url:"https://dadosabertos.bcb.gov.br/dataset/"+slug};
}
async function collect(now=new Date(),request=fetch) {
  const results=await Promise.allSettled(SERIES.map(s=>fetchSerie(s,now,request)));
  const series={};
  results.forEach((entry,i)=>{
    const item=SERIES[i];
    series[item.key]=entry.status==="fulfilled"?entry.value:{
      key:item.key,label:item.label,code:item.code,unit:item.unit,
      status:"FONTE_INDISPONIVEL",value:null,referencia:null,
      fonte:"Banco Central do Brasil (SGS)"};
  });
  const available=results.filter(x=>x.status==="fulfilled").length;
  return {versao:"nivon.mercado.publico.v1",
    status:available===SERIES.length?"DISPONIVEL":available?"PARCIAL":"INDISPONIVEL",
    consultado_em:now.toISOString(),leitura_somente:true,
    origem:"API_PUBLICA_BCB_SEM_PERSISTENCIA",nuvem_google_atualizada:false,series};
}
async function handler(req,res) {
  res.setHeader("Content-Type","application/json; charset=utf-8");
  res.setHeader("Cache-Control","public, s-maxage=600, stale-while-revalidate=60");
  res.setHeader("X-Content-Type-Options","nosniff");
  if (req.method!=="GET") {
    res.setHeader("Allow","GET");
    return res.status(405).json({status:"METODO_NAO_PERMITIDO"});
  }
  try {
    const data=await collect();
    return res.status(data.status==="INDISPONIVEL"?503:200).json(data);
  } catch (_) {
    return res.status(503).json({status:"INDISPONIVEL",series:{},leitura_somente:true});
  }
}
module.exports=handler;
module.exports.parseLatest=parseLatest;
module.exports.fetchSerie=fetchSerie;
module.exports.collect=collect;
