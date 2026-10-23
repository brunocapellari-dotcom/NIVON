"""Confere um ZIP de evidências com metadados LIVE do GitHub Actions.

Usa somente stdlib e HTTPS api.github.com quando invocado explicitamente.
Isto prova concordância de metadados com a API e o hash do arquivo LOCAL,
não assinatura Sigstore/SLSA, origem dos wheels dentro do ZIP nem segurança
do runner/lock. Nunca baixa o archive, executa pacote ou autoriza instalação.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path

from .auditoria_evidencias_pacotes import ErroEvidencia

REPO = "brunocapellari-dotcom/NIVON"
API = "https://api.github.com"
WORKFLOW = ".github/workflows/auditoria_pacotes.yml"
ARTIFACT_NAME = "nivon-evidencias-dependencias"
MAX_RESPONSE = 1_000_000
MAX_ARCHIVE = 512 * 1024 * 1024
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_DIGEST = re.compile(r"sha256:([a-f0-9]{64})\Z")


def _json_unico(raw: bytes) -> dict:
    def pares(items):
        result = {}
        for key, val in items:
            if key in result:
                raise ErroEvidencia("resposta GitHub contém chave JSON duplicada")
            result[key] = val
        return result
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
        raise ErroEvidencia("resposta GitHub inválida ou excessiva")
    try:
        out = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pares)
    except ErroEvidencia:
        raise
    except (UnicodeError, ValueError) as exc:
        raise ErroEvidencia("resposta GitHub JSON inválida") from exc
    if not isinstance(out, dict):
        raise ErroEvidencia("resposta GitHub deve ser objeto")
    return out


class _SemRedirecionamentos(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ErroEvidencia("redirecionamento HTTP não autorizado")


def consultar_api(endpoint: str, *, token: str | None = None) -> dict:
    """Requisição read-only a dois endpoints fixos; nenhuma URL arbitrária."""
    if not re.fullmatch(
        r"/repos/brunocapellari-dotcom/NIVON/actions/"
        r"(?:runs/[1-9][0-9]*|artifacts/[1-9][0-9]*)", endpoint,
    ):
        raise ErroEvidencia("endpoint API fora da allowlist")
    if token is not None and (not isinstance(token, str) or
                              not token or "\r" in token or "\n" in token):
        raise ErroEvidencia("token malformado")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "NIVON-offline-artifact-validator/1",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + endpoint, headers=headers, method="GET")
    opener = urllib.request.build_opener(_SemRedirecionamentos)
    try:
        with opener.open(req, timeout=8) as response:
            if response.status != 200 or response.geturl() != API + endpoint:
                raise ErroEvidencia("resposta API inesperada")
            data = response.read(MAX_RESPONSE + 1)
    except ErroEvidencia:
        raise
    except (OSError, urllib.error.URLError, ValueError) as exc:
        # Nunca registrar Authorization nem objeto req com cabeçalhos.
        raise ErroEvidencia("consulta HTTPS autenticada pelo TLS falhou") from exc
    return _json_unico(data)


def _hash_arquivo(path: Path) -> tuple[str, int]:
    if not isinstance(path, Path) or path.is_symlink():
        raise ErroEvidencia("arquivo de evidência symlink ou inválido")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARCHIVE:
                raise ErroEvidencia("evidência não é arquivo regular ou excedeu limite")
            h, size = hashlib.sha256(), 0
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise ErroEvidencia("arquivo grande demais")
                h.update(chunk)
            if size != info.st_size:
                raise ErroEvidencia("arquivo mudou durante a leitura")
            return h.hexdigest(), size
    except OSError as exc:
        raise ErroEvidencia("não foi possível abrir evidência com segurança") from exc


def validar_metadados(run: dict, artifact: dict, digest_local: str, tamanho_local: int,
                      *, run_id: int, artifact_id: int, source_sha: str,
                      workflow: str = WORKFLOW) -> dict:
    """Validação determinística de claims. Dicionários fornecidos NÃO autenticam API."""
    if (type(run_id) is not int or run_id <= 0 or type(artifact_id) is not int
            or artifact_id <= 0 or not isinstance(source_sha, str)
            or not _SHA.fullmatch(source_sha)):
        raise ErroEvidencia("identificadores/commit inválidos")
    if not isinstance(workflow, str) or not re.fullmatch(
        r"\.github/workflows/[a-zA-Z0-9_-]+\.ya?ml", workflow
    ):
        raise ErroEvidencia("workflow esperado inválido")
    if not isinstance(run, dict) or not isinstance(artifact, dict):
        raise ErroEvidencia("metadados de execução/artefato ausentes")
    run_repo = run.get("repository")
    head_repo = run.get("head_repository")
    if (run.get("id") != run_id or type(run.get("id")) is not int
            or not isinstance(run_repo, dict) or run_repo.get("full_name") != REPO
            or not isinstance(head_repo, dict) or head_repo.get("full_name") != REPO
            or run.get("head_sha") != source_sha):
        raise ErroEvidencia("identidade/commit do workflow divergente")
    if (run.get("event") != "workflow_dispatch" or run.get("status") != "completed"
            or run.get("conclusion") != "success"):
        raise ErroEvidencia("execução GitHub não é manual concluída com sucesso")
    # GitHub pode acrescentar @refs/heads/... ao campo path, mas a primeira
    # parte obrigatoriamente precisa ser o arquivo pinado.
    actual_workflow = run.get("path")
    if not isinstance(actual_workflow, str) or actual_workflow.split("@", 1)[0] != workflow:
        raise ErroEvidencia("workflow de evidências não corresponde ao esperado")
    w = artifact.get("workflow_run")
    if (artifact.get("id") != artifact_id or type(artifact.get("id")) is not int
            or artifact.get("name") != ARTIFACT_NAME or artifact.get("expired") is not False
            or not isinstance(w, dict) or type(w.get("id")) is not int
            or w["id"] != run_id or w.get("head_sha") != source_sha
            or w.get("repository_id") != run_repo.get("id")
            or w.get("head_repository_id") != head_repo.get("id")):
        raise ErroEvidencia("artefato não pertence à execução/repositório esperados")
    if (type(tamanho_local) is not int or tamanho_local <= 0 or
            type(artifact.get("size_in_bytes")) is not int or
            artifact["size_in_bytes"] != tamanho_local):
        raise ErroEvidencia("tamanho do ZIP divergente")
    expected = artifact.get("digest")
    match = _DIGEST.fullmatch(expected) if isinstance(expected, str) else None
    if not match or not isinstance(digest_local, str) or match.group(1) != digest_local:
        raise ErroEvidencia("digest SHA256 do ZIP não corresponde ao GitHub")
    return {
        "project": "NIVON",
        "evidence_type": "GITHUB_ACTIONS_API_METADATA_AND_LOCAL_ARCHIVE_DIGEST",
        "workflow_run_id": run_id,
        "artifact_id": artifact_id,
        "github_commit_sha": source_sha,
        "workflow_path": workflow,
        "archive_sha256": digest_local,
        "archive_bytes": tamanho_local,
        "repository": REPO,
        "metadata_coherent": True,
        "artifact_digest_matches_github_api": True,
        "live_api_query_done_by_this_function": False,
        "github_sigstore_attestation_verified": False,
        "slsa_provenance_verified": False,
        "archive_contents_verified": False,
        "third_party_wheel_origin_authenticated": False,
        "workflow_runner_trusted_or_hardened": False,
        "pip_audit_execution_proven": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_SIGNED_ATTESTATION_AND_PACKAGE_AUDITS",
    }


def verificar_github(archive: Path, *, run_id: int, artifact_id: int,
                     source_sha: str, workflow: str = WORKFLOW,
                     token: str | None = None) -> dict:
    """Consulta metadados reais na API TLS e confere o ZIP local contra digest.

    Não recupera o ZIP do GitHub, não valida conteúdo, assinatura/attestation
    criptográfica ou que o executor seja confiável.
    """
    # Rejeitar argumentos inválidos ANTES de fazer qualquer consulta de rede.
    if (type(run_id) is not int or run_id <= 0 or type(artifact_id) is not int
            or artifact_id <= 0 or not isinstance(source_sha, str)
            or not _SHA.fullmatch(source_sha)):
        raise ErroEvidencia("identificadores/commit inválidos")
    digest, size = _hash_arquivo(Path(archive))
    run = consultar_api(f"/repos/{REPO}/actions/runs/{run_id}", token=token)
    art = consultar_api(f"/repos/{REPO}/actions/artifacts/{artifact_id}", token=token)
    result = validar_metadados(run, art, digest, size, run_id=run_id,
                               artifact_id=artifact_id, source_sha=source_sha,
                               workflow=workflow)
    result["live_api_query_done_by_this_function"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Conferir ZIP contra API GitHub Actions, sem instalar")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow", default=WORKFLOW)
    args = parser.parse_args()
    try:
        result = verificar_github(args.archive, run_id=args.run_id,
                                 artifact_id=args.artifact_id, source_sha=args.source_sha,
                                 workflow=args.workflow, token=os.environ.get("GITHUB_TOKEN"))
    except ErroEvidencia as exc:
        parser.exit(2, f"PROVENIENCIA_BLOQUEADA: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
