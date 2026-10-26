"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root=path.join(__dirname,"..");
const js=fs.readFileSync(path.join(root,"public/assets/nivon.js"),"utf8");
const document={readyState:"loading",addEventListener:()=>{}};
const ctx={document};
vm.createContext(ctx);
vm.runInContext(js+"\nglobalThis.NIVON_TEST={classify,safeRunUrl,GROUPS};",ctx);
const {classify,safeRunUrl,GROUPS}=ctx.NIVON_TEST;

test("Cloud Run inclui frontend e utiliza mesma origem para backend",()=>{
  const docker=fs.readFileSync(path.join(root,"infra/google_cloud/Dockerfile.terminal"),"utf8");
  const service=fs.readFileSync(path.join(root,"src/nivon/terminal_web.py"),"utf8");
  assert.match(docker,/COPY public \.\/public/);
  assert.match(service,/\/api\/mercado/);
  assert.match(service,/\/painel/);
  assert.match(service,/Content-Security-Policy/);
  assert.doesNotMatch(docker,/vercel/i);
});
test("fonte externa limitada ao repositório público NIVON",()=>{
  assert.match(js,/https:\/\/api\.github\.com\/repos\/|const REPO = "brunocapellari-dotcom\/NIVON"/);
  assert.doesNotMatch(js,/localStorage|sessionStorage|document\.cookie|eval\(/);
  assert.doesNotMatch(js,/NEXT_PUBLIC_|GOOGLE_APPLICATION_CREDENTIALS|Authorization\s*:/);
});
test("cards cobrem todas as frentes reais sem confundir dados e workflow",()=>{
  assert.ok(GROUPS.length>=11);
  const labels=GROUPS.map(g=>g.id);
  assert.equal(new Set(labels).size,labels.length);
  assert.ok(GROUPS.find(g=>g.id==="agrocloud").match.test("NIVON - CEPEA IMEA CONAB para Google Cloud"));
  assert.ok(GROUPS.find(g=>g.id==="rail").match.test("NIVON - Leitura ferroviaria BigQuery para o Painel"));
  assert.ok(GROUPS.find(g=>g.id==="imea").match.test("NIVON IMEA - staging oficial Neon"));
});
test("não anuncia sucesso quando job foi pulado ou falhou",()=>{
  assert.equal(classify({status:"completed",conclusion:"skipped"}).key,"skipped");
  assert.equal(classify({status:"completed",conclusion:"failure"}).key,"failure");
  assert.equal(classify({status:"in_progress"}).key,"running");
  assert.equal(classify(null).key,"none");
});
test("URL de execução rejeita hosts arbitrários ou URLs inventadas",()=>{
  const valid="https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40253995907";
  assert.equal(safeRunUrl({html_url:valid}),valid);
  for(const bad of ["http://github.com/brunocapellari-dotcom/NIVON/actions/runs/1",
                    "https://evil.example.com/steal",
                    "javascript:alert(1)",
                    "https://github.com/other/NIVON/actions/runs/1"]){
    assert.equal(safeRunUrl({html_url:bad}),
      "https://github.com/brunocapellari-dotcom/NIVON/actions");
  }
});
test("página não embute scripts externos, dados fictícios nem chaves",()=>{
  const html=fs.readFileSync(path.join(root,"public/index.html"),"utf8");
  assert.match(html,/src="\/assets\/nivon\.js"/);
  assert.match(html,/execução bem-sucedida não confirma dado novo/i);
  assert.doesNotMatch(html,/<iframe|<script(?![^>]*src="\/assets\/(?:nivon|mercado)\.js")/i);
  assert.doesNotMatch(html,/apikey|private_key|client_secret/i);
});
