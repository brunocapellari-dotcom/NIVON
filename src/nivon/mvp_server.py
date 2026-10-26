"""NIVON Go-Live MVP: painel HTTP privado, sem serviços ou pacotes externos.

Exibe briefing SOMENTE se o pacote local for íntegro, aprovado pelo
ambiente de execução e ainda recente. IVO é apenas um roteador lexical
offline e NÃO produz respostas de mercado, coleta nem previsões.
Autenticação de usuários é responsabilidade obrigatória do proxy/IAM.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .ivo_planejador import ErroPlanejamento, planejar_consulta
from .mvp_release import ErroReleaseMVP, preparar_edicao


def estado_atual(config: dict, *, agora: datetime) -> tuple[dict, dict | None]:
    """Nunca devolver caminhos locais, tokens, ou o conteúdo recusado."""
    base = {
        "produto": "NIVON",
        "schema": "nivon_mvp_status_v1",
        "modo": "CONSULTA_PRIVADA_READ_ONLY",
        "status": "PREVIEW_SEM_EDICAO_HOMOLOGADA",
        "http_coleta_realizada": False,
        "envio_whatsapp_realizado": False,
        "motores_preditivos_executados": False,
        "publicacao_na_internet_autorizada_pelo_servico": False,
    }
    if config.get("NIVON_RELEASE_APPROVED") != "true":
        return base, None
    try:
        edition = preparar_edicao(
            arquivo=config.get("NIVON_RELEASE_FILE", ""),
            sha256_aprovado=config.get("NIVON_RELEASE_SHA256", ""),
            gerado_ate=agora,
        )
    except (ErroReleaseMVP, OSError, ValueError, TypeError):
        return {**base, "status": "EDICAO_REJEITADA_OU_DESATUALIZADA"}, None
    return {
        **base, "status": "EDICAO_DISPONIVEL_SOMENTE_CONSULTA",
        "edicao": edition["edicao"],
        "gerado_em": edition["gerado_em"],
        "indicadores": edition["indicadores_incluidos"],
        "noticias": edition["noticias_informadas"],
    }, edition


def _pagina(status: dict, release: dict | None, planejamento=None) -> str:
    def esc(x):
        return html.escape(str(x), quote=True)

    online = release is not None
    indicadores = ""
    if online:
        for r in release["indicadores"]:
            indicadores += (
                '<article class="indicador"><div class="cima">' +
                esc(r["secao"]) + '</div><h3>' + esc(r["titulo"]) +
                '</h3><strong>' + esc(r["valor"]) + '</strong><p>' +
                'Ref.: ' + esc(r["referencia"]) + ' · ' +
                esc(r["fonte"]) + '</p></article>'
            )
    if not indicadores:
        indicadores = ('<p class="vazio">Nenhum indicador foi liberado nesta edição. '
                       'Cotações, fretes e notícias não são inventados.</p>')
    resumo = ('<pre>' + esc(release["briefing_texto"]) + '</pre>'
              if online else
              '<p class="vazio">Nenhuma edição de dados com direitos e atualização '
              'aprovados está disponível. O NIVON permanece em modo de consulta.</p>')
    ivo = ""
    if planejamento is not None:
        ivo = '<section><h2>Plano IVO — sem execução de motores</h2><pre>' + esc(
            json.dumps(planejamento, ensure_ascii=False, indent=2)
        ) + '</pre></section>'
    doc = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>NIVON | Agrointeligência</title>
<style>
:root{color-scheme:light;background:#f3f1e9;color:#17291d;font-family:system-ui,-apple-system,Arial,sans-serif}
*{box-sizing:border-box}body{margin:0}.barra{padding:18px max(24px,calc((100vw - 1120px)/2));background:#123d29;color:white}
.marca{font-size:26px;letter-spacing:.16em;font-weight:850}.sub{color:#c9dbc9;font-size:13px}
main{max-width:1120px;margin:36px auto;padding:0 24px}h1{font-size:clamp(25px,4vw,42px);margin:12px 0}
h2{font-size:20px;margin:34px 0 14px}h3{font-size:17px;margin:5px 0}
.tag{color:#87651d;font-size:13px;font-weight:750;text-transform:uppercase;letter-spacing:.08em}
.aviso{border:1px solid #c9c4af;padding:13px 18px;border-radius:10px;background:#fffaf0;line-height:1.5}
.gr{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}
.indicador,section{padding:22px;background:white;border:1px solid #dddccf;border-radius:12px}
.indicador strong{font-size:25px;color:#24663a}.indicador p{font-size:12px;color:#4e5d54}
.cima{color:#a07827;text-transform:uppercase;font-size:12px;font-weight:700}
.vazio{color:#506453;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font:14px/1.7 ui-monospace,monospace}
input{width:min(100%,650px);padding:12px;border:1px solid #aab5a3;border-radius:8px}
button{background:#205b37;border:0;border-radius:8px;color:white;padding:12px 20px;font-weight:bold;cursor:pointer}
small{display:block;margin-top:13px;color:#5e7064}footer{color:#536353;padding:28px 24px;text-align:center;font-size:12px}
</style></head><body><header class="barra"><div class="marca">NIVON</div>
<div class="sub">Inteligência agrícola, mercado e logística · Acesso privado</div></header>
<main><div class="tag">Terminal de consulta · Pré-lançamento controlado</div>
<h1>Agronegócio em perspectiva</h1>
<div class="aviso"><b>Estado: __STATUS__</b><p>Dados observados somente com fontes,
direitos, carimbo temporal e revisão elegíveis. Ausências não são zero.
O serviço não realiza coleta, publicação ou envio WhatsApp.</p></div>
<h2>Indicadores</h2><div class="gr">__INDICADORES__</div>
<h2>Briefing editorial</h2><section>__BRIEFING__</section>
<h2>IVO · Planejamento de consultas</h2><section><p>Descreva uma pergunta sobre
soja, milho, clima, fretes ou logística. O IVO mostrará as frentes e as fontes
necessárias. Não executará pesquisas ou previsões nesta etapa.</p>
<form action="/ivo" method="post"><label for="q">Pergunta</label>
<p><input id="q" name="pergunta" maxlength="450" required
placeholder="Ex.: Quais dados são necessários para analisar o frete de soja?">
<button type="submit">Analisar escopo</button></p></form></section>
__IVO__
</main><footer>NIVON — integração progressiva · Dados não homologados não são publicados.</footer>
</body></html>"""
    return (doc.replace("__STATUS__", esc(status["status"]))
            .replace("__INDICADORES__", indicadores)
            .replace("__BRIEFING__", resumo)
            .replace("__IVO__", ivo))


def _handler(config: dict):
    class App(BaseHTTPRequestHandler):
        server_version = "NIVON-MVP"
        sys_version = ""

        def log_message(self, *_args):
            # Evita registrar perguntas, tokens ou payload em logs públicos.
            pass

        def send(self, status, data, ctype="application/json; charset=utf-8"):
            if isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = json.dumps(data, ensure_ascii=False, sort_keys=True,
                                  allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path)
            if path.query or path.fragment:
                self.send(404, {"status": "ROTA_INEXISTENTE"})
                return
            if path.path == "/healthz":
                self.send(200, {"status": "PROCESSO_ATIVO", "produto": "NIVON"})
                return
            state, edition = estado_atual(config, agora=datetime.now(timezone.utc))
            if path.path == "/api/status":
                self.send(200, state)
            elif path.path == "/api/edicao":
                if edition is None:
                    self.send(503, {"status": state["status"],
                                    "edicao_liberada": False})
                else:
                    self.send(200, edition)
            elif path.path == "/":
                self.send(200, _pagina(state, edition),
                          "text/html; charset=utf-8")
            else:
                self.send(404, {"status": "ROTA_INEXISTENTE"})

        def do_POST(self):
            if self.path != "/ivo":
                self.send(404, {"status": "ROTA_INEXISTENTE"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != (
                "application/x-www-form-urlencoded"
            ):
                self.send(415, {"status": "TIPO_NAO_SUPORTADO"})
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n < 1 or n > 1024:
                    raise ValueError("tamanho do formulário")
                content = self.rfile.read(n).decode("utf-8")
                params = parse_qs(content, keep_blank_values=True,
                                  max_num_fields=2, strict_parsing=True)
                if set(params) != {"pergunta"} or len(params["pergunta"]) != 1:
                    raise ValueError("formulário inválido")
                question = params["pergunta"][0]
                if len(question) > 450:
                    raise ValueError("pergunta extensa")
                plan = planejar_consulta(question, max_frentes=4)
            except (ValueError, UnicodeError, ErroPlanejamento, OSError):
                self.send(400, {"status": "PERGUNTA_INVALIDA"})
                return
            state, edition = estado_atual(config, agora=datetime.now(timezone.utc))
            self.send(200, _pagina(state, edition, planejamento=plan),
                      "text/html; charset=utf-8")

        def do_HEAD(self):
            self.send(405, {"status": "METODO_NAO_SUPORTADO"})

    return App


def main() -> None:
    host = os.getenv("NIVON_BIND", "127.0.0.1")
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise SystemExit("NIVON_BIND fora de contrato")
    if host == "0.0.0.0" and os.getenv("NIVON_PRIVATE_DEPLOY_APPROVED") != "true":
        raise SystemExit("escuta externa bloqueada: exigir IAM/proxy privado")
    port = int(os.getenv("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise SystemExit("porta inválida")
    with ThreadingHTTPServer((host, port), _handler(dict(os.environ))) as server:
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
