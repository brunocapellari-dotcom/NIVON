import { Pool } from 'pg';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { createHash } from 'node:crypto';

const POOL = new Pool({connectionString:process.env.DATABASE_URL,max:2,connectionTimeoutMillis:10000});
const KEYS=createRemoteJWKSet(new URL('https://token.actions.githubusercontent.com/.well-known/jwks'));
const REPO='brunocapellari-dotcom/NIVON';
const REF_ALLOW=new Set(['refs/heads/feat/catalogo-noticias-agricolas-20261021','refs/heads/main']);
const SERIES={
 soja_paranagua:{product:'soja',location:'Paranaguá/PR',url:'https://www.cepea.org.br/br/indicador/soja.aspx'},
 soja_parana:{product:'soja',location:'Paraná',url:'https://www.cepea.org.br/br/indicador/soja.aspx'},
 milho_esalq_b3:{product:'milho',location:'Campinas/SP',url:'https://www.cepea.org.br/br/indicador/milho.aspx'}
};
const digest=s=>createHash('sha256').update(s).digest('hex');

async function authenticate(req){
 const h=req.headers.get('authorization')||'';
 if(!h.startsWith('Bearer ')||h.length>12000)throw new Error('MISSING_JWT');
 const {payload}=await jwtVerify(h.slice(7),KEYS,{issuer:'https://token.actions.githubusercontent.com',
   audience:'urn:nivon:cepea:ingest',clockTolerance:15});
 const wf=REPO+'/.github/workflows/cepea-neon-ingest.yml@'+payload.ref;
 if(payload.repository!==REPO||!REF_ALLOW.has(payload.ref)||payload.workflow_ref!==wf||
    !['push','workflow_dispatch','schedule'].includes(payload.event_name))throw new Error('WORKFLOW_DENIED');
 return payload;
}
function validate(r){
 const spec=SERIES[r?.serie_id];
 if(r?.fonte!=='CEPEA'||!spec||r.produto!==spec.product||r.praca!==spec.location||
    r.origem_url!==spec.url||r.unidade!=='BRL/sc60kg'||
    r.licenca!=='CC BY-NC 4.0'||r.qualidade!=='CANDIDATO_NAO_GRAVADO')throw new Error('INVALID_PROVENANCE');
 if(r.data_publicacao!==null||r.competencia!==r.data_referencia.slice(0,7)||
    !/^20\d{2}-\d{2}-\d{2}$/.test(r.data_referencia)||
    Number.isNaN(Date.parse(r.data_referencia+'T00:00:00Z'))||
    r.data_referencia>new Date().toISOString().slice(0,10))throw new Error('INVALID_REFERENCE_DATE');
 if(typeof r.valor!=='string'||! /^\d+(?:\.\d{1,6})?$/.test(r.valor)||
    !Number.isFinite(Number(r.valor))||Number(r.valor)<=0||Number(r.valor)>1000000)
    throw new Error('INVALID_PRICE');
 const t=Date.parse(r.data_coleta);
 if(!Number.isFinite(t)||Math.abs(Date.now()-t)>86400000)throw new Error('BAD_COLLECTION_TIME');
 return {series:r.serie_id,product:spec.product,location:spec.location,reference:r.data_referencia,
         collected:r.data_coleta,unit:r.unidade,price:r.valor,url:spec.url,
         key:digest(['CEPEA',r.serie_id,r.data_referencia,'BRL/sc60kg'].join('|')),
         version:digest(r.valor)};
}
async function store(rows,claims){
 const c=await POOL.connect();let inserted=0;
 try{
  await c.query('BEGIN');
  for(const r of rows){
    const res=await c.query(
     "INSERT INTO public.nivon_cepea_prices(series_id,product,location,unit,reference_date,collected_at,price_brl,source_url,source_key,version_hash) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(source_key,version_hash) DO NOTHING RETURNING id",
     [r.series,r.product,r.location,r.unit,r.reference,r.collected,r.price,r.url,r.key,r.version]);
    inserted+=res.rowCount;
  }
  const latest=rows.map(r=>r.reference).sort().at(-1);
  const age=Math.floor((Date.now()-Date.parse(latest+'T00:00:00Z'))/86400000);
  const status=age>4?'SOURCE_LAG':(inserted?'OK':'NO_UPDATE');
  const now=new Date().toISOString();
  await c.query(
   "INSERT INTO public.nivon_p0_source_checks(source,check_kind,status,latest_reference_on,inserted_rows,warning,provenance_uri,job_identifier) VALUES('CEPEA','PRIMARY_INDICATOR', $1,$2,$3,$4,$5,$6)",
   [status,latest,inserted,age>4?'Data CEPEA defasada: não promover como preço atual':null,rows[0].url,String(claims.run_id||'')]
  );
  await c.query(
   "UPDATE public.nivon_p0_sources SET ingest_state='ACTIVE', allow_automated_ingest=TRUE,last_checked_at=$1,last_success_at=$1,last_reference_on=$2,freshness_state=$3,updated_at=now() WHERE source='CEPEA'",
   [now,latest,status]
  );
  await c.query('COMMIT');
  return {status,received:rows.length,inserted,duplicates:rows.length-inserted,latest_reference:latest};
 }catch(e){await c.query('ROLLBACK');throw e}finally{c.release()}
}
async function registerFailure(product,claims){
 const spec=product==='MILHO'?SERIES.milho_esalq_b3:SERIES.soja_paranagua;
 const c=await POOL.connect();
 try{
   await c.query('BEGIN');
   await c.query(
     "INSERT INTO public.nivon_p0_source_checks(source,check_kind,status,inserted_rows,warning,provenance_uri,job_identifier) VALUES('CEPEA','PRIMARY_SOURCE_FAILURE','ERROR',0,$1,$2,$3)",
     ['Falha de execução do coletor CEPEA ('+product+'); preço anterior NÃO atualizado',spec.url,String(claims.run_id||'')]
   );
   await c.query(
     "UPDATE public.nivon_p0_sources SET last_checked_at=now(),freshness_state='COLLECTOR_ERROR',ingest_state='ACTIVE',updated_at=now() WHERE source='CEPEA'"
   );
   await c.query('COMMIT');
   return {status:'RECORDED',source:'CEPEA',product,canonical_quotes_inserted:0};
 }catch(e){await c.query('ROLLBACK');throw e}finally{c.release()}
}

export default {
 async fetch(req){
  const path=new URL(req.url).pathname;
  if(path==='/health'&&req.method==='GET')return Response.json({service:'NIVON-CEPEA',status:'DEPLOYED'});
  if(!['/ingest','/report-failure'].includes(path)||req.method!=='POST')return Response.json({error:'NOT_FOUND'},{status:404});
  let claims;try{claims=await authenticate(req)}catch(e){return Response.json({error:'OIDC_REJECTED'},{status:401})}
  if(path==='/report-failure'){
    try{
      const txt=await req.text();if(txt.length>2000)throw Error('SIZE');
      const body=JSON.parse(txt);
      if(body.source!=='CEPEA'||!['SOJA','MILHO'].includes(body.product)||body.event!=='WORKFLOW_FAILED')throw Error('BAD_REPORT');
      return Response.json(await registerFailure(body.product,claims));
    }catch(e){console.error('CEPEA source failure reporting error');return Response.json({error:'REPORT_REJECTED'},{status:422})}
  }
  let rows;
  try{
   const data=await req.text();
   if(data.length>70000)throw new Error('PAYLOAD_TOO_LARGE');
   const payload=JSON.parse(data);
   if(payload.source!=='CEPEA'||!Array.isArray(payload.rows)||payload.rows.length<1||payload.rows.length>50)
      throw new Error('INVALID_ROWS');
   rows=payload.rows.map(validate);
   const keys=rows.map(r=>r.series+'|'+r.reference);
   if(new Set(keys).size!==keys.length)throw new Error('DUPLICATE_QUOTE_IN_BATCH');
  }catch(e){return Response.json({error:'VALIDATION_FAILED'},{status:422})}
  try{return Response.json(await store(rows,claims))}
  catch(e){console.error('cepea-ingest-error',String(e?.code||e?.message||'UNKNOWN').slice(0,55));
   return Response.json({error:'PERSISTENCE_FAILED'},{status:503})}
 }
};
