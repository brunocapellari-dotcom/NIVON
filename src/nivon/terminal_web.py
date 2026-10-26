"""NIVON Terminal — prévia privada de produção, apenas BigQuery read-only.

Serve informações ferroviárias comprovadas, não habilita ingestão, gravação,
alteração de IAM nem publicação de dados licenciados de outras fontes.
Exige Cloud Run IAM authentication no deploy; HTTP local é apenas para teste.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import os
from threading import Lock
import time
from urllib.parse import urlsplit

from .terminal_snapshot_gcs import EstadoSnapshot
from .antt_bigquery import DestinoBQ
from .transporte_multimodal import ErroTransporte

PROJETO = "nivon-data"
DATASET = "nivon_raw"
LIMITE_BYTES = 250_000_000
TTL_SEGUNDOS = 900
ANOS_INICIAIS = 2006
MAX_ANOS = 35

HTML = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>NIVON | Terminal de Inteligência Agro</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;
color:#e7eee9;background:#091d17}*{box-sizing:border-box}
body{margin:0}header{padding:18px max(4vw,24px);border-bottom:1px solid #294239;
display:flex;align-items:center;gap:22px;background:#0e261d}
.logo{font-size:23px;color:#e6b963;font-weight:800;letter-spacing:.12em}
header span{font-size:13px;color:#b4c8bc}
main{max-width:1150px;margin:auto;padding:32px 20px 75px}
h1{font-size:clamp(26px,4vw,40px);margin:2px 0 10px;font-weight:650}
p{color:#b5c6ba;line-height:1.55}.eyebrow{color:#dab66b;font-size:12px;letter-spacing:.18em}
.status{padding:10px 13px;border:1px solid #53614b;border-radius:8px;
font-size:13px;display:inline-block;color:#e2cb99;margin:18px 0 25px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}
.metric,.panel{background:#10291f;border:1px solid #305043;border-radius:12px;padding:20px}
.label{font-size:12px;color:#adc4b3}.value{font-size:clamp(22px,3vw,31px);font-weight:650;
margin:12px 0 4px;font-variant-numeric:tabular-nums}
small{color:#a9bda9}.section{margin-top:24px}
h2{font-size:17px;margin:0 0 13px;font-weight:600}.chart{display:flex;gap:4px;
align-items:end;min-height:270px;border-bottom:1px solid #55735b;padding:35px 0 0}
.bar-col{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:end;
height:235px;align-items:center;gap:7px}
.bar{width:clamp(5px,70%,35px);background:#499a67;border-radius:3px 3px 0 0;min-height:2px}
.bar.partial{background:#c2a364}
.year{font-size:10px;color:#b0bcb1;transform:rotate(-60deg);white-space:nowrap}
.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;color:#aebfb2;font-weight:500}th,td{padding:10px 12px;border-bottom:1px solid #30483c}
td:nth-child(n+2){font-variant-numeric:tabular-nums}
footer{margin-top:30px;border-top:1px solid #355345;padding-top:14px;font-size:12px;color:#9cb3a4}
.muted{font-size:12px}.error{color:#efb3a6}
@media(max-width:720px){.grid{grid-template-columns:1fr}
header{flex-wrap:wrap}.year{font-size:9px}.bar-col{gap:4px}}
</style></head><body>
<header><div class="logo">NIVON</div><span>Inteligência agroindustrial e logística</span></header>
<main>
<p><a href="/portal" style="color:#e6b963">Painel integrado: ferrovia, programação marítima e PortWatch ↗</a></p>
<div class="eyebrow">TERMINAL PRIVADO · PRÉVIA OPERACIONAL</div>
<h1>Ferrovia brasileira, em números.</h1>
<p>Movimentação por origem–destino registrada na ANTT/SIADE, lida diretamente do BigQuery.
Dados históricos declarados; 2026 ainda parcial. Sem mistura com volumes rodoviários ou hidroviários.</p>
<div id="estado" class="status" role="status" aria-live="polite">Carregando dados reais…</div>
<div class="grid" id="cards" hidden>
<div class="metric"><div class="label">Toneladas úteis acumuladas</div><div id="tu" class="value">—</div>
<small>Soma por ano, não equivale a cargas únicas</small></div>
<div class="metric"><div class="label">Registros origem–destino</div><div id="od" class="value">—</div>
<small>Histórico das ferrovias concedidas</small></div>
<div class="metric"><div class="label">Última competência disponível</div><div id="competencia" class="value">—</div>
<small id="atualizacao">Data de extração: —</small></div></div>
<section class="section panel" id="serie" hidden><h2>Série anual — toneladas úteis</h2>
<div class="chart" id="chart" role="img" aria-label="Histórico ferroviário anual"></div>
<p class="muted">A coluna mais recente pode representar período parcial. Base revisável pela ANTT.</p>
</section>
<section class="section panel" id="tabela" hidden><h2>Histórico detalhado por ano</h2>
<div class="table-wrap"><table><thead><tr><th>Ano</th><th>Toneladas úteis</th>
<th>Registros OD</th><th>Última competência</th></tr></thead><tbody id="linhas"></tbody></table></div></section>
<footer>Fonte: Agência Nacional de Transportes Terrestres (ANTT), SIADE.
Natureza: OBSERVADO_DECLARADO. Revisão atual da fonte; não é reconstrução point-in-time.
NIVON — visualização privada para avaliação, ainda sem homologação editorial plena.</footer>
</main><script>
const fmt=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
function set(id,v){document.getElementById(id).textContent=v;}
async function carregar(){
  try{
    const r=await fetch('/api/v1/ferrovia',{cache:'no-store'});
    if(!r.ok)throw new Error('Consulta indisponível ('+r.status+').');
    const dados=await r.json();
    if(dados.estado!=='ANTT_SERIE_OBSERVADA_DECLARADA')throw new Error('Série não validada.');
    set('tu',fmt.format(dados.tu_acumuladas));
    set('od',fmt.format(dados.registros_acumulados));
    set('competencia',dados.ultima_competencia);
    set('atualizacao','Última coleta: '+dados.ultima_coleta_utc.slice(0,16).replace('T',' ')+' UTC');
    const chart=document.getElementById('chart'),rows=document.getElementById('linhas');
    const peak=Math.max(...dados.serie.map(x=>Number(x.toneladas_uteis)));
    for(const a of dados.serie){
      const col=document.createElement('div');col.className='bar-col';
      const bar=document.createElement('div');bar.className='bar'+(a.parcial?' partial':'');
      bar.style.height=(Number(a.toneladas_uteis)/peak*190)+'px';
      bar.title=a.ano+': '+fmt.format(a.toneladas_uteis)+' TU';
      const yr=document.createElement('div');yr.className='year';yr.textContent=a.ano;
      col.append(bar,yr);chart.append(col);
      const tr=document.createElement('tr');
      for(const v of [String(a.ano),fmt.format(a.toneladas_uteis),
                      fmt.format(a.registros),a.ultima_competencia]){
        const td=document.createElement('td');td.textContent=v;tr.append(td);
      }rows.append(tr);
    }
    set('estado','DADOS DECLARADOS DA ANTT · Consulta real BigQuery · Última versão');
    for(const id of ['cards','serie','tabela'])document.getElementById(id).hidden=false;
  }catch(e){
    const status=document.getElementById('estado');status.classList.add('error');
    set('estado','DADOS INDISPONÍVEIS: '+e.message+' Nenhum número foi estimado.');
  }
}carregar();
</script></body></html>"""


def _ano_valido(ano: int, fim: int) -> bool:
    return type(ano) is int and ANOS_INICIAIS <= ano <= fim


def interpretar_serie(linhas, *, ultimo_ano: int, agora: datetime) -> dict:
    if (not _ano_valido(ultimo_ano, agora.year)
            or ultimo_ano - ANOS_INICIAIS + 1 > MAX_ANOS):
        raise ErroTransporte("janela de anos invalida")
    itens = list(linhas)
    if len(itens) != ultimo_ano - ANOS_INICIAIS + 1:
        raise ErroTransporte("historico anual incompleto; nao publicar totais")
    anos = []
    total_tu = Decimal(0)
    total_od = 0
    ultima_coleta = None
    for indice, row in enumerate(itens):
        obj = dict(row.items()) if hasattr(row, "items") else dict(row)
        esperado = ANOS_INICIAIS + indice
        try:
            ano = int(obj["ano"])
            registros = int(obj["registros"])
            tu = Decimal(str(obj["tu"]))
            comp = str(obj["ultima_competencia"])
            nversoes = int(obj["versoes_sha"])
            coleta = obj["ultima_coleta"]
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise ErroTransporte("retorno BigQuery incompleto") from exc
        if (ano != esperado or registros < 1 or not tu.is_finite() or tu <= 0
                or nversoes != 1 or len(comp) != 7 or comp[:4] != str(ano)
                or comp[4] != "-" or not comp[5:].isdigit()
                or not 1 <= int(comp[5:]) <= 12):
            raise ErroTransporte("ano, versao, competencia ou volume inconsistente")
        if not isinstance(coleta, datetime) or coleta.utcoffset() is None:
            raise ErroTransporte("data de coleta sem fuso")
        coleta = coleta.astimezone(timezone.utc)
        if coleta > agora or coleta.year < ano:
            raise ErroTransporte("data de coleta futura ou anterior ao ano")
        if ultima_coleta is None or coleta > ultima_coleta:
            ultima_coleta = coleta
        total_tu += tu
        total_od += registros
        anos.append({
            "ano":ano,"registros":registros,"toneladas_uteis":str(tu),
            "ultima_competencia":comp,"parcial":ano == ultimo_ano and comp != f"{ano}-12"
        })
    if anos[-1]["ultima_competencia"] > agora.strftime("%Y-%m"):
        raise ErroTransporte("competencia futura")
    return {
        "estado":"ANTT_SERIE_OBSERVADA_DECLARADA",
        "fonte":"ANTT/SIADE — transporte ferroviario origem-destino",
        "natureza":"OBSERVADO_DECLARADO",
        "homologacao_editorial":False,
        "serie":anos,
        "anos":len(anos),
        "registros_acumulados":total_od,
        "tu_acumuladas":str(total_tu),
        "ultima_competencia":anos[-1]["ultima_competencia"],
        "ultima_coleta_utc":ultima_coleta.isoformat(),
        "soma_multimodal_permitida":False,
        "point_in_time_historico":False,
        "status_publicacao":"PREVIA_PRIVADA",
    }


def consultar_ferrovia(*, cliente=None, sdk=None, agora=None) -> dict:
    instante = agora or datetime.now(timezone.utc)
    if instante.utcoffset() is None:
        raise ErroTransporte("relógio sem timezone")
    destino = DestinoBQ(PROJETO, DATASET)
    if cliente is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError as exc:
            raise ErroTransporte("google-cloud-bigquery nao instalado") from exc
        cliente = sdk.Client(project=PROJETO)
    elif sdk is None:
        raise ErroTransporte("SDK de teste obrigatorio")
    fim = instante.year
    if fim < 2026 or fim - ANOS_INICIAIS + 1 > MAX_ANOS:
        raise ErroTransporte("janela de fonte nao parametrizada")
    sql=(
        "SELECT ano, COUNT(*) AS registros, "
        "CAST(SUM(toneladas_uteis) AS STRING) AS tu, "
        "MAX(competencia) AS ultima_competencia, "
        "COUNT(DISTINCT arquivo_sha256) AS versoes_sha, "
        "MAX(data_coleta) AS ultima_coleta "
        "FROM " + chr(96) + destino.view_completa + chr(96)
        + " WHERE ano BETWEEN 2006 AND @fim "
        "GROUP BY ano ORDER BY ano"
    )
    cfg = sdk.QueryJobConfig(
        maximum_bytes_billed=LIMITE_BYTES,
        use_query_cache=True,
        query_parameters=[sdk.ScalarQueryParameter("fim","INT64",fim)],
    )
    job = cliente.query(sql, job_config=cfg)
    resultado = interpretar_serie(job.result(timeout=90), ultimo_ano=fim, agora=instante)
    resultado["bytes_processados_ultimo_job"] = getattr(job,"total_bytes_processed",None)
    return resultado


class TerminalState:
    """Memória curta para evitar consulta BQ em cada acesso ao terminal."""
    def __init__(self, consulta=None, relogio=None):
        self.consulta=consulta or consultar_ferrovia
        self.relogio=relogio or time.monotonic
        self.bloqueio=Lock()
        self.dados=None
        self.expira_em=0.0

    def obter(self):
        with self.bloqueio:
            agora=self.relogio()
            if self.dados is None or agora >= self.expira_em:
                resultado=self.consulta()
                if resultado.get("estado") != "ANTT_SERIE_OBSERVADA_DECLARADA":
                    raise ErroTransporte("consulta nao retornou dados validos")
                self.dados=resultado
                self.expira_em=agora+TTL_SEGUNDOS
            return self.dados


def servidor(state=None, snapshot=None):
    estado=state or TerminalState()
    dados_integrados=snapshot or EstadoSnapshot()

    class Handler(BaseHTTPRequestHandler):
        def responder(self, status:int, corpo:bytes, content_type:str):
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(corpo)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("X-Frame-Options","DENY")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy",
                "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            path=urlsplit(self.path).path
            if path == "/healthz":
                self.responder(200,b'{"estado":"PROCESSO_ATIVO"}',"application/json; charset=utf-8")
                return
            if path in ("/", "/index.html"):
                self.responder(200,HTML.encode("utf-8"),"text/html; charset=utf-8")
                return
            if path in ("/portal", "/portal/"):
                html=files("nivon").joinpath("portal_static","index.html").read_bytes()
                self.responder(200,html,"text/html; charset=utf-8")
                return
            if path in ("/assets/portal.css", "/assets/portal.js"):
                asset=path.rsplit("/",1)[-1]
                doc=files("nivon").joinpath("portal_static",asset).read_bytes()
                mime="text/css; charset=utf-8" if asset.endswith(".css") else "text/javascript; charset=utf-8"
                self.responder(200,doc,mime)
                return
            if path in ("/api/v1/painel", "/readyz"):
                try:
                    snapshot_real=dados_integrados.obter()
                except Exception:
                    self.responder(503,b'{"status":"SNAPSHOT_REAL_INDISPONIVEL"}',
                                   "application/json; charset=utf-8")
                    return
                if path == "/readyz":
                    self.responder(200,b'{"status":"PAINEL_PRIVADO_COM_DADOS_REAIS"}',
                                   "application/json; charset=utf-8")
                    return
                body=json.dumps(snapshot_real,ensure_ascii=False).encode("utf-8")
                self.responder(200,body,"application/json; charset=utf-8")
                return
            if path=="/api/v1/ferrovia":
                try:
                    doc=estado.obter()
                except Exception:
                    # Jamais enviar mensagens do BigQuery, IAM ou paths internos.
                    self.responder(503,b'{"estado":"FONTE_TEMPORARIAMENTE_INDISPONIVEL"}',
                                   "application/json; charset=utf-8")
                    return
                body=json.dumps(doc,ensure_ascii=False,default=str).encode("utf-8")
                self.responder(200,body,"application/json; charset=utf-8")
                return
            self.responder(404,b'{"erro":"ROTA_INEXISTENTE"}',"application/json; charset=utf-8")

        def do_POST(self):
            self.responder(405,b'{"erro":"SOMENTE_LEITURA"}',"application/json; charset=utf-8")
        def log_message(self, fmt, *args):
            # Log mínimo sem URL de query string, tokens ou cabeçalhos.
            return

    return Handler


def main():
    if (os.environ.get("NIVON_BQ_PROJECT")!=PROJETO or
            os.environ.get("NIVON_BQ_DATASET")!=DATASET):
        raise SystemExit("PROJETO_OU_DATASET_NAO_AUTORIZADO")
    porta=int(os.environ.get("PORT","8080"))
    if not 1 <= porta <= 65535:
        raise SystemExit("PORT_INVALIDA")
    srv=ThreadingHTTPServer(("0.0.0.0",porta),servidor())
    srv.serve_forever()


if __name__=="__main__":
    main()
