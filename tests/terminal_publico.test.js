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

test("Vercel publica somente assets publicos e impõe headers de proteção",()=>{
  const conf=JSON.parse(fs.readFileSync(path.join(root,"vercel.json"),"utf8"));
  assert.equal(conf.outputDirectory,"public");
  assert.equal(conf.framework,null);
  const headers=conf.headers.flatMap(r=>r.headers);
  const policy=headers.find(h=>h.key==="Content-Security-Policy");
  assert.match(policy.value,/default-src 'none'/);
  assert.match(policy.value,/connect-src https:\/\/api\.github\.com/);
  assert.match(headers.find(h=>h.key==="X-Robots-Tag").value,/noindex/);
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
  assert.doesNotMatch(html,/<iframe|<script(?![^>]*src="\/assets\/nivon\.js")/i);
  assert.doesNotMatch(html,/apikey|private_key|client_secret/i);
});
