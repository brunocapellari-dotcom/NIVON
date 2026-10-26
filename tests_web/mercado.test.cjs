"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const {readFileSync}=require("node:fs");
const path=require("node:path");
const handler=require("../api/mercado.js");
const NOW=new Date("2026-10-25T18:00:00Z");
const payload=(data,valor)=>JSON.stringify([{data,valor}]);
const mock=(responses)=>{
  const calls=[];
  const fetcher=async(url,init)=>{
    calls.push({url,init});
    const k=url.includes(".sgs.1/")?1:11;
    const value=responses[k];
    if(value instanceof Error)throw value;
    return {ok:true,status:200,headers:{get:(n)=>n==="content-type"?"application/json; charset=utf-8":null},
      text:async()=>value};
  };
  return {calls,fetcher};
};

test("parser seleciona última referência e não interpola datas",()=>{
  const result=handler.parseLatest([
    {data:"22/10/2026",valor:"0,050788"},
    {data:"23/10/2026",valor:"0.051"},
  ],NOW);
  assert.equal(result.value,0.051);
  assert.equal(result.referencia,"2026-10-23");
  assert.equal(result.idade_dias,2);
  assert.equal(result.status,"INFORMADO");
});

test("parser rejeita data futura, invalida, numero textual e conjunto vazio",()=>{
  for(const val of [
    [{data:"26/10/2026",valor:"0.05"}],
    [{data:"31/02/2026",valor:"0.05"}],
    [{data:"22/10/2026",valor:"NaN"}],
    [{data:"22/10/2026",valor:"1e9"}],
    [],{},[{data:"22/10/2026",valor:3}]
  ])assert.throws(()=>handler.parseLatest(val,NOW));
});

test("fontes reais oficiais fixas, sem URL controlável externamente",async()=>{
  const api=mock({1:payload("23/10/2026","5,0377"),11:payload("23/10/2026","0,050788")});
  const data=await handler.collect(NOW,api.fetcher);
  assert.equal(data.status,"DISPONIVEL");
  assert.equal(data.series.ptax_usd_venda.value,5.0377);
  assert.equal(data.series.selic_diaria.value,0.050788);
  assert.equal(data.series.ptax_usd_venda.unit,"BRL/USD");
  assert.equal(data.series.selic_diaria.unit,"% ao dia");
  assert.equal(data.origem,"API_PUBLICA_BCB_SEM_PERSISTENCIA");
  assert.equal(data.nuvem_google_atualizada,false);
  assert.equal(api.calls.length,2);
  for(const call of api.calls){
    assert.match(call.url,/^https:\/\/api\.bcb\.gov\.br\/dados\/serie\/bcdata\.sgs\.(1|11)\/dados\/ultimos\/5\?formato=json$/);
    assert.equal(call.init.method,"GET");
    assert.equal(call.init.redirect,"error");
    assert.ok(call.init.signal);
  }
});

test("falha parcial reportada sem fabricar valores",async()=>{
  const api=mock({1:payload("23/10/2026","5.0377"),11:new Error("429")});
  const result=await handler.collect(NOW,api.fetcher);
  assert.equal(result.status,"PARCIAL");
  assert.equal(result.series.selic_diaria.value,null);
  assert.equal(result.series.selic_diaria.status,"FONTE_INDISPONIVEL");
  assert.equal(result.series.ptax_usd_venda.value,5.0377);
});

test("dado antigo marcado SOURCE_LAG, não tratado como atual",async()=>{
  const result=handler.parseLatest([{data:"01/10/2026",valor:"4.95"}],NOW);
  assert.equal(result.status,"SOURCE_LAG");
  assert.ok(result.idade_dias>5);
});

test("HTTP diferente de GET devolve 405 e não consulta rede",async()=>{
  const head={};
  const res={
    status(code){this.code=code;return this;},
    setHeader(key,val){head[key]=val;},
    json(x){this.payload=x;return this;}
  };
  await handler({method:"POST",query:{url:"https://evil.example"}},res);
  assert.equal(res.code,405);
  assert.equal(res.payload.status,"METODO_NAO_PERMITIDO");
  assert.equal(head.Allow,"GET");
});

test("terminal web não contém preços fixos e declara estágio das fontes",()=>{
  const html=readFileSync(path.join(__dirname,"..","index.html"),"utf8");
  assert.match(html,/\/api\/mercado/);
  assert.match(html,/Google Cloud/);
  assert.match(html,/Não disponível nesta versão/);
  assert.match(html,/SOURCE_LAG/);
  assert.match(html,/pt-BR/);
  assert.doesNotMatch(html,/0,050788|5,0377/);
  const config=JSON.parse(readFileSync(path.join(__dirname,"..","vercel.json"),"utf8"));
  assert.ok(config.functions["api/mercado.js"]);
  assert.match(JSON.stringify(config),/frame-ancestors 'none'/);
});
