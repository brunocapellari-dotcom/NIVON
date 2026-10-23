"""Auditoria offline do inventário de tecnologias; sem imports de terceiros ou rede."""
from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ARQUIVO_IVO = "config/ivo_ferramentas_github.v1.json"
ARQUIVO_DELTA = "config/pesquisa_tecnologica_delta.v1.json"
POLITICA = "DENY_INSTALL_EXECUTION_AND_DEPLOY_UNTIL_INDEPENDENT_REVIEW"
DECISOES = frozenset({"ADOPT", "EVALUATE", "BENCHMARK", "RESERVE", "REJECT"})
GATES = ("license_reviewed", "security_reviewed", "dependencies_reviewed", "benchmark_passed")
ID_RE = re.compile(r"[A-Z][A-Z0-9_]{2,60}\Z")
REPO_RE = re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
DIST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class ErroPesquisa(ValueError):
    """Manifesto incompleto ou inconsistente; falha fechada."""


def _json_local(raiz: Path, relativo: str) -> dict:
    p = raiz / relativo
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 200_000:
        raise ErroPesquisa(f"manifesto ausente, link simbólico ou grande: {relativo}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroPesquisa(f"JSON inválido: {relativo}") from exc
    if not isinstance(data, dict):
        raise ErroPesquisa(f"raiz JSON inválida: {relativo}")
    return data


def _repo(url: str) -> str:
    if not isinstance(url, str):
        raise ErroPesquisa("URL de repositório não é texto")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or
            parsed.query or parsed.fragment or not REPO_RE.fullmatch(parsed.path) or
            parsed.path.endswith(".git")):
        raise ErroPesquisa(f"repositório GitHub inválido: {url}")
    return parsed.path.casefold()


def _normalizar_distribuicao(nome: str) -> str:
    if not isinstance(nome, str) or not DIST_RE.fullmatch(nome):
        raise ErroPesquisa("distribuição Python inválida")
    return re.sub(r"[-_.]+", "-", nome).lower()


def _deps_pyproject(toml_texto: str) -> set[str]:
    try:
        doc = tomllib.loads(toml_texto)
        project = doc["project"]
        deps = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            deps.extend(extra)
    except (tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ErroPesquisa("pyproject inválido") from exc
    nomes = set()
    for item in deps:
        if not isinstance(item, str):
            raise ErroPesquisa("dependência não textual")
        m = re.match(r"\s*([A-Za-z0-9_.-]+)", item)
        if not m:
            raise ErroPesquisa("dependência inválida")
        nomes.add(_normalizar_distribuicao(m.group(1)))
    return nomes


def validar_catalogos(ivo: dict, delta: dict, pyproject: str) -> dict:
    """Valida inventário unificado sem presumir instalação, licença ou homologação."""
    if ivo.get("project") != "NIVON" or not isinstance(ivo.get("components"), list):
        raise ErroPesquisa("catálogo IVO inválido")
    if (delta.get("project") != "NIVON" or delta.get("schema_version") != "1.0" or
            delta.get("extends") != ARQUIVO_IVO or delta.get("policy") != POLITICA or
            not isinstance(delta.get("candidates"), list)):
        raise ErroPesquisa("contrato de pesquisa inválido ou política permissiva")
    ids: set[str] = set()
    repos: set[str] = set()
    for item in ivo["components"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ErroPesquisa("componente IVO malformado")
        key = _repo(item.get("repository"))
        ident = item["id"]
        if ident in ids or key in repos:
            raise ErroPesquisa("catálogo IVO contém duplicação")
        ids.add(ident)
        repos.add(key)
    deps = _deps_pyproject(pyproject)
    resumo = []
    for item in delta["candidates"]:
        if not isinstance(item, dict):
            raise ErroPesquisa("candidato não é objeto")
        ident = item.get("id")
        if not isinstance(ident, str) or not ID_RE.fullmatch(ident) or ident in ids:
            raise ErroPesquisa("ID duplicado ou inválido")
        ids.add(ident)
        repo = _repo(item.get("repository"))
        if repo in repos:
            raise ErroPesquisa(f"repositório já catalogado: {ident}")
        repos.add(repo)
        if item.get("decision") not in DECISOES or item.get("priority") not in ("P0", "P1", "P2"):
            raise ErroPesquisa(f"decisão ou prioridade inválida: {ident}")
        for field in ("purpose", "license_declared", "evidence_url", "overlap", "next_experiment"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ErroPesquisa(f"campo obrigatório ausente: {ident}.{field}")
        evidence = urlsplit(item["evidence_url"])
        if (evidence.scheme != "https" or evidence.netloc != "github.com" or
                not evidence.path.casefold().startswith(repo + "/") or evidence.query or evidence.fragment):
            raise ErroPesquisa(f"evidência sem origem confiável: {ident}")
        try:
            reviewed_on = date.fromisoformat(item["reviewed_on"])
        except (TypeError, KeyError, ValueError) as exc:
            raise ErroPesquisa(f"data de revisão inválida: {ident}") from exc
        if reviewed_on > date.today():
            raise ErroPesquisa(f"revisão no futuro: {ident}")
        if not isinstance(item.get("allow_install"), bool) or item["allow_install"]:
            raise ErroPesquisa(f"instalação não autorizada: {ident}")
        for gate in GATES:
            if not isinstance(item.get(gate), bool):
                raise ErroPesquisa(f"gate de revisão inválido: {ident}.{gate}")
        if item["decision"] == "ADOPT" and not all(item[k] for k in GATES):
            raise ErroPesquisa(f"adoção sem gates completos: {ident}")
        package = _normalizar_distribuicao(item.get("python_distribution"))
        if package in deps and item["decision"] != "REJECT":
            # O pacote já está declarado no pyproject. Não criar segundo adaptador.
            raise ErroPesquisa(f"distribuição já declarada; revisar duplicidade: {ident}")
        faltantes = [k for k in GATES if not item[k]]
        resumo.append({"id": ident, "priority": item["priority"],
                       "decision": item["decision"], "package": package,
                       "gates_missing": faltantes, "install_enabled": False})
    counts = Counter(x["decision"] for x in resumo)
    return {"project": "NIVON", "policy": POLITICA, "base_catalog_items": len(ivo["components"]),
            "research_delta_items": len(resumo), "total_unique_repositories": len(repos),
            "declared_python_dependencies": len(deps), "auto_install_enabled": False,
            "decisions": dict(sorted(counts.items())),
            "candidates": sorted(resumo, key=lambda x: (x["priority"], x["id"]))}


def auditar(raiz: Path = ROOT) -> dict:
    ivo = _json_local(raiz, ARQUIVO_IVO)
    delta = _json_local(raiz, ARQUIVO_DELTA)
    pyproject = raiz / "pyproject.toml"
    if pyproject.is_symlink() or not pyproject.is_file() or pyproject.stat().st_size > 100_000:
        raise ErroPesquisa("pyproject ausente ou inválido")
    return validar_catalogos(ivo, delta, pyproject.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventário de pesquisa NIVON, somente leitura")
    parser.add_argument("--resumo", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report = auditar(args.root)
    except (ErroPesquisa, UnicodeError) as exc:
        parser.exit(2, f"PESQUISA_BLOQUEADA: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.resumo else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
