"""Validação OFFLINE de coerência de lock com hashes e resultado pip-audit JSON.

Não executa pip, não resolve transitivas, não autentica a origem do relatório e
NUNCA homologa instalação, ausência de CVEs ou liberação de produção.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .auditoria_extras import ErroDependencias, analisar_requisito

ROOT = Path(__file__).resolve().parents[2]
MAX_LOCK = 300_000
MAX_REPORT = 1_000_000
MAX_PACKAGES = 2_000
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_LINE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==(\d+(?:\.\d+){0,3})((?:\s+--hash=sha256:[A-Fa-f0-9]{64})+)\Z")
_HASH = re.compile(r"--hash=sha256:([A-Fa-f0-9]{64})")
_VERSION = re.compile(r"\d+(?:\.\d+){0,3}\Z")


class ErroEvidencia(ValueError):
    """Evidência externa ausente, inconsistente, insegura ou fora do contrato."""


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _json_seguro(texto: str) -> dict:
    def pares(valores):
        obj = {}
        for chave, valor in valores:
            if chave in obj:
                raise ErroEvidencia("chave JSON duplicada: " + str(chave))
            obj[chave] = valor
        return obj
    try:
        resultado = json.loads(texto, object_pairs_hook=pares)
    except ErroEvidencia:
        raise
    except (ValueError, TypeError) as exc:
        raise ErroEvidencia("relatório JSON inválido") from exc
    if not isinstance(resultado, dict):
        raise ErroEvidencia("raiz do relatório deve ser objeto")
    return resultado


def _numero_versao(valor: str) -> tuple[int, ...]:
    if not isinstance(valor, str) or not _VERSION.fullmatch(valor):
        raise ErroEvidencia("versão fora do subconjunto auditado")
    pontos = tuple(int(x) for x in valor.split("."))
    return pontos + (0,) * (4 - len(pontos))


def _lock(texto: str) -> dict[str, dict]:
    if not isinstance(texto, str) or len(texto.encode("utf-8")) > MAX_LOCK:
        raise ErroEvidencia("lock grande ou inválido")
    result = {}
    for linha in texto.splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        match = _LINE.fullmatch(linha.strip())
        if not match:
            raise ErroEvidencia("lock exige name==version e hashes sha256 explícitos por linha")
        nome = analisar_requisito(match.group(1) + "==" + match.group(2))["distribution"]
        hashes = _HASH.findall(match.group(3))
        if not hashes or len(set(x.lower() for x in hashes)) != len(hashes):
            raise ErroEvidencia("hash ausente ou duplicado no lock")
        if nome in result or len(result) >= MAX_PACKAGES:
            raise ErroEvidencia("distribuição duplicada ou excesso de pacotes no lock")
        result[nome] = {"version": match.group(2), "hashes_count": len(hashes),
                        "sha256_hashes": tuple(sorted(h.lower() for h in hashes))}
    if not result:
        raise ErroEvidencia("lock vazio")
    return result


def _dentro_do_requisito(version: str, requisito: dict) -> bool:
    alvo = _numero_versao(version)
    for op, ver in requisito["constraints"]:
        atual = _numero_versao(ver)
        if op == "==" and not (alvo == atual):
            return False
        if op == ">=" and not (alvo >= atual):
            return False
        if op == ">" and not (alvo > atual):
            return False
        if op == "<=" and not (alvo <= atual):
            return False
        if op == "<" and not (alvo < atual):
            return False
    return True


def avaliar(pyproject: str, lock: str, relatorio: str, metadados: dict,
            *, agora: datetime | None = None) -> dict:
    """Confere consistência dos artefatos informados; NÃO atesta sua origem."""
    if any(not isinstance(x, str) for x in (pyproject, lock, relatorio)):
        raise ErroEvidencia("artefatos devem ser texto")
    if len(pyproject.encode("utf-8")) > 80_000 or len(relatorio.encode("utf-8")) > MAX_REPORT:
        raise ErroEvidencia("artefato grande demais")
    if not isinstance(metadados, dict):
        raise ErroEvidencia("metadados ausentes")
    for campo, texto in (("pyproject_sha256", pyproject),
                         ("lock_sha256", lock), ("report_sha256", relatorio)):
        hash_recebido = metadados.get(campo)
        if not isinstance(hash_recebido, str) or not _SHA.fullmatch(hash_recebido):
            raise ErroEvidencia("hash obrigatório ausente ou inválido: " + campo)
        if hash_recebido != _sha(texto):
            raise ErroEvidencia("hash de artefato divergente: " + campo)
    if metadados.get("tool") != "pip-audit" or metadados.get("service") not in ("pypi", "osv"):
        raise ErroEvidencia("origem/tipo de auditoria não declarado")
    if type(metadados.get("exit_code")) is not int:
        raise ErroEvidencia("código de saída da ferramenta não registrado")
    selecao = metadados.get("extras")
    if (not isinstance(selecao, list) or not selecao or
            len(selecao) != len(set(x for x in selecao if isinstance(x, str))) or
            any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", x)
                for x in selecao)):
        raise ErroEvidencia("seleção de extras inválida")
    try:
        gerado = datetime.fromisoformat(metadados["generated_at"].replace("Z", "+00:00"))
    except (ValueError, KeyError, AttributeError) as exc:
        raise ErroEvidencia("data de execução da auditoria inválida") from exc
    if gerado.tzinfo is None:
        raise ErroEvidencia("data de auditoria sem fuso horário")
    ref = agora or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        raise ErroEvidencia("agora sem fuso horário")
    if not timedelta(0) <= ref - gerado <= timedelta(hours=24):
        raise ErroEvidencia("auditoria futura ou mais antiga que 24 horas")
    try:
        projeto = tomllib.loads(pyproject)["project"]
        extras = projeto["optional-dependencies"]
        core = projeto.get("dependencies", [])
        if projeto.get("name") != "nivon":
            raise ErroEvidencia("pyproject de outro projeto")
    except (KeyError, TypeError, AttributeError, tomllib.TOMLDecodeError) as exc:
        raise ErroEvidencia("pyproject inválido") from exc
    if not isinstance(extras, dict) or not isinstance(core, list):
        raise ErroEvidencia("grupos de dependências malformados")
    obrigatorios = {}
    for grupo in ["core"] + selecao:
        if grupo != "core" and grupo not in extras:
            raise ErroEvidencia("extra não encontrado no projeto: " + grupo)
        itens = core if grupo == "core" else extras[grupo]
        if not isinstance(itens, list):
            raise ErroEvidencia("grupo inválido: " + grupo)
        for requisito in itens:
            try:
                parsed = analisar_requisito(requisito)
            except ErroDependencias as exc:
                raise ErroEvidencia("requisito direto sem auditoria: " + str(requisito)) from exc
            obrigatorios.setdefault(parsed["distribution"], []).append(parsed)
    packages = _lock(lock)
    for nome, requisitos in obrigatorios.items():
        if nome not in packages:
            raise ErroEvidencia("dependência direta ausente no lock: " + nome)
        if not all(_dentro_do_requisito(packages[nome]["version"], item) for item in requisitos):
            raise ErroEvidencia("versão do lock viola dependência direta: " + nome)
    data = _json_seguro(relatorio)
    if not isinstance(data.get("dependencies"), list) or not isinstance(data.get("fixes"), list):
        raise ErroEvidencia("formato pip-audit JSON incompatível")
    recebidos = {}
    total_vulnerabilidades = 0
    for item in data["dependencies"]:
        if not isinstance(item, dict):
            raise ErroEvidencia("item de auditoria inválido")
        if item.get("skip_reason") is not None:
            raise ErroEvidencia("pacote ignorado na auditoria")
        try:
            nome = analisar_requisito(str(item["name"]) + "==" + str(item["version"]))["distribution"]
        except (ErroDependencias, KeyError) as exc:
            raise ErroEvidencia("pacote de auditoria sem versão reconhecida") from exc
        if nome in recebidos:
            raise ErroEvidencia("pacote duplicado no relatório")
        if not isinstance(item.get("vulns"), list):
            raise ErroEvidencia("vulnerabilidades não declaradas")
        for vuln in item["vulns"]:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str) or not vuln["id"]:
                raise ErroEvidencia("registro de vulnerabilidade incompleto")
        total_vulnerabilidades += len(item["vulns"])
        recebidos[nome] = item["version"]
    if set(recebidos) != set(packages):
        raise ErroEvidencia("inventário auditado não coincide com todas as entradas do lock")
    for nome, item in packages.items():
        if recebidos[nome] != item["version"]:
            raise ErroEvidencia("versão auditada diverge do lock: " + nome)
    if data["fixes"] and not total_vulnerabilidades:
        raise ErroEvidencia("fixes informados sem vulnerabilidade")
    if metadados["exit_code"] != (1 if total_vulnerabilidades else 0):
        raise ErroEvidencia("exit code inconsistente com vulnerabilidades declaradas")
    return {
        "project": "NIVON",
        "evidence_type": "OFFLINE_UNTRUSTED_PIP_AUDIT_REPORT_COHERENCE",
        "selected_extras": sorted(selecao),
        "locked_packages": len(packages),
        "direct_packages_covered": len(obrigatorios),
        "lock_hashes_declared": sum(x["hashes_count"] for x in packages.values()),
        "vulnerabilities_reported": total_vulnerabilidades,
        "reported_no_vulnerabilities": total_vulnerabilidades == 0,
        "report_fresh_within_24h": True,
        "transitive_dependency_closure_verified": False,
        "hashes_downloaded_or_verified": False,
        "audit_origin_authenticated": False,
        "real_vulnerability_scan_performed_by_this_module": False,
        "installed_package_tests_performed": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_SIGNED_ORIGIN_FULL_TRANSITIVE_CLOSURE_AND_INSTALLED_TESTS",
    }


def _arquivo(path: Path, limite: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limite:
        raise ErroEvidencia("arquivo inexistente, symlink ou grande")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ErroEvidencia("arquivo não é UTF-8") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Coerência pip-audit offline, sem execução de pip")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    try:
        meta = _json_seguro(_arquivo(args.metadata, 16_000))
        saida = avaliar(_arquivo(args.root / "pyproject.toml", 80_000),
                        _arquivo(args.lock, MAX_LOCK), _arquivo(args.report, MAX_REPORT), meta)
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"EVIDENCIA_BLOQUEADA: {exc}\n")
    print(json.dumps(saida, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
