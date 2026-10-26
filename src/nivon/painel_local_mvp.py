"""Painel interno mínimo do NIVON (localhost, somente leitura, zero deps).

GET /          -> HTML acessível, nenhum JavaScript externo.
GET /api/ptax  -> consulta GET ao BCB sob demanda e cache volátil de 90s.
GET /healthz   -> saúde do processo; NÃO declara dataset fresco/go-live.
Não publica na internet, não persiste dados e não envia WhatsApp.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import urlsplit

from .piloto_ptax_readonly import ErroPiloto, executar

HOST = "127.0.0.1"
TTL_SECONDS = 90
APP_STATUS = "PILOTO_INTERNO_NAO_HOMOLOGADO"

PAGE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIVON | Terminal interno</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#172b28;background:#f4f7f4}
*{box-sizing:border-box}body{margin:0}header{background:#143f32;color:white;padding:26px 7vw}
small{opacity:.75;letter-spacing:.12em;text-transform:uppercase}h1{margin:4px 0;font-size:2rem}
main{max-width:1120px;margin:0 auto;padding:28px 20px}
.notice{border-left:4px solid #9c6420;background:#fff8e9;padding:12px 16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-top:24px}
article{background:white;border:1px solid #dce7e0;border-radius:12px;padding:20px;min-height:155px}
label{font-weight:600;color:#46665b;font-size:.88rem}
.value{font-size:2.2rem;font-weight:720;margin:12px 0}
#status{font-weight:600}button{background:#165642;color:white;padding:10px 16px;border:none;
border-radius:8px;cursor:pointer}button:disabled{opacity:.5;cursor:default}
meta{color:#46665b}footer{margin-top:32px;color:#576e65;font-size:.9rem}
</style>
</head>
<body>
<header><small>Inteligência agropecuária, mercados e logística</small>
<h1>NIVON</h1><div>Terminal interno · Visualização operacional</div></header>
<main>
<div class="notice"><strong>Piloto não homologado.</strong>
Dados em tempo real somente onde a fonte estiver verificada.
Sem publicação externa, envio WhatsApp ou coleta agendada.</div>
<p><button id="reload" type="button">Consultar PTAX oficial</button>
 <span id="status" role="status" aria-live="polite">Consulta sob demanda</span></p>
<section class="cards" aria-label="Indicadores">
<article><label>PTAX USD/BRL · venda</label>
<div class="value" id="rate">—</div><div id="reference">Aguardando consulta do Banco Central</div></article>
<article><label>Variação × dia anterior observado</label>
<div class="value" id="change">—</div><div id="coleta">Sem dados carregados</div></article>
<article><label>Safra · CONAB / IMEA</label><div class="value">Indisponível</div>
<div>Integração e homologação em andamento</div></article>
<article><label>Preços físicos · CEPEA</label><div class="value">Indisponível</div>
<div>Dados atuais e direitos pendentes</div></article>
<article><label>Diesel · ANP</label><div class="value">Indisponível</div>
<div>Coleta persistente ainda não homologada</div></article>
<article><label>Line-up e logística</label><div class="value">Indisponível</div>
<div>Não confundir programação com realização</div></article>
</section>
<footer>Fonte do indicador ativo: Banco Central do Brasil (PTAX/OData).
Valores observados não são previsões, recomendações ou preços físicos de grãos.</footer>
</main>
<script>
const q=id=>document.getElementById(id);
async function atualizar(){
 const button=q('reload');button.disabled=true;q('status').textContent='Consultando fonte oficial…';
 try{
  const response=await fetch('/api/ptax',{cache:'no-store'});
  const d=await response.json();
  if(!response.ok||d.status!=='PREVIA_INTERNA_VALIDA'){
   q('rate').textContent='—';q('change').textContent='—';
   q('reference').textContent='Cotação indisponível ou vencida';
   q('status').textContent='Fonte indisponível — não reutilizar cotação antiga';
   return;
  }
  q('rate').textContent=Number(d.cotacao_venda).toLocaleString('pt-BR',{minimumFractionDigits:4,maximumFractionDigits:4});
  q('change').textContent=d.variacao_venda_pct_vs_dia_anterior_observado==null?
    'Sem base anterior':Number(d.variacao_venda_pct_vs_dia_anterior_observado).toFixed(2)+'%';
  q('reference').textContent='Referência: '+d.competencia+' · '+d.referencia_utc;
  q('coleta').textContent='Coletado: '+d.coletado_utc;
  q('status').textContent='Informado pelo BCB · '+d.idade_horas+' horas desde a observação';
 }catch(e){
  q('rate').textContent='—';q('change').textContent='—';
  q('status').textContent='Falha de conexão — nenhum valor presumido';
 }finally{button.disabled=false}
}
q('reload').addEventListener('click',atualizar);
</script></body></html>
"""


class CacheVolatil:
    def __init__(self, consultar: Callable[[], dict]):
        self.consultar = consultar
        self.cached: dict | None = None
        self.stamp = 0.0
        self.lock = threading.Lock()

    def read(self) -> dict:
        with self.lock:
            if self.cached is not None and time.monotonic()-self.stamp<TTL_SECONDS:
                return dict(self.cached)
            # Não reaproveitar dados vencidos após uma falha de rede.
            self.cached = None
            result = self.consultar()
            self.cached = dict(result)
            self.stamp = time.monotonic()
            return result


def construir_servidor(*, porta: int=8765, host: str=HOST,
                       consulta: Callable[[],dict] | None=None) -> HTTPServer:
    if host != HOST:
        raise ValueError("piloto só pode atender no localhost 127.0.0.1")
    if type(porta) is not int or not 0<=porta<=65535:
        raise ValueError("porta HTTP inválida")
    consulta = consulta or (lambda: executar(agora=datetime.now(timezone.utc)))
    cache = CacheVolatil(consulta)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            # Evita endereços/retornos de consulta em logs persistentes.
            pass

        def _send(self, status: int, value: bytes, kind: str):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(value)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(value)

        def _json(self, status: int, obj: dict):
            self._send(status, json.dumps(obj, ensure_ascii=False,
                    allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path=urlsplit(self.path)
            if path.query or path.fragment:
                self._json(400, {"erro":"parâmetros proibidos"})
                return
            if path.path=="/":
                self._send(200,PAGE.encode("utf-8"),"text/html; charset=utf-8")
            elif path.path=="/healthz":
                self._json(200,{"processo":"UP","estado":APP_STATUS,
                                "publicacao_ativa":False,"dados_atuais_confirmados":False})
            elif path.path=="/api/ptax":
                try:
                    data=cache.read()
                except (ErroPiloto,OSError,ValueError):
                    self._json(503,{"status":"INDISPONIVEL",
                                    "mensagem":"Falha de fonte/validação; não reutilizar valores",
                                    "aprovado_go_live":False})
                    return
                self._json(200 if data.get("status")=="PREVIA_INTERNA_VALIDA" else 503,data)
            else:
                self._json(404,{"erro":"rota inexistente"})

    server = HTTPServer((host,porta),Handler)
    return server


def main() -> int:
    parser=argparse.ArgumentParser(description="Terminal NIVON local, jamais expor publicamente")
    parser.add_argument("--porta", type=int,default=8765)
    args=parser.parse_args()
    server=construir_servidor(porta=args.porta)
    print(f"NIVON PILOTO INTERNO http://{HOST}:{server.server_port} — não homologado")
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
