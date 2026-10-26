"""Terminal NIVON privado: somente leitura de recortes reais ANTT de 2025."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from importlib.resources import files
from threading import Lock
from time import monotonic
from wsgiref.simple_server import make_server

CACHE_SECONDS = 300
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       "connect-src 'self'; img-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
ASSETS = {"/": ("terminal_index.html", "text/html; charset=utf-8"),
          "/assets/terminal.css": ("terminal.css", "text/css; charset=utf-8"),
          "/assets/terminal.js": ("terminal.js", "application/javascript; charset=utf-8")}


class ErroTerminal(ValueError):
    pass


def ler_bq():
    from .corredores_multimodais_2025 import consultar
    return consultar()


def contrato(d):
    if (not isinstance(d, dict)
        or d.get("estado") != "PAINEL_MULTIMODAL_2025_DADOS_SEPARADOS_COM_PROVENIENCIA"
        or d.get("ano") != 2025
        or d.get("escopo_top16_rodoviario_toneladas") != "98170287"
        or d.get("escopo_top16_e_total_nacional") is not False
        or d.get("totais_das_modalidades_somaveis") is not False
        or d.get("transbordos_efetivos_identificados") is not False
        or len(d.get("rodovia_rgi_fluxos_top16", [])) != 16
        or len(d.get("polos", [])) != 9):
        raise ErroTerminal("escopo nao reconciliado")
    return {"estado":"HISTORICO_EM_HOMOLOGACAO","publicavel":False,
            "ano_referencia":2025,"consulta_em_utc":datetime.now(timezone.utc).isoformat(),
            "escopo_top16_rodoviario_toneladas":d["escopo_top16_rodoviario_toneladas"],
            "rodovia_rgi_fluxos_top16":d["rodovia_rgi_fluxos_top16"],
            "polos":d["polos"],"fontes":d["fontes"],
            "avisos":list(d.get("avisos", [])) + [
                "Consulta agora nao implica publicacao nova da fonte.",
                "Nao somar modalidades, interpretar RGI como terminal nem inferir transbordo.",
                "Hidrovia de fonte secundaria nao integra os totais oficiais.",
                "Serie de 2025: nao informa fretes atuais, preco negociado ou previsao."],
            "hidrovia_oficial_homologada":False,
            "modalidades_aditivas":False}


class Terminal:
    """Sem login embutido: Cloud Run IAM PRIVADO obrigatorio para implantar."""
    def __init__(self, *, reader=None, enable_data=None, clock=monotonic):
        self.reader = reader or ler_bq
        self.enabled = (os.getenv("NIVON_TERMINAL_READ_APPROVED") == "true"
                        if enable_data is None else enable_data is True)
        self.clock=clock
        self.lock=Lock()
        self.saved=None
        self.until=0

    def data(self):
        if not self.enabled:
            raise PermissionError("GCP_READ_BLOCKED")
        with self.lock:
            if self.saved is not None and self.clock() < self.until:
                return self.saved
            self.saved=contrato(self.reader())
            self.until=self.clock()+CACHE_SECONDS
            return self.saved

    @staticmethod
    def reply(start, status, raw, mime):
        start(status,[("Content-Type",mime),("Content-Length",str(len(raw))),
                      ("Cache-Control","private,no-store,max-age=0"),
                      ("Content-Security-Policy",CSP),
                      ("X-Content-Type-Options","nosniff"),
                      ("X-Frame-Options","DENY"),("Referrer-Policy","no-referrer")])
        return [raw]

    def json(self,start,status,obj):
        return self.reply(start,status,json.dumps(obj,ensure_ascii=False,
                          allow_nan=False).encode("utf-8"),"application/json; charset=utf-8")

    def __call__(self,environ,start):
        if environ.get("REQUEST_METHOD")!="GET":
            return self.json(start,"405 Method Not Allowed",{"status":"METODO_BLOQUEADO"})
        if environ.get("QUERY_STRING",""):
            return self.json(start,"400 Bad Request",{"status":"PARAMETROS_BLOQUEADOS"})
        path=environ.get("PATH_INFO","")
        if path=="/healthz":
            return self.json(start,"200 OK",{"processo":"ATIVO","leitura_habilitada":self.enabled,
                                             "publicacao_homologada":False})
        if path=="/api/v1/painel":
            try:
                return self.json(start,"200 OK",self.data())
            except PermissionError:
                return self.json(start,"503 Service Unavailable",{"status":"LEITURA_DESABILITADA"})
            except Exception:
                return self.json(start,"503 Service Unavailable",{"status":"FONTE_INDISPONIVEL"})
        asset=ASSETS.get(path)
        if asset is None:
            return self.json(start,"404 Not Found",{"status":"NAO_ENCONTRADO"})
        return self.reply(start,"200 OK",files("nivon").joinpath(asset[0]).read_bytes(),asset[1])


application=Terminal()


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--porta",type=int,default=8080)
    a=p.parse_args()
    if not 1024<=a.porta<=65535:
        raise SystemExit("PORTA_INVALIDA")
    with make_server("127.0.0.1",a.porta,application) as server:
        server.serve_forever()


if __name__=="__main__":
    main()
