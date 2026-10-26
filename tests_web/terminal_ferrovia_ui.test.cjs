"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const source=fs.readFileSync(path.join(__dirname,"../src/nivon/terminal_web.py"),"utf8");
const html=source.split('HTML = r"""')[1].split('"""')[0];
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1].replace("}carregar();","}");
function element(){return {textContent:"",hidden:true,children:[],style:{},
  classList:{add(){}},append(...items){this.children.push(...items);},
  replaceChildren(...items){this.children=items;}};}
function browser(data){
  const nodes=new Map();
  const document={getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},createElement:element};
  const response={ok:true,status:200,json:async()=>data};
  const context={document,Intl,fetch:async(url,opts)=>{
    assert.equal(url,"/api/v1/ferrovia");assert.equal(opts.cache,"no-store");return response;
  }};
  vm.createContext(context);vm.runInContext(script,context);
  return {context,nodes,response};
}
const fixture=lag=>({estado:"ANTT_SERIE_OBSERVADA_DECLARADA",tu_acumuladas:"0",registros_acumulados:1,
  ultima_competencia:"2026-03",ultima_coleta_utc:"2026-10-25T20:30:00+00:00",
  freshness:{estado:lag?"SOURCE_LAG":"DENTRO_DA_JANELA_DE_ALERTA"},
  serie:[{ano:2026,toneladas_uteis:"0",registros:1,ultima_competencia:"2026-03",arquivo_sha256:"a".repeat(64),parcial:true}]});

test("UI distingue coleta/competência, mostra SHA e não divide por zero",async()=>{
  const {context,nodes}=browser(fixture(false));await context.carregar();
  assert.match(html,/ANTT\/SIADE/);
  assert.equal(nodes.get("competencia").textContent,"2026-03");
  assert.match(nodes.get("atualizacao").textContent,/2026-10-25/);
  assert.equal(nodes.get("tu").textContent,"0");
  assert.equal(nodes.get("linhas").children[0].children[4].textContent,"a".repeat(64));
  assert.equal(nodes.get("chart").children[0].children[0].style.height,"0px");
  await context.carregar();
  assert.equal(nodes.get("linhas").children.length,1);
});
test("UI alerta fonte defasada apesar de coleta recente",async()=>{
  const {context,nodes}=browser(fixture(true));await context.carregar();
  assert.match(nodes.get("estado").textContent,/FONTE DEFASADA.*2026-03/);
  assert.match(nodes.get("estado").textContent,/Coleta recente não significa dado novo/);
  assert.equal(nodes.get("cards").hidden,false);
});
test("Falha após sucesso esconde dados antigos e não inventa zero",async()=>{
  const {context,nodes,response}=browser(fixture(false));await context.carregar();
  response.ok=false;response.status=503;await context.carregar();
  for(const name of ["cards","serie","tabela"])assert.equal(nodes.get(name).hidden,true);
  assert.equal(nodes.get("linhas").children.length,0);
  assert.match(nodes.get("estado").textContent,/DADOS INDISPONÍVEIS/);
});
