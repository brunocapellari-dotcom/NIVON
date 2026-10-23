import {Pool} from 'pg';
import {createRemoteJWKSet,jwtVerify} from 'jose';
import {createHash} from 'node:crypto';
const POOL=new Pool({connectionString:process.env.DATABASE_URL,max:2,connectionTimeoutMillis:10000});
const KEYS=createRemoteJWKSet(new URL('https://token.actions.githubusercontent.com/.well-known/jwks'));
const REPO='brunocapellari-dotcom/NIVON';
const SOURCE_IDS={soja:'4',milho:'3'};
const sha=s=>createHash('sha256').update(s).digest('hex');
function check(r){
 if(!r||r.source!=='IMEA'||!SOURCE_IDS[r.chain]||!['PRECO','FRETE'].includes(r.indicator_kind)||
    r.reference_date!==null||r.status!=='PUBLICACAO_NAO_EQUIVALE_REFERENCIA')
   throw Error('SOURCE');
 const u=new URL(r.source_url);
 if(u.protocol!=='https:'||u.hostname!=='api1.imea.com.br'||u.pathname!=='/api/v2/mobile/cadeias/'+SOURCE_IDS[r.chain]+'/cotacoes'||u.search||u.username||u.password)throw Error('URL');
 for(const key of ['indicator_id','indicator','location','unit','value','published_at','source_key','version_hash'])
  if(typeof r[key]!=='string'||!r[key]||r[key].length>250)throw Error('SCHEMA');
 if(!/^\d{1,30}$/.test(r.indicator_id)||!/^\d+(?:\.\d+)?$/.test(r.value)||
   +r.value<=0||+r.value>1e9||!Number.isFinite(+r.value))throw Error('VALUE');
 if(r.crop_year!==null && (typeof r.crop_year!=='string'||! /^(?:\d{2}|20\d{2})\/\d{2}$/.test(r.crop_year)))throw Error('CROP');
 if(!/^[0-9a-f]{64}$/.test(r.source_key)||!/^[0-9a-f]{64}$/.test(r.version_hash))throw Error('HASH_FORMAT');
 const when=Date.parse(r.published_at);
 if(!Number.isFinite(when)||!/^20\d{2}-\d{2}-\d{2}T/.test(r.published_at)||when>Date.now()+86400000)throw Error('DATE');
 const identity=['IMEA',r.chain,r.indicator_kind,r.indicator_id,r.location,r.published_at,r.crop_year||'',r.unit].join('|');
 if(sha(identity)!==r.source_key||sha(r.value)!==r.version_hash)throw Error('HASH_MISMATCH');
 if(r.indicator_kind==='FRETE'&&!['r$/t','r$/ton','r$/tonelada'].includes(r.unit.toLowerCase()))throw Error('FREIGHT_UNIT');
 return r;
}
async function authorize(req){
 const h=req.headers.get('authorization')||'';
 if(!h.startsWith('Bearer ')||h.length>12000)throw Error('TOKEN');
 const {payload}=await jwtVerify(h.slice(7),KEYS,{issuer:'https://token.actions.githubusercontent.com',audience:'urn:nivon:imea:stage',clockTolerance:15});
 if(payload.repository!==REPO||!['refs/heads/main','refs/heads/feat/catalogo-noticias-agricolas-20261021'].includes(payload.ref)||
    payload.workflow_ref!==REPO+'/.github/workflows/imea-neon-stage.yml@'+payload.ref||
    !['push','workflow_dispatch','schedule'].includes(payload.event_name))throw Error('WORKFLOW');
 return payload;
}
async function store(rows,claim){
 const c=await POOL.connect();let inserted=0;
 try{
  await c.query('BEGIN');
  for(const r of rows){
   const x=await c.query(
    'INSERT INTO public.nivon_imea_prices_staging (chain,indicator_kind,indicator_id,indicator_name,location,unit,crop_year,price,published_at,reference_date,source_url,source_key,version_hash) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NULL,$10,$11,$12) ON CONFLICT(source_key,version_hash) DO NOTHING RETURNING id',
    [r.chain,r.indicator_kind,r.indicator_id,r.indicator,r.location,r.unit,r.crop_year,r.value,r.published_at,r.source_url,r.source_key,r.version_hash]
   );
   inserted+=x.rowCount;
  }
  await c.query("INSERT INTO public.nivon_p0_source_checks(source,check_kind,status,inserted_rows,warning,provenance_uri,job_identifier) VALUES('IMEA','OFFICIAL_STAGING',$1,$2,'Data publicada não equivale data de referência; estágio apenas, sem promoção a tendência.',$3,$4)",
   [inserted?'OK':'NO_UPDATE',inserted,rows[0].source_url,String(claim.run_id||'')]);
  await c.query('COMMIT');
  return {status:'STAGED',received:rows.length,inserted,duplicates:rows.length-inserted,canonical_quotes_inserted:0};
 }catch(e){await c.query('ROLLBACK');throw e}finally{c.release()}
}
export default {async fetch(req){
 const path=new URL(req.url).pathname;
 if(req.method==='GET'&&path==='/health')return Response.json({status:'READY',source:'IMEA'});
 if(req.method!=='POST'||path!=='/stage')return Response.json({error:'NOT_FOUND'},{status:404});
 let claim;try{claim=await authorize(req)}catch{return Response.json({error:'UNAUTHORIZED'},{status:401})}
 let rows;try{
  const txt=await req.text();
  if(txt.length>80000)throw Error('SIZE');
  const obj=JSON.parse(txt);
  if(obj.source!=='IMEA'||!Array.isArray(obj.rows)||obj.rows.length<1||obj.rows.length>80)throw Error('ROWS');
  rows=obj.rows.map(check);
  if(new Set(rows.map(x=>x.source_key+'|'+x.version_hash)).size!==rows.length)throw Error('DUPLICATES');
 }catch{return Response.json({error:'BAD_DATA'},{status:422})}
 try{return Response.json(await store(rows,claim))}
 catch(e){console.error('imea-stage',String(e?.code||e?.message||'error').slice(0,60));return Response.json({error:'PERSISTENCE_ERROR'},{status:503})}
}};
