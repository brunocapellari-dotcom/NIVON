"""Descoberta controlada de conjuntos ANTT com dados estruturados MDF-e.
Catálogo CKAN é só metadado; NÃO é uma série de toneladas coletada.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

API = "https://dados.antt.gov.br/api/3/action/package_search"
QUERIES = ("mdfe", "mdf-e", "movimentação de cargas", "movimentacao de cargas")
MAX_BODY = 2_000_000

class ErroCatalogoANTT(ValueError):
    pass

class SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _norm(v):
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()

def _safe_csv(url):
    if not isinstance(url, str):
        return False
    p = urlsplit(url)
    return (
        p.scheme == "https" and p.hostname == "dados.antt.gov.br"
        and not p.username and not p.password and not p.query and not p.fragment
        and p.port in (None, 443)
        and re.fullmatch(r"/dataset/[^/]+/resource/[^/]+/download/[^/]+\.csv", p.path, re.I) is not None
    )

def _request(q, opener):
    if not isinstance(q, str) or q not in QUERIES:
        raise ErroCatalogoANTT("consulta não permitida")
    url = API + "?" + urlencode({"q": q, "rows": 50, "start": 0})
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "NIVON/0.1 pesquisa-nao-comercial"})
    with opener.open(req, timeout=20) as resp:
        mime = str(resp.headers.get("Content-Type", "")).split(";")[0].lower().strip()
        if resp.status != 200 or resp.geturl() != url or mime != "application/json":
            raise ErroCatalogoANTT("resposta CKAN inválida")
        raw = resp.read(MAX_BODY + 1)
    if not 0 < len(raw) <= MAX_BODY:
        raise ErroCatalogoANTT("resposta CKAN grande ou vazia")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as e:
        raise ErroCatalogoANTT("JSON CKAN inválido") from e
    if payload.get("success") is not True or not isinstance(payload.get("result", {}).get("results"), list):
        raise ErroCatalogoANTT("estrutura CKAN inválida")
    result = payload["result"]
    if len(result["results"]) > 50 or type(result.get("count")) is not int or result["count"] < 0:
        raise ErroCatalogoANTT("metadados CKAN excedem limites")
    return result

def inspecionar(resultados):
    """Classificar catálogo sem seguir links nem inferir conteúdo de CSV."""
    if not isinstance(resultados, list):
        raise ErroCatalogoANTT("lista esperada")
    achados = {}
    for obj in resultados:
        if not isinstance(obj, dict):
            continue
        ident = str(obj.get("id") or "")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", ident):
            continue
        rotulo = str(obj.get("title") or "")[:240]
        descricao = str(obj.get("notes") or "")[:2000]
        contexto = _norm(rotulo + " " + descricao + " " + str(obj.get("name") or ""))
        # Não converter trânsito ferroviário, RNTRC ou CIOT em toneladas do MDF-e.
        mention = ("mdfe" in contexto.replace(" ", "") or "manifesto eletronico de documentos fiscais" in contexto)
        resources = obj.get("resources")
        if not isinstance(resources, list):
            resources = []
        csv_urls = sorted({
            r["url"] for r in resources
            if isinstance(r, dict) and _norm(r.get("format")) == "csv" and _safe_csv(r.get("url"))
        })
        kind = "CATALOGO_SEM_PROVA_MDFE"
        if mention:
            kind = "MDFE_COM_CSV_CANDIDATO_NAO_HOMOLOGADO" if csv_urls else "MDFE_SEM_CSV_VALIDO_NO_CATALOGO"
        achados[ident] = {
            "dataset_id": ident, "titulo": rotulo,
            "classificacao": kind,
            "recursos_csv_oficiais": csv_urls,
            "atualizado_metadata": str(obj.get("metadata_modified") or "")[:40],
            "licenca_declarada": str(obj.get("license_id") or "")[:100],
        }
    return sorted(achados.values(), key=lambda x: (x["classificacao"], x["dataset_id"]))

def descobrir(*, opener=None, agora=None):
    cliente = opener or build_opener(SemRedirect())
    all_raw, execucoes, total_resultados = [], [], 0
    for query in QUERIES:
        data = _request(query, cliente)
        all_raw.extend(data["results"])
        total_resultados += len(data["results"])
        execucoes.append({
            "termo": query, "total_encontrado": data["count"],
            "retornado": len(data["results"]),
            "consulta_parcial": data["count"] > len(data["results"]),
        })
    entries = inspecionar(all_raw)
    candidates = [x for x in entries if x["classificacao"] == "MDFE_COM_CSV_CANDIDATO_NAO_HOMOLOGADO"]
    instante = (agora or datetime.now(timezone.utc)).isoformat()
    return {
        "dataset_id": "ANTT_MDFE_CKAN_DISCOVERY",
        "coletado_em": instante,
        "status": "CANDIDATOS_PARA_HOMOLOGACAO" if candidates else "SEM_CSV_MDFE_IDENTIFICADO_NO_ESCOPO",
        "esgotou_catalogo": not any(q["consulta_parcial"] for q in execucoes),
        "termos": execucoes,
        "datasets_unicos": len(entries),
        "candidatos_csv_mdfe": len(candidates),
        "registros_catalogo": entries,
        "nao_equivale_a": "VOLUME_RODOVIARIO_OBSERVADO",
        "fonte": API,
    }

def gravar_json_atomic(path, resultado):
    alvo = Path(path)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_name(alvo.name + ".tmp")
    try:
        tmp.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(alvo)
    finally:
        tmp.unlink(missing_ok=True)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Consultar 4 termos no catálogo oficial ANTT, sem downloads de dados.")
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)
    try:
        resultado = descobrir()
        gravar_json_atomic(args.output, resultado)
        print(json.dumps({k: resultado[k] for k in (
            "dataset_id", "status", "datasets_unicos", "candidatos_csv_mdfe", "esgotou_catalogo"
        )}, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Não divulgar payload ou URL dinâmica de terceiros.
        resultado = {"dataset_id": "ANTT_MDFE_CKAN_DISCOVERY",
                     "status": "ERRO_AQUISICAO_NAO_EQUIVALE_A_AUSENCIA",
                     "coletado_em": datetime.now(timezone.utc).isoformat(),
                     "tipo_erro": type(exc).__name__}
        gravar_json_atomic(args.output, resultado)
        print(json.dumps(resultado, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
