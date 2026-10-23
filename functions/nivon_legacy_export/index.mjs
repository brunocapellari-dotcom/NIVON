// Ponte temporaria apenas para extrair dados legados, sem escrita no Neon.
// GitHub OIDC com audiencia e workflow exatos; NAO publicar cargas nas Actions.
import {Pool} from 'pg';
import {createRemoteJWKSet,jwtVerify} from 'jose';

const pool=new Pool({connectionString:process.env.DATABASE_URL,max:2,connectionTimeoutMillis:10000});
const issuer='https://token.actions.githubusercontent.com';
const jwks=createRemoteJWKSet(new URL(issuer+'/.well-known/jwks'));
const repository='brunocapellari-dotcom/NIVON';
const workflow=repository+'/.github/workflows/nivon-gcp-migracao.yml@refs/heads/main';
const workflowPR=repository+'/.github/workflows/nivon-gcp-migracao.yml@refs/heads/feat/migracao-neon-para-gcp-20261023';
const aud='urn:nivon:legacy:export:v1';
const ALLOWED={
  imea:'public.nivon_imea_prices_staging',
  cepea:'public.nivon_cepea_prices',
  conab_safras:'public.nivon_conab_safras',
  conab_balancos:'public.nivon_conab_balancos',
  conab_series:'public.nivon_conab_series_historicas'
};
function reply(payload,code=200){
 return new Response(JSON.stringify(payload),{status:code,headers:{
  'content-type':'application/json; charset=utf-8',
  'cache-control':'no-store','x-content-type-options':'nosniff'
 }});
}
function digits(s,{min=0,max=Number.MAX_SAFE_INTEGER}={}){
 if(typeof s!=='string'|| !/^(0|[1-9][0-9]*)$/.test(s)||s.length>16)throw Error('INVALID_INTEGER');
 const n=Number(s);
 if(!Number.isSafeInteger(n)||n<min||n>max)throw Error('INTEGER_RANGE');
 return n;
}
async function auth(request){
 const bearer=request.headers.get('authorization')||'';
 if(!bearer.startsWith('Bearer ')||bearer.length>12000)throw Error('BEARER');
 const {payload}=await jwtVerify(bearer.slice(7),jwks,{
  issuer,audience:aud,clockTolerance:15
 });
 if(payload.repository!==repository ||
    ![workflow,workflowPR].includes(payload.workflow_ref) ||
    !['refs/heads/main','refs/heads/feat/migracao-neon-para-gcp-20261023'].includes(payload.ref) ||
    !['push','workflow_dispatch'].includes(payload.event_name) ||
    payload.workflow_ref.slice(payload.workflow_ref.lastIndexOf('@')+1)!==payload.ref)
  throw Error('WORKFLOW');
}
export default {async fetch(req){
 const url=new URL(req.url);
 if(req.method==='GET'&&url.pathname==='/health')
  return reply({status:'READY',service:'NIVON_LEGACY_READ_ONLY',records_exposed:false});
 if(req.method!=='GET'||!['/checkpoint','/export'].includes(url.pathname))
  return reply({error:'NOT_FOUND'},404);
 try{await auth(req)}catch{return reply({error:'UNAUTHORIZED'},401)}
 const requested=url.searchParams.get('dataset');
 const table=ALLOWED[requested];
 if(!table||url.searchParams.getAll('dataset').length!==1)
  return reply({error:'DATASET_NOT_ALLOWED'},422);
 try{
  if(url.pathname==='/checkpoint'){
   if([...url.searchParams.keys()].some(k=>k!=='dataset'))
    return reply({error:'BAD_PARAMETERS'},422);
   const result=await pool.query('SELECT COALESCE(MAX(id),0)::text AS upper_id,COUNT(*)::int AS count FROM '+table);
   return reply({status:'CHECKPOINT',dataset:requested,upper_id:result.rows[0].upper_id,
        count:result.rows[0].count,snapshot_is_transactional:false});
  }
  if([...url.searchParams.keys()].some(k=>!['dataset','after','upto','limit'].includes(k)) ||
    [...url.searchParams.keys()].some(k=>url.searchParams.getAll(k).length!==1) ||
    !url.searchParams.has('upto'))
   return reply({error:'BAD_PARAMETERS'},422);
  const after=digits(url.searchParams.get('after')??'0');
  const upto=digits(url.searchParams.get('upto'),{min:1});
  const limit=digits(url.searchParams.get('limit')??'80',{min:1,max:100});
  if(after>upto)return reply({error:'BAD_RANGE'},422);
  // The table name is a server-side constant, never a client-provided SQL identifier.
  const records=await pool.query(
    'SELECT t.id::text AS id,to_jsonb(t)::text AS payload_json FROM '+table+' t WHERE t.id>$1 AND t.id<=$2 ORDER BY t.id ASC LIMIT $3',
    [after,upto,limit]
  );
  const rows=records.rows.map(x=>({id:x.id,payload_json:x.payload_json}));
  return reply({status:'OK',dataset:requested,upper_id:String(upto),
      after_id:String(after),rows,received:rows.length,
      next_after_id:rows.length?rows[rows.length-1].id:String(after)});
 }catch(err){
  console.error('nivon-legacy',String(err?.code||err?.name||'error').slice(0,35));
  return reply({error:'LEGACY_READ_FAILED'},503);
 }
}};
