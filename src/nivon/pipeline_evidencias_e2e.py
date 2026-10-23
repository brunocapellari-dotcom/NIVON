"""NIVON: smoke operacional ponta a ponta da cadeia de evidências, OFFLINE.

Cria e executa um pipeline completo com wheels 100% SINTÉTICOS:
METADATA -> RECORD -> SHA256 do wheel -> lock -> relatório simulado ->
validação Requires-Dist -> inventário de licenças -> gate fail-closed ->
controles adversariais -> relatório e ZIP de proveniência sintética.

NÃO baixa, instala, importa pacotes externos ou executa scanner CVE real.
Não é homologação e nunca autoriza instalação/produção. O propósito é
executar o encadeamento integrado na CI, em vez de somente testar módulos.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .auditoria_artefatos_pacotes import verificar_cadeia
from .auditoria_evidencias_pacotes import ErroEvidencia
from .pacote_proveniencia_sintetico import REPO, criar_pacote, verificar_pacote

_SHA = re.compile(r"[0-9a-f]{40}\Z")
PACKAGES = (("duckdb", "1.2.3", ("numpy (>=1,<3)",)),
            ("numpy", "2.0.0", ()))
ALL_FALSE = ("approved_for_install", "approved_for_production",
             "audit_executor_authenticated", "declared_lock_origin_authenticated",
             "vulnerability_service_live_queried", "legal_license_review_completed",
             "resolver_transitive_closure_attested")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _wheel(package: str, version: str, requirements: tuple[str, ...]) -> bytes:
    """Gera ZIPs fictícios localmente; distribuição nunca instalada."""
    prefix = f"{package}-{version}.dist-info"
    meta = [
        "Metadata-Version: 2.4",
        f"Name: {package}",
        f"Version: {version}",
        "License-Expression: MIT",
        "License-File: LICENSE",
    ]
    meta.extend(f"Requires-Dist: {req}" for req in requirements)
    members = {
        prefix + "/METADATA": ("\n".join(meta) + "\n").encode("utf-8"),
        prefix + "/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
        prefix + "/licenses/LICENSE": b"SYNTHETIC LICENSE TEXT NOT A REAL THIRD-PARTY LICENSE\n",
        package + "/__init__.py": b"# synthetic evidence, never execute\n",
    }
    buffer = io.StringIO(newline="")
    rows = []
    for name, raw in members.items():
        value = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        rows.append((name, "sha256=" + value, str(len(raw))))
    rows.append((prefix + "/RECORD", "", ""))
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in members.items():
            z.writestr(name, raw)
        z.writestr(prefix + "/RECORD", buffer.getvalue().encode("utf-8"))
    return out.getvalue()


def executar(pyproject: bytes, *, source_sha: str, run_id: int, output: Path) -> dict:
    """Executa etapas E2E e grava evidências locais se TODAS forem aprovadas.

    Acesso à saída só depois da validação dos controles; sem overwrites.
    """
    if not isinstance(pyproject, bytes) or not pyproject or len(pyproject) > 80_000:
        raise ErroEvidencia("pyproject ausente ou grande demais")
    if not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha) or (
            type(run_id) is not int or run_id <= 0):
        raise ErroEvidencia("referência de execução inválida")
    if not isinstance(output, Path) or output.exists() or output.is_symlink():
        raise ErroEvidencia("saída já existe, não sobrescrever")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ErroEvidencia("diretório pai da saída inexistente/inseguro")
    try:
        project = pyproject.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ErroEvidencia("pyproject não é UTF-8") from exc
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="nivon-e2e-") as tmp:
        wheelhouse = Path(tmp)
        lock_lines = []
        entries = []
        for name, version, requires in PACKAGES:
            data = _wheel(name, version, requires)
            filename = f"{name}-{version}-py3-none-any.whl"
            (wheelhouse / filename).write_bytes(data)
            lock_lines.append(f"{name}=={version} --hash=sha256:{_digest(data)}\n")
            entries.append({"name": name, "version": version, "vulns": []})
        lock = "".join(lock_lines)
        report = json.dumps({"dependencies": entries, "fixes": []},
                            separators=(",", ":"), sort_keys=True)
        metadata = {
            "pyproject_sha256": _digest(pyproject),
            "lock_sha256": _digest(lock.encode("utf-8")),
            "report_sha256": _digest(report.encode("utf-8")),
            "generated_at": now.isoformat(),
            "tool": "pip-audit",
            "service": "pypi",
            "exit_code": 0,
            "extras": ["ivo-query"],
        }
        positive = verificar_cadeia(project, lock, report, metadata,
                                   wheelhouse, agora=now)
        if (positive.get("wheels_hash_verified") != len(PACKAGES) or
                positive.get("supported_wheel_dependencies_checked") != 2 or
                positive.get("license_files_declared") != len(PACKAGES) or
                any(positive.get(field) is not False for field in ALL_FALSE)):
            raise ErroEvidencia("gate E2E não provou contrato de segurança")

        # Controle adversarial REALMENTE EXECUTADO: ZIP adulterado após lock,
        # mesmo que CSV/RECORD interno pareça plausível.
        target = wheelhouse / "duckdb-1.2.3-py3-none-any.whl"
        original = target.read_bytes()
        target.write_bytes(original + b"tampered-after-lock")
        tamper_rejected = False
        try:
            verificar_cadeia(project, lock, report, metadata, wheelhouse, agora=now)
        except ErroEvidencia:
            tamper_rejected = True
        finally:
            target.write_bytes(original)
        if not tamper_rejected:
            raise ErroEvidencia("controle adversarial E2E permitiu wheel adulterado")

        # Controle adversarial: relatório parcial, inclusive com hash novo
        # informado pelo próprio operador, não cobre todas as distribuições.
        partial = json.dumps({"dependencies": entries[:1], "fixes": []},
                             separators=(",", ":"), sort_keys=True)
        changed_metadata = {**metadata, "report_sha256": _digest(partial.encode())}
        incomplete_rejected = False
        try:
            verificar_cadeia(project, lock, partial, changed_metadata,
                             wheelhouse, agora=now)
        except ErroEvidencia:
            incomplete_rejected = True
        if not incomplete_rejected:
            raise ErroEvidencia("controle adversarial aceitou cobertura parcial")

    synthetic_archive = criar_pacote(
        pyproject, repo=REPO, source_sha=source_sha, run_id=run_id)
    archive_check = verificar_pacote(
        synthetic_archive, repo=REPO, source_sha=source_sha, run_id=run_id)
    if archive_check["approved_for_production"] is not False:
        raise ErroEvidencia("arquivo de proveniência não pode autorizar produção")

    summary = {
        "project": "NIVON",
        "run_type": "E2E_SYNTHETIC_INTEGRATION_NOT_REAL_AUDIT",
        "source_sha": source_sha,
        "workflow_run_id": run_id,
        "generated_utc": now.isoformat(),
        "steps_executed": [
            "build_two_fake_wheels_with_record_and_license",
            "generate_synthetic_lock_and_fake_pip_audit_json",
            "validate_record_wheel_sha256_and_metadata",
            "validate_supported_requires_dist_closure",
            "inventory_local_license_files",
            "reject_tampered_wheel",
            "reject_incomplete_scan_report_even_with_updated_hash",
            "generate_and_reverify_synthetic_provenance_zip",
        ],
        "synthetic_wheels_processed": positive["wheels_hash_verified"],
        "supported_dependencies_checked": positive["supported_wheel_dependencies_checked"],
        "license_files_verified": positive["license_files_declared"],
        "tampered_wheel_rejected": tamper_rejected,
        "incomplete_report_rejected": incomplete_rejected,
        "provenance_zip_sha256": archive_check["zip_sha256"],
        "provenance_zip_bytes": archive_check["zip_bytes"],
        "real_wheels_downloaded": False,
        "real_pip_audit_executed": False,
        "real_cve_database_queried": False,
        "real_license_approval_granted": False,
        "github_sigstore_attestation_verified": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_SYNTHETIC_END_TO_END_EXECUTION_ONLY",
    }
    output.mkdir(mode=0o700)
    try:
        (output / "proveniencia_sintetica.zip").write_bytes(synthetic_archive)
        (output / "resumo_integracao.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        (output / "sha256sums.txt").write_text(
            archive_check["zip_sha256"] + "  proveniencia_sintetica.zip\n",
            encoding="ascii")
    except BaseException:
        # Evita deixar evidências incompletas que possam ser confundidas
        # com uma execução aprovada.
        for file in output.iterdir():
            if file.is_file():
                file.unlink()
        output.rmdir()
        raise
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Executar cadeia E2E NIVON com fixtures reais em bytes sintéticos")
    parser.add_argument("--pyproject", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.pyproject.is_symlink() or not args.pyproject.is_file():
            raise ErroEvidencia("pyproject ausente ou symlink")
        summary = executar(args.pyproject.read_bytes(), source_sha=args.source_sha,
                          run_id=args.run_id, output=args.output)
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"E2E_BLOQUEADO: {exc}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
