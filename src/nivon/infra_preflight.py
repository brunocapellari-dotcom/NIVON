"""Inventário de infraestrutura NIVON: validação offline, sem deploy/rede.

Validação da estrutura NÃO é homologação operacional. Um manifesto estático
não constitui prova de que um recurso na nuvem exista ou esteja protegido.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

VALID_STATES = {"VERIFIED_CODE_ONLY", "CODE_ONLY", "NOT_VERIFIED", "NOT_IMPLEMENTED"}
ENV_IDS = {"development", "staging", "production"}
REQUIRED_GATES = {
    "REVIEW_AND_RELEASE", "OCI_ACCOUNT_QUOTAS", "SECRETS_AND_IAM",
    "DURABILITY", "BACKUP_RESTORE", "SOURCE_RIGHTS",
    "REAL_SOURCE_VALIDATION", "REAL_HISTORICAL_BACKTEST",
    "GOVERNED_AGENT_E2E", "AUTH_AND_TLS", "AIS_LINEUP_LICENSED",
    "PUBLISH_AND_PROVIDER", "ALERTS_AND_RECOVERY", "ZERO_COST_PROOF",
    "INDEPENDENT_SECURITY_REVIEW", "OPERATOR_HOMOLOGATION",
}


class InfraError(ValueError):
    """Recusa manifesta de prontidão não comprovada."""


def carregar_inventario(caminho: str | Path | None = None) -> dict:
    if caminho is None:
        caminho = Path(__file__).resolve().parents[2] / "infra" / "inventory.v1.json"
    path = Path(caminho)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000:
        raise InfraError("manifesto ausente, simbólico ou muito grande")

    def pares_sem_duplicatas(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise InfraError("chave JSON duplicada no inventário")
            out[k] = v
        return out

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pares_sem_duplicatas)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InfraError("JSON de infraestrutura inválido") from exc


def validar_inventario(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != "nivon.infrastructure.v1":
        raise InfraError("schema incompatível")
    if doc.get("authority") != "REVIEW_ONLY":
        raise InfraError("documento só pode descrever revisão")
    d = doc.get("deployment")
    if not isinstance(d, dict):
        raise InfraError("bloco de deployment inválido")
    for name, expected in (
        ("authorized", False), ("active", False),
        ("account_resources_verified", False),
        ("quota_and_billing_verified", False),
        ("paid_services_allowed", False),
        ("notebook_dependency_allowed", False),
    ):
        if type(d.get(name)) is not bool or d[name] is not expected:
            raise InfraError("deploy ou capacidade não pode ser presumido: " + name)
    if type(d.get("approved_monthly_brl")) is not int or d["approved_monthly_brl"] != 0:
        raise InfraError("orçamento não autorizado")
    if d.get("provider_candidate") != "ORACLE_CLOUD_ALWAYS_FREE":
        raise InfraError("provedor alterado sem revisão")
    envs = doc.get("environments")
    if not isinstance(envs, list) or {e.get("id") for e in envs if isinstance(e, dict)} != ENV_IDS or len(envs) != len(ENV_IDS):
        raise InfraError("ambientes esperados: development, staging, production")
    for env in envs:
        if type(env.get("runtime_enabled")) is not bool or env["runtime_enabled"]:
            raise InfraError("ambiente foi ligado sem gate")
        if type(env.get("contains_real_sensitive_data")) is not bool or env["contains_real_sensitive_data"]:
            raise InfraError("manifesto não autoriza dados reais em ambiente")
    st = doc.get("storage_policy")
    if not isinstance(st, dict):
        raise InfraError("política de armazenamento ausente")
    for key in ("remote_backup_required", "remote_backup_verified",
                "encrypted_remote_backup_verified",
                "restore_in_separate_environment_verified",
                "public_repository_may_store_real_data"):
        if type(st.get(key)) is not bool:
            raise InfraError("controle de armazenamento inválido: " + key)
    if not st["remote_backup_required"] or any(st[k] for k in (
        "remote_backup_verified", "encrypted_remote_backup_verified",
        "restore_in_separate_environment_verified", "public_repository_may_store_real_data")):
        raise InfraError("backup remoto ou distribuição indevidamente presumida")
    for key in ("raw_path", "state_path", "analytics_path", "model_path", "local_backups_path"):
        val = st.get(key)
        if not isinstance(val, str) or not val.startswith("/") or ".." in Path(val).parts:
            raise InfraError("path de armazenamento inseguro")
    gates = doc.get("release_gates")
    if not isinstance(gates, dict) or not REQUIRED_GATES.issubset(gates):
        raise InfraError("gates mínimos ausentes")
    if any(type(v) is not bool or v for v in gates.values()):
        raise InfraError("gates não devem estar aprovados sem evidência")
    components = doc.get("components")
    if not isinstance(components, list) or len(components) < 10:
        raise InfraError("componentes insuficientes")
    ids = [c.get("id") for c in components if isinstance(c, dict)]
    if len(ids) != len(components) or len(set(ids)) != len(ids) or any(not isinstance(x, str) or not x for x in ids):
        raise InfraError("ID de componente inválido/duplicado")
    graph = {}
    for c in components:
        if c.get("state") not in VALID_STATES or type(c.get("live_enabled")) is not bool or c["live_enabled"]:
            raise InfraError("estado ou ativação de componente inválido")
        if c.get("gate") not in gates:
            raise InfraError("gate de componente desconhecido")
        deps = c.get("depends_on")
        if not isinstance(deps, list) or len(deps) != len(set(deps)) or any(x not in ids for x in deps):
            raise InfraError("dependência ausente/duplicada")
        graph[c["id"]] = deps
    visited, visiting = set(), set()

    def visit(node):
        if node in visiting:
            raise InfraError("ciclo no grafo de dependências")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for key in ids:
        visit(key)
    ev = doc.get("evidence")
    if not isinstance(ev, dict) or ev.get("operational_deployment") != "NOT_VERIFIED" or ev.get("cloud_assets") != "NOT_VERIFIED":
        raise InfraError("evidência operacional presumida")
    if ev.get("synthetic_test_success_does_not_approve_real_data") is not True:
        raise InfraError("testes sintéticos não aprovam dados reais")
    return {
        "status": "BLUEPRINT_VALIDO_OPERACAO_BLOQUEADA",
        "deployment_authorized": False,
        "componentes": len(components),
        "gates_aprovados": 0,
        "cloud_confirmada": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pré-voo NIVON sem rede/deploy")
    parser.add_argument("--manifest", help="arquivo JSON em vez do padrão")
    parser.add_argument("--require-live", action="store_true",
                        help="falhar quando não há liberação operacional")
    args = parser.parse_args(argv)
    try:
        info = validar_inventario(carregar_inventario(args.manifest))
        print(json.dumps(info, ensure_ascii=False, sort_keys=True))
        return 3 if args.require_live else 0
    except (OSError, InfraError) as exc:
        print(json.dumps({"status": "INVALIDO", "erro": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
