"""Aceite real do terminal NIVON no Cloud Run, após deploy autorizado.

Não realiza deploy, altera IAM ou cria recursos. Uma verificação autenticada
do PROCESSO não é suficiente: valida resposta observada do BigQuery e o limite
faturável após leitura. Nenhum token, dado bruto ou URL de serviço em logs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

PROJECT = "nivon-data"
REGION = "southamerica-east1"
SERVICE = "nivon-terminal"
MAX_BYTES_BILLED = 250_000_000
MAX_RESPONSE = 512_000
HOST = re.compile(r"nivon-terminal-[a-z0-9-]{4,100}\Z")
COMPETENCE = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])\Z")


class AceiteBloqueado(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise AceiteBloqueado("resposta HTTP redirecionada")


def validar_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 230:
        raise AceiteBloqueado("URL do serviço inválida")
    try:
        u = urlsplit(url)
        hostname = u.hostname or ""
        suffix = (".a.run.app", "." + REGION + ".run.app")
        matched = next((s for s in suffix if hostname.endswith(s)), None)
        label = hostname[:-len(matched)] if matched else ""
        if (u.scheme != "https" or matched is None or not HOST.fullmatch(label)
            or u.username or u.password or u.port is not None
            or u.path not in ("", "/") or u.query or u.fragment):
            raise AceiteBloqueado("Cloud Run privado fora do domínio homologado")
    except (ValueError, TypeError) as exc:
        raise AceiteBloqueado("URL Cloud Run malformada") from exc
    return url.rstrip("/")


def _comando(args: list[str], *, run=subprocess.run, timeout=25) -> str:
    try:
        p = run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=timeout, check=False)
        if p.returncode or not isinstance(p.stdout, str) or len(p.stdout) > 100_000:
            raise AceiteBloqueado("metadados ou token indisponíveis")
        return p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AceiteBloqueado("comando de leitura GCP indisponível") from exc


def metadados_e_token(*, run=subprocess.run):
    svc = _comando([
        "gcloud", "run", "services", "describe", SERVICE,
        "--project=" + PROJECT, "--region=" + REGION, "--format=json",
    ], run=run)
    policy = _comando([
        "gcloud", "run", "services", "get-iam-policy", SERVICE,
        "--project=" + PROJECT, "--region=" + REGION, "--format=json",
    ], run=run)
    try:
        data = json.loads(svc)
        iam = json.loads(policy)
        if not isinstance(data, dict) or not isinstance(iam, dict):
            raise ValueError("estrutura não objeto")
        name = (data.get("metadata") or {}).get("name")
        labels = (data.get("metadata") or {}).get("labels") or {}
        identity = (((data.get("spec") or {}).get("template") or {}).get("spec") or {}).get("serviceAccountName")
        status = data.get("status") or {}
        url = validar_url(status.get("url"))
        conditions = status.get("conditions") or []
        ready = any(x.get("type") == "Ready" and x.get("status") == "True"
                    for x in conditions if isinstance(x, dict))
        if (name != SERVICE or labels.get("nivon-component") != "terminal"
            or not isinstance(identity, str) or not identity.endswith("@" + PROJECT + ".iam.gserviceaccount.com")
            or not ready):
            raise AceiteBloqueado("identidade, rótulo ou prontidão Cloud Run inválidos")
        bindings = iam.get("bindings") or []
        if not isinstance(bindings, list):
            raise AceiteBloqueado("política IAM inválida")
        if any((not isinstance(b, dict)) or
               (b.get("role") == "roles/run.invoker" and
                bool(set(b.get("members") or ()) & {"allUsers", "allAuthenticatedUsers"}))
               for b in bindings):
            raise AceiteBloqueado("acesso público ou política IAM inválida")
    except (ValueError, TypeError, AttributeError) as exc:
        raise AceiteBloqueado("metadados Cloud Run não comprovados") from exc
    token = _comando(["gcloud","auth","print-identity-token",
                      "--audiences=" + url], run=run)
    if not 64 <= len(token) <= 8192 or any(c.isspace() for c in token):
        raise AceiteBloqueado("token de identidade inválido")
    return url, token


def _ler(url: str, token: str, path: str, *, opener=None, timeout=20) -> bytes:
    if path not in ("/", "/healthz", "/api/v1/ferrovia"):
        raise AceiteBloqueado("rota não homologada")
    req = Request(url + path, headers={
        "Authorization": "Bearer " + token,
        "Accept": "text/html" if path == "/" else "application/json",
        "User-Agent": "NIVON-Private-GoLive-Acceptance/0.1",
    }, method="GET")
    op = opener or build_opener(_NoRedirect())
    try:
        with op.open(req, timeout=timeout) as res:
            if res.status != 200 or res.geturl() != url + path:
                raise AceiteBloqueado("resposta privada inválida")
            mime = res.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
            if mime != ("text/html" if path == "/" else "application/json"):
                raise AceiteBloqueado("MIME de resposta incompatível")
            raw = res.read(MAX_RESPONSE + 1)
            if not 0 < len(raw) <= MAX_RESPONSE:
                raise AceiteBloqueado("resposta inválida ou acima do limite")
            return raw
    except AceiteBloqueado:
        raise
    except (OSError, HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise AceiteBloqueado("leitura autenticada do terminal indisponível") from exc


def _json(raw: bytes) -> dict:
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise AceiteBloqueado("resposta JSON inválida") from exc
    if not isinstance(d, dict):
        raise AceiteBloqueado("JSON não objeto")
    return d


def validar_payload(health: bytes, page: bytes, body: bytes,
                    *, now: datetime) -> dict:
    if _json(health) != {"estado": "PROCESSO_ATIVO"}:
        raise AceiteBloqueado("health não atesta processo")
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise AceiteBloqueado("relógio não confiável")
    if b"NIVON" not in page or b"Carregando dados reais" not in page:
        raise AceiteBloqueado("interface web divergente")
    d = _json(body)
    if (d.get("estado") != "ANTT_SERIE_OBSERVADA_DECLARADA" or
        d.get("natureza") != "OBSERVADO_DECLARADO" or
        d.get("status_publicacao") != "PREVIA_PRIVADA" or
        d.get("homologacao_editorial") is not False or
        d.get("soma_multimodal_permitida") is not False or
        d.get("point_in_time_historico") is not False or
        "ANTT/SIADE" not in str(d.get("fonte", ""))):
        raise AceiteBloqueado("fonte/epistemologia do BigQuery não homologadas")
    series = d.get("serie")
    anos = d.get("anos")
    if (not isinstance(series, list) or not isinstance(anos, int) or isinstance(anos, bool)
        or not 1 <= anos <= 35 or len(series) != anos):
        raise AceiteBloqueado("série histórica incompleta")
    if anos != now.year - 2006 + 1 or not 2006 <= now.year <= 2040:
        raise AceiteBloqueado("janela de série ferroviária divergente")
    acc_tu = Decimal(0)
    acc_od = 0
    for index, row in enumerate(series):
        if not isinstance(row, dict) or row.get("ano") != 2006 + index:
            raise AceiteBloqueado("ano não sequencial")
        if (not isinstance(row.get("registros"), int) or isinstance(row["registros"], bool)
            or row["registros"] <= 0):
            raise AceiteBloqueado("contagem ferroviária inválida")
        try:
            tu = Decimal(str(row["toneladas_uteis"]))
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise AceiteBloqueado("tonelagem não numérica") from exc
        if not tu.is_finite() or tu <= 0:
            raise AceiteBloqueado("tonelagem inválida")
        comp = row.get("ultima_competencia")
        if not isinstance(comp, str) or not COMPETENCE.fullmatch(comp) or not comp.startswith(str(row["ano"])):
            raise AceiteBloqueado("competência ferroviária incorreta")
        acc_tu += tu
        acc_od += row["registros"]
    if d.get("ultima_competencia") != series[-1]["ultima_competencia"]:
        raise AceiteBloqueado("competência agregada divergente")
    if d["ultima_competencia"] > now.strftime("%Y-%m"):
        raise AceiteBloqueado("competência futura")
    if not isinstance(d.get("registros_acumulados"), int) or d["registros_acumulados"] != acc_od:
        raise AceiteBloqueado("contagem acumulada divergente")
    try:
        total = Decimal(str(d["tu_acumuladas"]))
        collected = datetime.fromisoformat(d["ultima_coleta_utc"])
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise AceiteBloqueado("dados de fechamento ou coleta inválidos") from exc
    if total != acc_tu or collected.utcoffset() is None or collected > now:
        raise AceiteBloqueado("inconsistência total ou coleta futura")
    billed = d.get("bytes_processados_ultimo_job")
    if billed is not None and (not isinstance(billed, int) or isinstance(billed, bool) or
                               not 0 <= billed <= MAX_BYTES_BILLED):
        raise AceiteBloqueado("limite faturável divergente")
    return {
        "estado": "VALIDACAO_PRIVADA_TECNICA_COMPLETA",
        "projeto": PROJECT, "regiao": REGION, "servico": SERVICE,
        "http": "GET_ONLY_IAM_AUTHENTICATED",
        "endpoint_bigquery_observado": True,
        "anos": anos, "primeiro_ano": 2006, "ultimo_ano": series[-1]["ano"],
        "ultima_competencia": d["ultima_competencia"],
        "max_bytes_billed_per_query": MAX_BYTES_BILLED,
        "dados_fabricados_aceitos": False,
        "permissoes_publicas": False,
        "go_live_publico": False,
        "certificacao_direitos_completa": False,
    }


def aceitar(url: str, token: str, *, opener=None, now=None) -> dict:
    url = validar_url(url)
    current = now or datetime.now(timezone.utc)
    health = _ler(url, token, "/healthz", opener=opener)
    page = _ler(url, token, "/", opener=opener)
    data = _ler(url, token, "/api/v1/ferrovia", opener=opener, timeout=105)
    return validar_payload(health, page, data, now=current)


def main(argv=None) -> int:
    argparse.ArgumentParser(description="Aceite Cloud Run privado pós-deploy").parse_args(argv)
    if (os.environ.get("GITHUB_REF") != "refs/heads/main" or
        os.environ.get("NIVON_GO_LIVE_DEPLOY_APPROVED") != "true" or
        os.environ.get("NIVON_GCP_COST_REVIEWED") != "true"):
        print("ACEITE_REAL_BLOQUEADO_SEM_DEPLOY_E_CUSTO_APROVADOS")
        return 3
    try:
        url, token = metadados_e_token()
        report = aceitar(url, token)
    except (AceiteBloqueado, OSError, ValueError):
        print("ACEITE_PRIVADO_REPROVADO_METADADOS_IAM_TOKEN_OU_DADOS")
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
