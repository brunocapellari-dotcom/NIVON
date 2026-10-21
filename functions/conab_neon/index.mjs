import { Pool } from 'pg';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { createHash } from 'node:crypto';
const POOL = new Pool({connectionString:process.env.DATABASE_URL,max:2,connectionTimeoutMillis:10000});
const KEYS=createRemoteJWKSet(new URL('https://token.actions.githubusercontent.com/.well-known/jwks'));
const REPO='brunocapellari-dotcom/NIVON';
const REF='refs/heads/feat/catalogo-noticias-agricolas-20261021';
const WF=REPO+'/.github/workflows/conab-neon-ingest.yml@'+REF;
const hash=s=>createHash('md5').update(s,'utf8').digest('hex');
const error=(code,message)=>Response.json({status:message},{status:code});
function validDate(s){return typeof s==='string' && /^20\d{2}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s+'T00:00:00Z'))}
function metric(v,name){
  if(v===null)return null;
  if(typeof v!=='string'||! /^\d+(?:\.\d+)?$/.test(v)||!Number.isFinite(Number(v))||Number(v)>1e10)throw new Error('INVALID_'+name);
  return v;
}
function validate(o){
  const m=o?.metric;
  if(o?.source!=='CONAB'||o?.origin_kind!=='agrobr.conab.safras'||!m||m.fonte!=='CONAB'||!['soja','milho'].includes(m.produto)||m.uf!=='MT')throw new Error('SOURCE');
  if(!/^20\d{2}\/\d{2}$/.test(m.safra)||m.competencia!==m.safra||!Number.isInteger(m.levantamento)||m.levantamento<1||m.levantamento>12)throw new Error('SCOPE');
  if(!validDate(m.data_publicacao)||m.data_publicacao>new Date().toISOString().slice(0,10))throw new Error('DATE');
  if(o.publication_date!==m.data_publicacao||o.publication_safra!==m.safra||Number(o.publication_survey)!==m.levantamento)throw new Error('RELEASE_MISMATCH');
  if(typeof o.publication_url!=='string'||!o.publication_url.startsWith('https://www.gov.br/conab/')||! /\.xlsx?$/.test(o.publication_url))throw new Error('ORIGIN_URL');
  if(typeof o.parser_version!=='string'||!o.parser_version.startsWith('agrobr-2.0.0-schema-'))throw new Error('VERSION');
  if(m.data_referencia!==null||m.area_colhida_mil_ha!==null||m.natureza!=='PROJETADO')throw new Error('SEMANTICS');
  const a=metric(m.area_plantada_mil_ha,'AREA'),y=metric(m.produtividade_kg_ha,'YIELD'),p=metric(m.producao_mil_t,'PRODUCTION');
  if(a===null&&y===null&&p===null)throw new Error('NO_METRICS');
  const stamp=Date.parse(m.data_coleta);
  if(!Number.isFinite(stamp)||Math.abs(Date.now()-stamp)>86400000)throw new Error('COLLECTION_TIME');
  return {product:m.produto,uf:'MT',year:m.safra,survey:m.levantamento,published:m.data_publicacao,collected:m.data_coleta,
    area:a,yieldKg:y,prod:p,url:o.publication_url,parser:o.parser_version,
    source_key:hash(['CONAB',m.produto,'MT',m.safra,m.levantamento,m.data_publicacao].join('|')),
    version_hash:hash([a??'',y??'',p??''].join('|'))};
}
async function authenticate(req){
  const header=req.headers.get('authorization')||'';
  if(!header.startsWith('Bearer ')||header.length>12000)throw new Error('MISSING_TOKEN');
  const {payload}=await jwtVerify(header.slice(7),KEYS,{issuer:'https://token.actions.githubusercontent.com',audience:'urn:nivon:conab:ingest',clockTolerance:15});
  const whitelisted=new Set([REF,'refs/heads/main']);
  const expected=REPO+'/.github/workflows/conab-neon-ingest.yml@'+payload.ref;
  if(payload.repository!==REPO||!whitelisted.has(payload.ref)||payload.workflow_ref!==expected||!['push','workflow_dispatch','schedule'].includes(payload.event_name))throw new Error('BAD_WORKFLOW');
  return payload;
}
async function store(rows,claims){
  const c=await POOL.connect();let inserted=0;
  try{
    await c.query('BEGIN');
    for(const r of rows){
      const q=await c.query("INSERT INTO public.nivon_conab_safras (product,uf,crop_year,survey_number,published_on,reference_date,collected_at,competence,area_mil_ha,yield_kg_ha,production_mil_t,source_name,source_uri,parser_version,epistemic_type,origin_kind,source_key,version_hash,quality_status) VALUES($1,$2,$3,$4,$5,NULL,$6,$3,$7,$8,$9,'CONAB',$10,$11,'PROJETADO','agrobr.conab.safras',$12,$13,'VALIDADO') ON CONFLICT(source_key,version_hash) DO NOTHING RETURNING id",
        [r.product,r.uf,r.year,r.survey,r.published,r.collected,r.area,r.yieldKg,r.prod,r.url,r.parser,r.source_key,r.version_hash]);
      inserted+=q.rowCount;
      await c.query("INSERT INTO public.nivon_conab_ingestions (source_name,dataset,product,uf,crop_year,survey_number,collection_started_at,collection_finished_at,status,rows_received,rows_validated,rows_inserted,source_uri,error_code) VALUES('CONAB','safras',$1,$2,$3,$4,$5,now(),'SUCCESS',1,1,$6,$7,NULL)",[r.product,r.uf,r.year,r.survey,r.collected,q.rowCount,r.url]);
    }
    await c.query('COMMIT');
    return {status:'OK',received:rows.length,inserted,duplicates:rows.length-inserted,run_id:String(claims.run_id||'')};
  }catch(e){await c.query('ROLLBACK');throw e}finally{c.release()}
}
export default {
 async fetch(req){
   const path=new URL(req.url).pathname;
   if(req.method==='GET'&&path==='/health')return Response.json({service:'NIVON-CONAB',status:'DEPLOYED'});
   if(req.method!=='POST'||path!=='/ingest')return error(404,'NOT_FOUND');
   let claims;try{claims=await authenticate(req)}catch(e){return error(401,'OIDC_REJECTED')}
   let rows;try{
     const t=await req.text();
     if(t.length>18000)throw new Error('SIZE');
     const body=JSON.parse(t);
     if(!Array.isArray(body.rows)||body.rows.length<1||body.rows.length>2)throw new Error('ROWS');
     rows=body.rows.map(validate);
   }catch(e){return error(422,'BAD_CONAB_PAYLOAD')}
   try{return Response.json(await store(rows,claims))}
   catch(e){console.error('conab-ingest-failure',String(e?.code||e?.message||'UNKNOWN').slice(0,60));return error(503,'PERSISTENCE_ERROR')}
 }
};