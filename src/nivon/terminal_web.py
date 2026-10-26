"""NIVON: terminal interno HTTP, apenas leitura do BigQuery e sem simulados.

Publicação exige Cloud Run privado IAM. Este processo NÃO implementa login
próprio: é obrigatório colocá-lo atrás de autenticação do Cloud Run.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time

PROJECT="nivon-data"
DATASET="nivon_raw"
LOCATION="southamerica-east1"
MAX_BYTES_PER_QUERY=50_000_000
CACHE_SECONDS=600
EXPECTED_ROAD_COUNT=16
EXPECTED_ROAD_TON=98_170_287
RAIL_IDS=("MT_RONDONOPOLIS_FERRO","MT_ITIQUIRA_FERRO","MT_ALTO_ARAGUAIA_FERRO")
RAIL_VIEW=f"{PROJECT}.{DATASET}.vw_nivon_corredores_ferrovia_mensal"
ROAD_VIEW=f"{PROJECT}.{DATASET}.vw_antt_rodovia_rgi_top16_atual"

RAIL_SQL=(
    "SELECT polo_id, CAST(SUM(toneladas_uteis) AS STRING) AS tu "
    f"FROM `{RAIL_VIEW}` "
    "WHERE data_referencia BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' "
    "AND polo_id IN ('MT_RONDONOPOLIS_FERRO','MT_ITIQUIRA_FERRO','MT_ALTO_ARAGUAIA_FERRO') "
    "GROUP BY polo_id ORDER BY polo_id LIMIT 3"
)
ROAD_SQL=(
    "SELECT COUNT(*) AS n, CAST(SUM(toneladas) AS STRING) AS tu, "
    f"COUNT(DISTINCT sha256) AS revisions FROM `{ROAD_VIEW}` WHERE ano=2025"
)

class FalhaTerminal(Exception):
    pass

def parse_ton(value):
    try:
        d=Decimal(str(value))
    except (ValueError,TypeError,InvalidOperation) as exc:
        raise FalhaTerminal("tonelagem invalida") from exc
    if not d.is_finite() or d < 0:
        raise FalhaTerminal("tonelagem negativa ou infinita")
    return d

def extrair_snapshot(rail_rows,road_rows,*,agora=None):
    ts=agora or datetime.now(timezone.utc)
    if ts.utcoffset() is None:
        raise FalhaTerminal("instante sem fuso")
    polos={}
    for r in rail_rows:
        if r.polo_id not in RAIL_IDS or r.polo_id in polos:
            raise FalhaTerminal("polo ferroviario desconhecido ou duplicado")
        polos[r.polo_id]=str(parse_ton(r.tu))
    if set(polos) != set(RAIL_IDS):
        raise FalhaTerminal("cobertura dos polos ferroviarios de 2025 incompleta")
    road_rows=list(road_rows)
    if len(road_rows)!=1:
        raise FalhaTerminal("agregado rodoviario invalido")
    road=road_rows[0]
    n=int(road.n)
    revisions=int(road.revisions)
    road_total=parse_ton(road.tu)
    if n != EXPECTED_ROAD_COUNT or revisions != 1 or road_total != EXPECTED_ROAD_TON:
        # Nunca publicar uma revisao inesperada como valor ja conciliado.
        raise FalhaTerminal("revisao rodoviaria mudou: nova conciliacao necessaria")
    return {
        "estado":"DADOS_REAIS_2025_CONFIRMADOS",
        "gerado_em_utc":ts.astimezone(timezone.utc).isoformat(),
        "periodo":"2025-01-01 a 2025-12-31",
        "recorte":"HISTORICO_ANUAL_NAO_TEMPO_REAL",
        "ferrovia":{
            "fonte":"ANTT_SIADE",
            "natureza":"OBSERVADO_DECLARADO_FERROVIARIO",
            "unidade":"toneladas_uteis",
            "granularidade":"ESTACAO_FERROVIARIA_ORIGEM",
            "polos":polos,
            "terminais_confirmados":False,
        },
        "rodovia":{
            "fonte":"ANTT_ANUARIO_TRC_2025",
            "natureza":"OBSERVADO_RELATORIO_TOP16_RGI",
            "unidade":"toneladas",
            "granularidade":"REGIAO_GEOGRAFICA_IMEDIATA",
            "linhas":n,"toneladas_top16":str(road_total),
            "produto_identificado":False,
            "matriz_completa":False,
        },
        "hidrovia":{
            "estado":"NAO_HOMOLOGADA_NA_CAMADA_OFICIAL",
            "fonte_terceira_disponivel_separadamente":True,
        },
        "soma_multimodal_permitida":False,
        "transbordos_confirmados":False,
        "rotulo":"USO_INTERNO_DADOS_HISTORICOS",
    }

def consultar_snapshot(*,cliente=None,sdk=None,agora=None):
    if sdk is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError as exc:
            raise FalhaTerminal("cliente BigQuery indisponivel") from exc
    client=cliente if cliente is not None else sdk.Client(project=PROJECT,location=LOCATION)
    cfg=sdk.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_PER_QUERY,use_query_cache=True)
    rail=list(client.query(RAIL_SQL,job_config=cfg,location=LOCATION).result(timeout=55))
    road=list(client.query(ROAD_SQL,job_config=cfg,location=LOCATION).result(timeout=55))
    return extrair_snapshot(rail,road,agora=agora)

class Cache:
    def __init__(self,loader=None,clock=None,ttl=CACHE_SECONDS):
        self.loader=loader or consultar_snapshot
        self.clock=clock or time.monotonic
        self.ttl=ttl
        self.lock=threading.Lock()
        self.doc=None
        self.expira=0.0
    def get(self):
        with self.lock:
            agora=self.clock()
            if self.doc is not None and agora < self.expira:
                return self.doc
            resultado=self.loader()  # sem stale-while-error; evita informar dado falso
            self.doc=resultado
            self.expira=self.clock()+self.ttl
            return resultado

PAGE="""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="robots" content="noindex,nofollow"/>
<title>NIVON · Terminal Operacional</title>
<link rel="stylesheet" href="/app.css"/></head>
<body><div class="layout">
<header class="top"><div class="brand"><span class="logo">N</span><div><strong>NIVON</strong><small>Inteligência do agro e da logística</small></div></div><span class="pill">ACESSO INTERNO</span></header>
<main><div class="eyebrow">TERMINAL DE INTELIGÊNCIA · 2025</div>
<h1>Corredores de granéis</h1><p class="sub">Visão operacional inicial conectada ao Google Cloud. Dados históricos com fonte e escopo explícitos.</p>
<div id="status" role="status" aria-live="polite">Consultando bases verificadas…</div>
<section class="panels"><article class="tile"><small>Rodo · ANTT TRC</small><strong id="road">—</strong><span>Toneladas dos 16 maiores fluxos RGI em 2025</span><em>Recorte parcial · sem produtos identificados</em></article>
<article class="tile"><small>Ferro · ANTT SIADE</small><strong id="rail">—</strong><span>Toneladas úteis embarcadas nos três polos monitorados, 2025</span><em>Origem ferroviária · não é descarga rodoviária</em></article>
<article class="tile mute"><small>Hidro · ANTAQ</small><strong>Em validação</strong><span>Fonte oficial de microdados ainda não homologada nesta camada</span><em>Não estimamos toneladas ausentes</em></article></section>
<section class="detail"><div class="secTitle"><h2>Embarques ferroviários por polo</h2><span>2025 · toneladas úteis</span></div>
<table><thead><tr><th>Polo</th><th>Toneladas úteis</th><th>Fonte</th></tr></thead><tbody id="polos"><tr><td colspan="3">Carregando dados…</td></tr></tbody></table>
</section>
<section class="note"><strong>Interpretação dos dados</strong><p>Rodovia: 16 fluxos entre regiões geográficas imediatas, não a matriz completa MDF-e. Ferrovia: estações de origem, não transbordos confirmados. Os universos <b>não são somáveis</b>. O terminal não afirma dados em tempo real.</p></section>
</main><footer>NIVON · Plataforma interna · Status das fontes <span id="updated">—</span></footer></div>
<script src="/app.js" defer></script></body></html>"""
STYLE=""":root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;background:#081b14;color:#ecf3ec}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#123e2d 0,transparent 37%),#081b14}.layout{max-width:1200px;margin:auto;padding:20px 28px}.top{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2c4939;padding:18px 0 25px}.brand{display:flex;align-items:center;gap:13px}.brand strong{letter-spacing:.17em;font-size:24px}.brand small{display:block;color:#a6bcb0;font-size:12px;margin-top:2px}.logo{display:grid;place-items:center;width:48px;height:48px;background:#295f3f;border:1px solid #518763;border-radius:12px;color:#e6c16e;font-weight:900;font-size:29px}.pill{border:1px solid #6f7951;background:#262e20;padding:8px 11px;border-radius:30px;font-size:11px;font-weight:700;letter-spacing:.1em;color:#eadba9}main{padding:50px 0}.eyebrow{color:#c2a961;font-size:12px;font-weight:700;letter-spacing:.16em}h1{font-size:clamp(31px,5vw,52px);letter-spacing:-.04em;margin:13px 0 12px}.sub{color:#9fb7a9;font-size:16px;max-width:670px;line-height:1.6}#status{font-size:13px;color:#bfcfbd;border-left:3px solid #d4b96b;padding:10px 15px;margin:24px 0}.panels{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}.tile{background:#10261b;border:1px solid #284b34;border-radius:16px;min-height:210px;padding:24px;display:flex;flex-direction:column;gap:12px}.tile small{font-size:12px;color:#baaf81;text-transform:uppercase;letter-spacing:.1em}.tile strong{font-size:clamp(23px,2.5vw,35px);font-variant-numeric:tabular-nums;letter-spacing:-.02em}.tile span{color:#cee2d0;font-size:13px;line-height:1.45}.tile em{margin-top:auto;font-size:11px;font-style:normal;color:#84998b}.mute{opacity:.8}.detail{margin-top:35px;background:#10251c;border:1px solid #284b34;border-radius:16px;padding:20px 23px}.secTitle{display:flex;align-items:baseline;justify-content:space-between;gap:20px}.secTitle h2{font-size:20px}.secTitle span{font-size:12px;color:#9eb6a5}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:14px 8px;border-top:1px solid #304735}th{font-size:11px;text-transform:uppercase;color:#97ad9a}td{font-size:14px}td:nth-child(2){font-variant-numeric:tabular-nums;font-weight:700}.note{border-left:3px solid #c6a451;margin-top:26px;background:#17251b;padding:17px 21px;color:#b5c6b7;font-size:13px;line-height:1.65}.note strong{color:#efdba4}footer{display:flex;justify-content:space-between;gap:20px;color:#78927f;border-top:1px solid #294534;padding:24px 0;font-size:12px}@media(max-width:800px){.panels{grid-template-columns:1fr}.layout{padding:12px 17px}main{padding:35px 0}.tile{min-height:165px}.secTitle{display:block}.pill{font-size:9px}.brand strong{font-size:19px}}"""
SCRIPT="""(()=>{'use strict';const $=id=>document.getElementById(id);const fmt=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});const polos={MT_RONDONOPOLIS_FERRO:'Rondonópolis',MT_ITIQUIRA_FERRO:'Itiquira',MT_ALTO_ARAGUAIA_FERRO:'Alto Araguaia'};fetch('/api/resumo',{credentials:'same-origin',cache:'no-store'}).then(async r=>{if(!r.ok)throw Error('Dados indisponíveis ('+r.status+')');return r.json()}).then(d=>{if(d.estado!=='DADOS_REAIS_2025_CONFIRMADOS')throw Error('Dados sem conciliação');const p=d.ferrovia.polos;let total=0;const corpo=$('polos');corpo.replaceChildren();for(const id of Object.keys(polos)){const t=Number(p[id]);if(!Number.isFinite(t)||t<0)throw Error('Volume ferroviário inválido');total+=t;const tr=document.createElement('tr');for(const value of [polos[id],fmt.format(t),'ANTT/SIADE']){const td=document.createElement('td');td.textContent=value;tr.appendChild(td)}corpo.appendChild(tr)}$('rail').textContent=fmt.format(total)+' t';$('road').textContent=fmt.format(Number(d.rodovia.toneladas_top16))+' t';$('updated').textContent='Consulta: '+new Date(d.gerado_em_utc).toLocaleString('pt-BR');$('status').textContent='Dados oficiais históricos consultados e conciliados · ano-base 2025 · sem tempo real'}).catch(e=>{$('status').textContent='Base indisponível ou sem conciliação: '+e.message;$('polos').replaceChildren();$('rail').textContent='Indisponível';$('road').textContent='Indisponível'})})();"""

class Handler(BaseHTTPRequestHandler):
    cache=Cache()
    def log_message(self,fmt,*args):
        # Logs sem query strings, dados, cookies ou identificadores pessoais
        print("NIVON_WEB_HTTP",self.command,self.path.split("?",1)[0],flush=True)
    def _reply(self,status,content,typ):
        data=content.encode("utf8") if isinstance(content,str) else content
        self.send_response(status)
        self.send_header("Content-Type",typ)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store, max-age=0")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        route=self.path.split("?",1)[0]
        if route=="/healthz":
            return self._reply(200,'{"status":"alive","data_verified":false}',"application/json; charset=utf-8")
        if route=="/":
            return self._reply(200,PAGE,"text/html; charset=utf-8")
        if route=="/app.css":
            return self._reply(200,STYLE,"text/css; charset=utf-8")
        if route=="/app.js":
            return self._reply(200,SCRIPT,"text/javascript; charset=utf-8")
        if route=="/api/resumo":
            try:
                doc=self.cache.get()
            except Exception:
                # Fail closed; não vazar projeto, tabelas, IAM, dados ou traceback.
                return self._reply(503,'{"estado":"DADOS_NAO_DISPONIVEIS_OU_NAO_CONCILIADOS"}',"application/json; charset=utf-8")
            return self._reply(200,json.dumps(doc,ensure_ascii=False),"application/json; charset=utf-8")
        return self._reply(404,'{"erro":"rota_nao_encontrada"}',"application/json; charset=utf-8")

def main():
    if os.getenv("NIVON_TERMINAL_PRIVATE") != "true":
        raise SystemExit("TERMINAL_REQUER_CLOUD_RUN_PRIVADO")
    port=int(os.getenv("PORT","8080"))
    if not 1<=port<=65535:
        raise SystemExit("PORT_INVALIDO")
    print("NIVON_TERMINAL_PRIVADO_INICIADO",port,flush=True)
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()

if __name__=="__main__":
    main()
