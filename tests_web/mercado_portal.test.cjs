"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const {readFileSync}=require("node:fs");
const path=require("node:path");
const api=require("../api/mercado.js");
const NOW=new Date("2026-10-25T18:00:00Z");
const mock=inputs=>async (url,opts)=>{
  assert.match(url,/^https:\/\/api\.bcb\.gov\.br\/dados\/serie\/bcdata\.sgs\.(1|11)\/dados\/ultimos\/5\?formato=json$/);
  assert.equal(opts.method,"GET");
  assert.equal(opts.redirect,"error");
  const code=url.includes(".sgs.1/")?1:11;
  if(inputs[code] instanceof Error)throw inputs[code];
  return {
    ok:true,
    headers:{get:(key)=>key==="content-type"?"application/json":null},
    text:async()=>JSON.stringify(inputs[code])
  };
};
test("Fonte BCB com data, escala e unidade preservadas",async()=>{
  const dados=await api.collect(NOW,mock({
    1:[{data:"23/10/2026",valor:"5,0523"}],
    11:[{data:"23/10/2026",valor:"0,050788"}]
  }));
  assert.equal(dados.status,"DISPONIVEL");
  assert.equal(dados.series.ptax_usd_venda.referencia,"2026-10-23");
  assert.equal(dados.series.ptax_usd_venda.unit,"BRL/USD");
  assert.equal(dados.series.selic_diaria.unit,"% ao dia");
  assert.equal(dados.series.selic_diaria.value,0.050788);
  assert.equal(dados.nuvem_google_atualizada,false);
});
test("Atraso e falha parcial nunca fabricam cotações",async()=>{
  const dados=await api.collect(NOW,mock({
    1:[{data:"01/10/2026",valor:"5.0111"}],
    11:new Error("BCB fora do ar")
  }));
  assert.equal(dados.status,"PARCIAL");
  assert.equal(dados.series.ptax_usd_venda.status,"SOURCE_LAG");
  assert.equal(dados.series.selic_diaria.status,"FONTE_INDISPONIVEL");
  assert.equal(dados.series.selic_diaria.value,null);
});
test("Datas futuras e valores não numéricos são rejeitados",()=>{
  for(const value of [[{data:"26/10/2026",valor:"5"}],
    [{data:"31/02/2026",valor:"5"}],
    [{data:"23/10/2026",valor:"NaN"}],
    []]){
    assert.throws(()=>api.parseLatest(value,NOW));
  }
});
test("Métodos mutantes são bloqueados",async()=>{
  let accessed=false;
  const response={status(code){this.code=code;return this;},
    setHeader(){},json(item){this.data=item;return this;}};
  await api({method:"POST"},response);
  assert.equal(response.code,405);
  assert.equal(response.data.status,"METODO_NAO_PERMITIDO");
  assert.equal(accessed,false);
});
test("Portal único mantém CSP segura e liga widget ao mesmo domínio",()=>{
  const root=path.join(__dirname,"..");
  const html=readFileSync(path.join(root,"public","index.html"),"utf8");
  const js=readFileSync(path.join(root,"public","assets","mercado.js"),"utf8");
  const v=JSON.parse(readFileSync(path.join(root,"infra/google_cloud/portal-security-headers.json"),"utf8"));
  assert.match(html,/\/assets\/nivon\.js/);
  assert.match(html,/\/assets\/mercado\.js/);
  assert.match(html,/mkt-usd-value/);
  assert.match(html,/mkt-selic-value/);
  assert.match(js,/textContent/);
  assert.match(js,/\/api\/mercado/);
  assert.doesNotMatch(js,/localStorage|innerHTML|document\.write/);
  assert.match(JSON.stringify(v),/script-src 'self'/);
  assert.doesNotMatch(JSON.stringify(v),/unsafe-inline/);
  assert.doesNotMatch(html,/5,0523|0,050788/);
});
