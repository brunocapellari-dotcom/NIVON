"""Ensaio OFFLINE de backup Restic cifrado e restore SQLite com dados sintéticos.

NÃO cria backup remoto, não lê dados de produção, não configura timers.
A senha é efêmera em arquivo privado; nenhum segredo entra no GitHub.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .pacote_recuperacao import criar_pacote_recuperacao, testar_restore_pacote, ErroPacote


class ErroRestic(ValueError):
    """Interrompe o ensaio sem propagar dados secretos para logs."""


_BLOQUEIOS = (
    "NIVON_RUNTIME_ENABLED", "NIVON_COLLECTORS_ENABLED",
    "NIVON_PUBLICATION_ENABLED", "NIVON_BACKUP_ENABLED",
)


def _guardas(ambiente: dict[str, str]) -> None:
    for chave in _BLOQUEIOS:
        if ambiente.get(chave, "false") != "false":
            raise ErroRestic("operação real bloqueada: " + chave)


def _comando(restic: str, args: list[str], *, ambiente: dict[str, str], pasta: Path) -> str:
    """Somente argv pré-definidos, sem shell ou passthrough de credenciais."""
    permitido = {"init", "backup", "check", "restore", "snapshots"}
    if not args or args[0] not in permitido:
        raise ErroRestic("comando de Restic não permitido")
    try:
        proc = subprocess.run(
            [restic, "--no-cache", *args], cwd=pasta, env=ambiente,
            capture_output=True, text=True, timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErroRestic("execução Restic indisponível: " + args[0]) from exc
    if proc.returncode:
        # Não incluir stdout/stderr, pois podem conter informações de ambiente.
        raise ErroRestic("Restic falhou na fase " + args[0]
                        + " (status " + str(proc.returncode) + ")")
    return proc.stdout


def _criar_fixture(pasta: Path) -> dict:
    """Dados artificiais com resultado conhecido, não consultar histórico NIVON."""
    if pasta.exists() or pasta.is_symlink():
        raise ErroRestic("fixture já existe")
    pasta.mkdir(mode=0o700)
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE synthetic_records (id INTEGER PRIMARY KEY, valor TEXT NOT NULL)")
        db.executemany("INSERT INTO synthetic_records (valor) VALUES (?)",
                       [("TEST_ONLY_1",), ("TEST_ONLY_2",), ("TEST_ONLY_3",)])
        db.execute("PRAGMA user_version=1")
        # SQLite backup() pode aguardar indefinidamente com escrita pendente.
        db.commit()
        return criar_pacote_recuperacao(db, pasta, nome="nivon-sintetico")


def _credenciais_temporarias(root: Path) -> tuple[Path, dict[str, str]]:
    secret_dir = root / "credentials"
    secret_dir.mkdir(mode=0o700)
    senha_path = secret_dir / "restic_password"
    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(senha_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secrets.token_urlsafe(48) + "\n")
        f.flush()
        os.fsync(f.fileno())
    repo_dir = root / "encrypted-repository"
    return repo_dir, {
        # Ambiente de subprocesso por allowlist: sem tokens cloud herdados.
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root),
        "RESTIC_REPOSITORY": str(repo_dir),
        "RESTIC_PASSWORD_FILE": str(senha_path),
        "RESTIC_CACHE_DIR": str(root / "cache"),
    }


def executar_drill(*, ambiente: dict[str, str] | None = None) -> dict:
    """Cria um repositório Restic LOCAL privado, verifica e restaura em nova pasta."""
    env = dict(os.environ) if ambiente is None else ambiente
    _guardas(env)
    # CLI não aceita paths externos nem carrega destinos/segredos cloud.
    restic = shutil.which("restic")
    if not restic:
        raise ErroRestic("restic não instalado: execução real do ensaio indisponível")
    with tempfile.TemporaryDirectory(prefix="nivon-restic-synthetic-") as tmp:
        root = Path(tmp)
        os.chmod(root, 0o700)
        package = root / "fixture"
        info = _criar_fixture(package)
        repo, secure_env = _credenciais_temporarias(root)
        _comando(restic, ["init"], ambiente=secure_env, pasta=root)
        _comando(restic, ["backup", "--tag", "NIVON_SYNTHETIC_OFFLINE", "."],
                 ambiente=secure_env, pasta=package)
        _comando(restic, ["check"], ambiente=secure_env, pasta=root)
        result = _comando(restic, ["snapshots", "--json"], ambiente=secure_env, pasta=root)
        try:
            snapshots = json.loads(result)
        except (ValueError, TypeError) as exc:
            raise ErroRestic("catálogo de snapshots Restic inválido") from exc
        if (not isinstance(snapshots, list) or len(snapshots) != 1
                or "NIVON_SYNTHETIC_OFFLINE" not in snapshots[0].get("tags", [])):
            raise ErroRestic("snapshot sintético único não comprovado")
        target = root / "restored"
        target.mkdir(mode=0o700)
        _comando(restic, ["restore", "latest", "--target", str(target)],
                 ambiente=secure_env, pasta=root)
        manifests = list(target.rglob("nivon-sintetico.manifest.json"))
        backups = list(target.rglob("nivon-sintetico.sqlite"))
        if (len(manifests) != 1 or len(backups) != 1
                or manifests[0].parent != backups[0].parent
                or any(p.is_symlink() for p in manifests + backups)):
            raise ErroRestic("restore não retornou exatamente o pacote esperado")
        result = testar_restore_pacote(manifests[0], diretorio_temporario=root)
        if result["arquivo_sha256"] != info["sha256"]:
            raise ErroRestic("hash do arquivo restaurado diverge do pacote original")
        return {
            "estado": "RESTIC_LOCAL_ENCRYPTED_SYNTHETIC_RESTORE_OK",
            "snapshot_count": 1,
            "tables_verified": result["tabelas_verificadas"],
            "restored_sha256": result["arquivo_sha256"],
            "production_backup_verified": False,
            "remote_backup_verified": False,
            "remote_restore_verified": False,
            "cloud_credentials_used": False,
            "persistent_service_started": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NIVON: Restic sintético offline")
    parser.add_argument("--synthetic-drill", action="store_true",
                        help="ensaio efêmero local com Restic instalado; sem rede do NIVON")
    args = parser.parse_args(argv)
    try:
        _guardas(dict(os.environ))
        if not args.synthetic_drill:
            print(json.dumps({"estado": "OFF_BY_DEFAULT", "restic_executado": False,
                              "remote_backup_verified": False}, sort_keys=True))
            return 0
        report = executar_drill()
        print(json.dumps(report, sort_keys=True))
        return 0
    except (ErroRestic, ErroPacote, OSError, sqlite3.Error) as exc:
        print(json.dumps({"estado": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
