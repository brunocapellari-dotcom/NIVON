// NIVON PTAX official collector. Branch-bound Neon Function; DATABASE_URL is injected by Neon.
// No secrets, real prices, or licensed third-party data are committed to GitHub.
import { Pool } from "pg";
const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 2, connectionTimeoutMillis: 10000, idleTimeoutMillis: 10000 });
const HOST = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/";
const START = "2020-01-01"; // historical ingestion starts with a bounded, auditable horizon
const SOURCE = "Banco Central do Brasil / PTAX";
const CURRENCIES = ["USD", "EUR"];
const MS_DAY = 86400000;
const ISO = (ms) => new Date(ms).toISOString().slice(0, 10);
const plusDays = (iso, days) => ISO(Date.parse(iso + "T00:00:00Z") + days * MS_DAY);
const brazilToday = () => {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: "America/Sao_Paulo", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
  const get = (s) => p.find(x=>x.type===s).value;
  return get("year")+"-"+get("month")+"-"+get("day");
};
function ptaxUrl(currency, start, end) {
  if (!CURRENCIES.includes(currency) || !/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end) || start > end) throw new Error("INVALID_WINDOW");
  const fmt = s => s.slice(5,7) + "-" + s.slice(8,10) + "-" + s.slice(0,4);
  const params = new URLSearchParams({"@dataInicial": "'"+fmt(start)+"'", "@dataFinalCotacao": "'"+fmt(end)+"'", "$format":"json", "$top":"5000"});
  if (currency==="USD") return HOST+"CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?"+params;
  params.set("@moeda", "'EUR'");
  return HOST+"CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?"+params;
}
async function download(currency,start,end) {
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),15000);
  try {
    const resp = await fetch(ptaxUrl(currency,start,end), {headers:{"Accept":"application/json"},signal:controller.signal,redirect:"error"});
    if(!resp.ok) throw new Error("BCB_HTTP_"+resp.status);
    const text = await resp.text();
    if(text.length > 4_000_000) throw new Error("BCB_TOO_LARGE");
    const data = JSON.parse(text);
    if(!data || !Array.isArray(data.value) || data["@odata.nextLink"] || data["odata.nextLink"] || data.value.length>=5000) throw new Error("BCB_PARTIAL_RESPONSE");
    if(data.value.length > 500) throw new Error("BCB_WINDOW_TOO_LARGE");
    return data.value.map(r=>{
      const time = r?.dataHoraCotacao;
      const kind = currency==="USD" ? "COTACAO_DOLAR_DIARIA" : r?.tipoBoletim;
      const buy = Number(r?.cotacaoCompra), sell=Number(r?.cotacaoVenda);
      if(typeof time!=="string" || !/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}/.test(time) || !kind || !Number.isFinite(buy) || !Number.isFinite(sell) || buy<=0 || sell<=0) throw new Error("BCB_BAD_RECORD");
      const ref=time.slice(0,10);
      if(ref<start || ref>end) throw new Error("BCB_DATE_OUTSIDE_WINDOW");
      return [currency,ref,time,kind,String(buy),String(sell),"BRL/"+currency,"INFORMADO"];
    });
  } finally {clearTimeout(timer)}
}
async function writeWindow(currency,start,end,mode) {
  const rows = await download(currency,start,end);
  const conn = await pool.connect();
  let inserted=0;
  try {
    await conn.query("BEGIN");
    for(let offset=0;offset<rows.length;offset+=60) {
      const part=rows.slice(offset,offset+60);
      const params=part.flat(),values=part.map((r,i)=>"("+r.map((_,j)=>"$"+(i*8+j+1)).join(",")+")").join(",");
      const sql="INSERT INTO public.nivon_ptax_quotes (currency,reference_date,quote_time_original,bulletin_type,buy_brl,sell_brl,unit,observation_kind) VALUES "+values+" ON CONFLICT DO NOTHING";
      inserted+=(await conn.query(sql,params)).rowCount;
    }
    await conn.query("INSERT INTO public.nivon_ptax_checkpoints(currency,window_start,window_end,status,fetched,last_completed_at) VALUES($1,$2,$3,$4,$5,now()) ON CONFLICT(currency,window_start,window_end) DO UPDATE SET status=excluded.status,fetched=excluded.fetched,last_completed_at=now()",[currency,start,end,rows.length?"SUCCESS":"EMPTY",rows.length]);
    await conn.query("INSERT INTO public.nivon_ptax_runs(job_type,currency,window_start,window_end,finished_at,status,fetched,inserted) VALUES($1,$2,$3,$4,now(),$5,$6,$7)",[mode,currency,start,end,rows.length?"SUCCESS":"EMPTY",rows.length,inserted]);
    await conn.query("COMMIT");
    return {currency,mode,start,end,received:rows.length,inserted};
  } catch (e) {await conn.query("ROLLBACK");throw e} finally {conn.release()}
}
async function nextHistory(currency,day) {
  const rs=await pool.query("SELECT window_start::text as start,window_end::text as end FROM public.nivon_ptax_checkpoints WHERE currency=$1 AND window_start>=$2::date ORDER BY window_start ASC",[currency,START]);
  const done=new Set(rs.rows.map(x=>x.start+"|"+x.end));
  for(let start=START;start<=day;start=plusDays(start,31)){
    const end=plusDays(start,30)>day?day:plusDays(start,30);
    if(!done.has(start+"|"+end))return [start,end];
  }
  return null;
}
async function runTask() {
  const conn=await pool.connect();
  let locked=false;
  try {
    locked=(await conn.query("SELECT pg_try_advisory_lock(240618) AS ok")).rows[0].ok;
    if(!locked)return {status:"ALREADY_RUNNING"};
    const last=await conn.query("SELECT max(started_at) AS last FROM public.nivon_ptax_runs WHERE status IN ('SUCCESS','EMPTY') AND job_type='DAILY'");
    if(last.rows[0].last && Date.now()-new Date(last.rows[0].last).getTime()<20*3600*1000) return {status:"ALREADY_CHECKED_RECENTLY"};
    const end=brazilToday(),begin=plusDays(end,-10),out=[];
    for(const currency of CURRENCIES){
      try {out.push(await writeWindow(currency,begin,end,"DAILY"))}
      catch(e){
        await pool.query("INSERT INTO public.nivon_ptax_runs(job_type,currency,window_start,window_end,finished_at,status,error_class) VALUES('DAILY',$1,$2,$3,now(),'ERROR',$4)",[currency,begin,end,String(e?.message||"UNKNOWN").slice(0,90)]);
        throw e;
      }
    }
    for(const currency of CURRENCIES) {
      const window=await nextHistory(currency,end);
      if(window) {
        try {out.push(await writeWindow(currency,window[0],window[1],"BACKFILL"))}
        catch(e) {
          await pool.query("INSERT INTO public.nivon_ptax_runs(job_type,currency,window_start,window_end,finished_at,status,error_class) VALUES('BACKFILL',$1,$2,$3,now(),'ERROR',$4)",[currency,...window,String(e?.message||"UNKNOWN").slice(0,90)]);
          throw e;
        }
      }
    }
    return {status:"OK",windows:out};
  } finally {if(locked)await conn.query("SELECT pg_advisory_unlock(240618)");conn.release()}
}
export default {
  async fetch(req) {
    if(req.method==="GET" && new URL(req.url).pathname==="/health")return Response.json({service:"NIVON-PTAX",state:"deployed",current_time_utc:new Date().toISOString()});
    // Neon documented trigger marker. Public requests without marker are rejected;
    // marker is not a cryptographic signature. DB lock + 20h guard reduces abuse.
    if(req.method!=="POST" || !req.headers.get("x-neon-trigger-invocation-id"))return Response.json({error:"FORBIDDEN"}, {status:403});
    try {return Response.json(await runTask())}
    catch(e){console.error("ptax-trigger-failure",String(e?.message||"UNKNOWN").slice(0,80));return Response.json({error:"COLLECTION_FAILED"},{status:503})}
  }
};
