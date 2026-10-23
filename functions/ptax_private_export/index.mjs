// NIVON / PTAX: exportacao privada e somente leitura para migracao auditavel.
// Esta API NAO executa carga Google Cloud e NUNCA e uma fonte publica de preços.
// JWT OIDC de um workflow GitHub permitido; consulta apenas tabela PTAX canonical.
import { Pool } from 'pg';
import { createRemoteJWKSet, jwtVerify } from 'jose';

const pool=new Pool({connectionString:process.env.DATABASE_URL,max:2,connectionTimeoutMillis:10000});
const jwks=createRemoteJWKSet(new URL('https://token.actions.githubusercontent.com/.well-known/jwks'));
const REPO='brunocapellari-dotcom/NIVON';
const AUDIENCE='urn:nivon:ptax:export:v1';
const WORKFLOW='.github/workflows/ptax-neon-private-export.yml';
const ALLOWED=new Set(['refs/heads/plan/gcp-data-platform-20261021','refs/heads/main']);
const MAX_LIMIT=150, MAX_ID=Number.MAX_SAFE_INTEGER;

function json(body,status=200){
  return new Response(JSON.stringify(body),{status,headers:{
    'content-type':'application/json; charset=utf-8',
    'cache-control':'no-store','x-content-type-options':'nosniff'
  }});
}
function strictInt(v,name,{zero=false,limit=MAX_ID}={}){
  if(typeof v!=='string'|| !/^(0|[1-9][0-9]*)$/.test(v)||v.length>16){
    throw new Error('INVALID_'+name);
  }
  const n=Number(v);
  if(!Number.isSafeInteger(n)||n>(limit)||(n===0&&!zero))throw new Error('INVALID_'+name);
  return n;
}
async function authorize(req){
  const auth=req.headers.get('authorization')||'';
  if(!auth.startsWith('Bearer ')||auth.length>12000)throw new Error('AUTH_HEADER');
  const {payload}=await jwtVerify(auth.slice(7),jwks,{
    issuer:'https://token.actions.githubusercontent.com',
    audience:AUDIENCE,
    clockTolerance:15,
  });
  if(payload.repository!==REPO || !ALLOWED.has(payload.ref) ||
    payload.workflow_ref!==REPO+'/'+WORKFLOW+'@'+payload.ref ||
    !['push','workflow_dispatch'].includes(payload.event_name)){
    throw new Error('WORKFLOW_NOT_AUTHORIZED');
  }
}
const FIELDS=`
 SELECT id::text AS id, currency::text AS currency,
 reference_date::text AS reference_date,
 quote_time_original, bulletin_type, buy_brl::text AS buy_brl,
 sell_brl::text AS sell_brl, unit, source, license,
 CASE WHEN published_at IS NULL THEN NULL ELSE
  to_char(published_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END AS published_at,
 to_char(first_collected_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS first_collected_at,
 to_char(last_verified_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS last_verified_at,
 observation_kind
 FROM public.nivon_ptax_quotes
`;
export default {
 async fetch(req){
  const url=new URL(req.url);
  if(req.method==='GET'&&url.pathname==='/health')
    return json({status:'READY',service:'NIVON_PTAX_PRIVATE_EXPORT',public_data:false});
  if(req.method!=='GET'||!['/checkpoint','/export'].includes(url.pathname))
    return json({error:'NOT_FOUND'},404);
  try{await authorize(req)}catch{return json({error:'UNAUTHORIZED'},401)}
  try{
    if(url.pathname==='/checkpoint'){
      if(url.search)return json({error:'BAD_PARAMETERS'},422);
      const result=await pool.query(
       'SELECT COALESCE(MAX(id),0)::text AS upper_id,COUNT(*)::int AS row_count FROM public.nivon_ptax_quotes'
      );
      return json({status:'CHECKPOINT',upper_id:result.rows[0].upper_id,
        row_count:result.rows[0].row_count,source:'NEON_PTAX',
        source_snapshot_transactional:false});
    }
    if([...url.searchParams.keys()].some(k=>!['after','upto','limit'].includes(k))||
      [...url.searchParams.keys()].some(k=>url.searchParams.getAll(k).length!==1)||
      !url.searchParams.has('upto'))return json({error:'BAD_PARAMETERS'},422);
    const after=strictInt(url.searchParams.get('after')??'0','AFTER',{zero:true});
    const upto=strictInt(url.searchParams.get('upto'),'UPTO');
    const limit=strictInt(url.searchParams.get('limit')??'100','LIMIT',{limit:MAX_LIMIT});
    if(after>upto)return json({error:'INVALID_RANGE'},422);
    const result=await pool.query(FIELDS+' WHERE id>$1 AND id<=$2 ORDER BY id ASC LIMIT $3',
     [after,upto,limit]);
    for(const r of result.rows){
      strictInt(r.id,'ROW_ID');
      if(!['USD','EUR'].includes(r.currency)||r.observation_kind!=='INFORMADO')
        throw new Error('INVALID_SOURCE_RECORD');
    }
    const rows=result.rows;
    const next=rows.length?rows[rows.length-1].id:String(after);
    return json({status:'OK',upper_id:String(upto),after_id:String(after),next_after_id:next,
       received:rows.length,has_more:rows.length===limit&&Number(next)<upto,rows});
  }catch(e){
   if(String(e?.message||'').startsWith('INVALID_'))
     return json({error:'BAD_PARAMETERS_OR_SOURCE'},422);
   console.error('ptax-private-export',String(e?.code||e?.name||'unknown').slice(0,35));
   return json({error:'SOURCE_READ_FAILED'},503);
  }
 }
};
