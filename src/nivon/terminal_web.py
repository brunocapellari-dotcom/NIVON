"""NIVON Terminal — prévia privada de produção, apenas BigQuery read-only.

Serve informações ferroviárias comprovadas, não habilita ingestão, gravação,
alteração de IAM nem publicação de dados licenciados de outras fontes.
Exige Cloud Run IAM authentication no deploy; HTTP local é apenas para teste.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Lock
import time
from urllib.parse import urlsplit

from .antt_bigquery import DestinoBQ
from .transporte_multimodal import ErroTransporte

PROJETO = "nivon-data"
DATASET = "nivon_raw"
LIMITE_BYTES = 250_000_000
TTL_SEGUNDOS = 900
ANOS_INICIAIS = 2006
MAX_ANOS = 35
# Alerta operacional explícito; não representa SLA oficial da ANTT.
ALERTA_DEFASAGEM_MESES = 3

# Shared visual assets from PR #276; the existing HTTP server remains the entrypoint.
HTML = files("nivon").joinpath("portal_static", "index.html").read_text(encoding="utf-8")
ASSETS = {
    "/assets/portal.js": ("portal.js", "text/javascript; charset=utf-8"),
    "/assets/portal.css": ("portal.css", "text/css; charset=utf-8"),
}


def _ano_valido(ano: int, fim: int) -> bool:
    return type(ano) is int and ANOS_INICIAIS <= ano <= fim


def interpretar_serie(linhas, *, ultimo_ano: int, agora: datetime) -> dict:
    if agora.utcoffset() is None:
        raise ErroTransporte("relógio sem timezone")
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
            referencia = obj["ultima_referencia"]
            sha = obj["arquivo_sha256"]
            ausentes = obj["campos_ausentes"]
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise ErroTransporte("retorno BigQuery incompleto") from exc
        if (ano != esperado or registros < 1 or not tu.is_finite() or tu < 0
                or nversoes != 1 or len(comp) != 7 or comp[:4] != str(ano)
                or comp[4] != "-" or not comp[5:].isdigit()
                or not 1 <= int(comp[5:]) <= 12):
            raise ErroTransporte("ano, versao, competencia ou volume inconsistente")
        if comp > agora.strftime("%Y-%m"):
            raise ErroTransporte("competencia futura")
        if (type(ausentes) is not int or ausentes != 0 or not isinstance(sha, str)
                or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)):
            raise ErroTransporte("proveniencia ausente ou inconsistente")
        if type(referencia) is not date or referencia.isoformat() != comp + "-01":
            raise ErroTransporte("data de referencia divergente da competencia")
        if not isinstance(coleta, datetime) or coleta.utcoffset() is None:
            raise ErroTransporte("data de coleta sem fuso")
        coleta = coleta.astimezone(timezone.utc)
        if coleta > agora or coleta.date() < referencia:
            raise ErroTransporte("data de coleta futura ou anterior ao ano")
        if ultima_coleta is None or coleta > ultima_coleta:
            ultima_coleta = coleta
        total_tu += tu
        total_od += registros
        anos.append({
            "ano":ano,"registros":registros,"toneladas_uteis":str(tu),
            "arquivo_sha256":sha,"data_referencia":referencia.isoformat(),
            "data_coleta_utc":coleta.isoformat(),
            "ultima_competencia":comp,"parcial":ano == ultimo_ano and comp != f"{ano}-12"
        })
    referencia_final = date.fromisoformat(anos[-1]["data_referencia"])
    idade_meses = (agora.year - referencia_final.year) * 12 + agora.month - referencia_final.month
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
        "freshness":{"estado":"SOURCE_LAG" if idade_meses > ALERTA_DEFASAGEM_MESES else "DENTRO_DA_JANELA_DE_ALERTA",
                     "idade_competencia_meses":idade_meses,
                     "limite_alerta_meses":ALERTA_DEFASAGEM_MESES,"sla_oficial":False},
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
        "MIN(arquivo_sha256) AS arquivo_sha256, "
        "MAX(data_referencia) AS ultima_referencia, "
        "COUNTIF(toneladas_uteis IS NULL OR competencia IS NULL OR "
        "arquivo_sha256 IS NULL OR data_coleta IS NULL OR data_referencia IS NULL) AS campos_ausentes, "
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


def servidor(state=None):
    estado=state or TerminalState()

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
                "default-src 'none'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'")
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
            if path in ASSETS:
                name,content_type=ASSETS[path]
                body=files("nivon").joinpath("portal_static",name).read_bytes()
                self.responder(200,body,content_type)
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
