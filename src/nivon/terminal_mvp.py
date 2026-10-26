"""NIVON Terminal Interno — primeira superfície de produto com dados reais.

WSGI simples, sem frontend externo. Somente consultas read-only limitadas
a BigQuery existente. Fail closed: sem token, orçamento/consentimento e
credenciais, nenhum dado de domínio é servido. Não torna um snapshot
histórico "ao vivo" nem converte programa portuário em operação concluída.

Hospedagem não executada por este módulo. Nunca publicar sem HTTPS/IAM,
segredo forte e aprovação de custo BigQuery.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
import re
from urllib.parse import parse_qs

from .ferrovia_painel_bq import consultar_ferrovia
from .maritimo_painel_bigquery import consultar_maritimo, PASSAGENS

ALLOWED_METHODS = {"GET", "HEAD"}
MONTH = re.compile(r"^20[0-9]{2}-(?:0[1-9]|1[0-2])$")
DEFAULT_PASSAGEM = "panama"
HEADERS = [
    ("Content-Type", "application/json; charset=utf-8"),
    ("Cache-Control", "no-store, private"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
]
HTML_HEADERS = [
    ("Content-Type", "text/html; charset=utf-8"),
    ("Cache-Control", "no-store, private"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy",
     "default-src 'none'; script-src 'self'; style-src 'self'; "
     "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'"),
]


class ErroTerminal(ValueError):
    pass


def _auth(token, config):
    digest = config.get("NIVON_MVP_TOKEN_SHA256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        return False
    if not isinstance(token, str) or len(token) < 24 or len(token) > 256:
        return False
    return hmac.compare_digest(sha256(token.encode("utf-8")).hexdigest(), digest)


def _params(query):
    raw = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
    if any(len(v)!=1 for v in raw.values()) or set(raw) - {"mes", "passagem"}:
        raise ErroTerminal("filtros invalidos")
    mes=raw.get("mes", ["2025-12"])[0]
    passagem=raw.get("passagem", [DEFAULT_PASSAGEM])[0]
    if not MONTH.fullmatch(mes) or passagem not in PASSAGENS:
        raise ErroTerminal("mes ou passagem fora do contrato")
    return mes, passagem


def montar_resumo(*, projeto, dataset, mes, passagem, instante=None,
                 ler_ferrovia=consultar_ferrovia, ler_maritimo=consultar_maritimo):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", projeto):
        raise ErroTerminal("projeto GCP invalido")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,200}", dataset):
        raise ErroTerminal("dataset GCP invalido")
    if not MONTH.fullmatch(mes) or passagem not in PASSAGENS:
        raise ErroTerminal("filtros invalidos")
    agora=instante or datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.utcoffset() is None:
        raise ErroTerminal("requer instante com timezone")
    agora=agora.astimezone(timezone.utc)
    hoje=agora.date()
    mes_data=datetime.fromisoformat(mes+"-01").date()
    if mes_data>hoje:
        raise ErroTerminal("competencia futura")
    inicio=(hoje-timedelta(days=29)).isoformat()
    fim=hoje.isoformat()
    output={
        "nome":"NIVON", "versao":"mvp-interno-1",
        "corte":agora.isoformat(), "mes_ferrovia":mes,
        "janela_portwatch":[inicio,fim], "passagem":passagem,
        "natureza":"LEITURA_HISTORICA_RESTRITA",
        "homologado_para_decisoes_comerciais":False,
        "consultas_reais_confirmadas":0, "fontes":{},
        "regras":["Nao somar modalidades distintas",
                  "Revisao de programacao nao e operacao concluida",
                  "Revisao ferroviaria atual nao reconstrui vintages historicos"],
    }
    erros=[]
    try:
        rail=ler_ferrovia(projeto=projeto,dataset=dataset,competencia=mes,
            uf_origem="MT",as_of=agora.isoformat(),limite=400,
            max_bytes_billed=50_000_000,executar=True)
        if rail.get("executado") is not True or rail.get("publicavel") is not False:
            raise ErroTerminal("consulta ferroviaria sem comprovacao")
        output["consultas_reais_confirmadas"]+=1
        output["fontes"]["ferrovia"]={
            "estado":rail.get("estado"),"fonte":"ANTT_SIADE_ORIGEM_DESTINO",
            "competencia":mes,"unidade":"toneladas uteis",
            "polos":rail.get("polos_ferroviarios",[])[:15],
            "linhas_view":rail.get("linhas_view"),
            "historico_pit_reconstruido":False,"publicavel":False,
            "sem_registro_nao_equivale_a_zero":True,
        }
    except Exception as exc:
        erros.append({"fonte":"ferrovia","estado":"INDISPONIVEL",
                      "classe_erro":type(exc).__name__})
    try:
        mar=ler_maritimo(projeto=projeto,dataset=dataset,inicio=inicio,
            fim=fim,as_of=agora.isoformat(),passagem=passagem,
            limite=400,max_bytes_billed=50_000_000,executar=True)
        if mar.get("executado") is not True or mar.get("publicavel") is not False:
            raise ErroTerminal("consulta maritima sem comprovacao")
        output["consultas_reais_confirmadas"]+=1
        output["fontes"]["maritimo"]={
            k:v for k,v in mar.items() if k in (
                "estado","passagem","inicio","fim","dias_distintos","revisoes_visiveis",
                "vintages_descartadas_para_soma","transitos_ais_reportados",
                "volume_estimado_modelo_t","publicavel","nota")
        }
        output["fontes"]["maritimo"]["volume_realizado_confirmado"]=False
        output["fontes"]["maritimo"]["fonte"]="FMI_PORTWATCH_DERIVADO"
    except Exception as exc:
        erros.append({"fonte":"maritimo","estado":"INDISPONIVEL",
                      "classe_erro":type(exc).__name__})
    output["erros"]=erros
    output["estado"]=(
        "CONSULTAS_REAIS_LIMITADAS" if not erros
        else "DADOS_PARCIAIS" if output["consultas_reais_confirmadas"]
        else "SEM_FONTE_VERIFICADA"
    )
    return output


def _json(status, body, start_response):
    data=json.dumps(body, ensure_ascii=False, separators=(",",":"),
                    allow_nan=False,default=str).encode("utf-8")
    start_response(status,HEADERS+[("Content-Length",str(len(data)))])
    return [data]


def app(environ, start_response):
    method=environ.get("REQUEST_METHOD","GET")
    if method not in ALLOWED_METHODS:
        return _json("405 Method Not Allowed",{"erro":"metodo_nao_suportado"},start_response)
    path=environ.get("PATH_INFO","/")
    if path=="/healthz":
        return _json("200 OK",{"aplicacao":"NIVON","processo":"ONLINE",
                  "consultou_bigquery":False,"go_live_homologado":False},start_response)
    if path in ("/","/terminal.js","/terminal.css"):
        import importlib.resources as resources
        file={"/":"index.html","/terminal.js":"terminal.js",
              "/terminal.css":"terminal.css"}[path]
        try:
            data=resources.files("nivon").joinpath("mvp_web",file).read_bytes()
        except (FileNotFoundError,OSError):
            return _json("404 Not Found",{"erro":"interface_indisponivel"},start_response)
        headers=HTML_HEADERS if path=="/" else (
            [("Content-Type","application/javascript; charset=utf-8")]
            if path.endswith(".js") else [("Content-Type","text/css; charset=utf-8")])
        start_response("200 OK",headers+[("Content-Length",str(len(data)))])
        return [data]
    if path!="/api/v1/resumo":
        return _json("404 Not Found",{"erro":"rota_inexistente"},start_response)
    # Sem segredo forte e gate financeiro, não toca a rede nem BigQuery.
    config=os.environ
    bearer=environ.get("HTTP_AUTHORIZATION","")
    token=bearer[7:] if bearer.startswith("Bearer ") else ""
    if not _auth(token,config):
        return _json("401 Unauthorized",{"erro":"acesso_nao_autorizado"},start_response)
    if config.get("NIVON_MVP_BQ_READ_APPROVED")!="true":
        return _json("503 Service Unavailable",{"erro":"leitura_bigquery_nao_aprovada"},start_response)
    try:
        mes,passagem=_params(environ.get("QUERY_STRING",""))
        result=montar_resumo(projeto=config.get("NIVON_BQ_PROJECT",""),
                            dataset=config.get("NIVON_BQ_DATASET",""),
                            mes=mes,passagem=passagem)
    except (ErroTerminal,ValueError) as exc:
        return _json("400 Bad Request",{"erro":"parametros_invalidos"},start_response)
    except Exception:
        return _json("503 Service Unavailable",{"erro":"consulta_indisponivel"},start_response)
    status="200 OK" if result["consultas_reais_confirmadas"] else "503 Service Unavailable"
    return _json(status,result,start_response)


def main():
    from wsgiref.simple_server import make_server
    addr=os.environ.get("NIVON_MVP_BIND","127.0.0.1")
    if addr not in ("127.0.0.1","localhost"):
        raise RuntimeError("runserver dev permite somente loopback")
    port=int(os.environ.get("PORT","8080"))
    if not 1024<=port<=65535:
        raise ValueError("porta invalida")
    with make_server(addr,port,app) as httpd:
        httpd.serve_forever()


if __name__=="__main__":
    main()
