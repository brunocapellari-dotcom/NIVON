"""Backup/restore PORTAVEL do staging PAM: SQLite + bytes + recibos.

Sem conexao cloud, publicacao ou transformacao em verdade canonica.
O ZIP contem exatamente o necessario para restaurar e auditar localmente.
Integridade SHA nao equivale a origem oficial/assinatura independente.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .ivo_pam_qualidade import auditar_operacao_pam


class ErroBackupPAM(ValueError):
    pass


_HASH = re.compile(r"[a-f0-9]{64}\Z")
_OBJ = re.compile(r"objetos_sha256/[a-f0-9]{64}\.bin\Z")
_REC = re.compile(r"recibos/[a-f0-9]{64}\.json\Z")
_MAX_ENTRADAS = 6005


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(x: object) -> bytes:
    return (json.dumps(x, ensure_ascii=False, sort_keys=True,
                       allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def _abrir_db_ro(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise ErroBackupPAM("banco SQLite inexistente ou simbolico")
    uri = "file:" + quote(str(path.resolve(strict=True)), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _conferir_base(db: sqlite3.Connection, cofre: Path) -> dict:
    try:
        res = auditar_operacao_pam(db=db, raiz=cofre, max_vintages=3000)
    except (ValueError, TypeError, sqlite3.Error, OSError) as exc:
        raise ErroBackupPAM("integridade do staging nao verificavel") from exc
    if res.get("integridade_local_aprovada") is not True:
        raise ErroBackupPAM("staging corrupto: backup/restauro recusado")
    return res


def _validar_tamanho(max_bytes: int) -> None:
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 128 * 1024 * 1024:
        raise ErroBackupPAM("limite de backup fora do intervalo")


def _originais(cofre: Path, max_bytes: int) -> dict[str, bytes]:
    if cofre.is_symlink() or not cofre.is_dir():
        raise ErroBackupPAM("quarentena ausente ou simbolica")
    result: dict[str, bytes] = {}
    size = 0
    for folder, regex in (("objetos_sha256", _OBJ), ("recibos", _REC)):
        sub = cofre / folder
        if sub.is_symlink() or not sub.is_dir():
            raise ErroBackupPAM("diretorio de quarentena invalido")
        for file in sorted(sub.iterdir()):
            name = folder + "/" + file.name
            if (not regex.fullmatch(name) or file.is_symlink()
                    or not file.is_file() or len(result) >= _MAX_ENTRADAS - 2):
                raise ErroBackupPAM("arquivo de cofre inesperado")
            stat_size = file.stat().st_size
            if not 0 < stat_size <= max_bytes - size:
                raise ErroBackupPAM("quota total excedida")
            raw = file.read_bytes()
            if len(raw) != stat_size:
                raise ErroBackupPAM("arquivo mudou na leitura")
            # Nomes content-addressed sao parte do contrato da quarentena.
            if _hash(raw) != file.name[:64]:
                raise ErroBackupPAM("objeto ou recibo adulterado")
            result[name] = raw
            size += len(raw)
    return result


def criar_backup_pam(
    *, banco: str | Path, cofre: str | Path,
    arquivo_zip: str | Path, max_bytes: int = 64 * 1024 * 1024,
) -> dict:
    """Congela SQLite via backup API e valida bytes antes da publicacao local."""
    _validar_tamanho(max_bytes)
    src, root, out = Path(banco), Path(cofre), Path(arquivo_zip)
    if out.exists() or out.is_symlink() or not out.parent.is_dir() or out.parent.is_symlink():
        raise ErroBackupPAM("destino deve ser arquivo novo em diretorio existente")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "operacional.sqlite"
        with closing(_abrir_db_ro(src)) as db:
            pre = _conferir_base(db, root)
            with closing(sqlite3.connect(snapshot)) as copy:
                db.backup(copy)
        with closing(_abrir_db_ro(snapshot)) as db:
            post = _conferir_base(db, root)
        if (pre["vintages_verificadas"] != post["vintages_verificadas"]
                or pre["capturas_registradas"] != post["capturas_registradas"]):
            raise ErroBackupPAM("coleta alterada durante checkpoint")
        files = {"operacional.sqlite": snapshot.read_bytes()}
        files.update(_originais(root, max_bytes))
        if sum(map(len, files.values())) > max_bytes:
            raise ErroBackupPAM("backup excede quota")
        manifest = {
            "schema": "nivon_ivo_pam_backup_operacional_v1",
            "capturas": post["capturas_registradas"],
            "vintages": post["vintages_verificadas"],
            "arquivos": {
                name: {"sha256": _hash(raw), "bytes": len(raw)}
                for name, raw in sorted(files.items())
            },
            "direitos_externos_comprovados": False,
            "publicacao_oficial_atestada": False,
            "registro_canonico_modificado": False,
            "homologacao_operacional": False,
        }
        files["manifesto.json"] = _json(manifest)
        # ZIP_STORED evita bomb de compressao e preserva bytes exatos.
        fd, tmpzip = tempfile.mkstemp(prefix=".nivon_backup_", suffix=".zip",
                                       dir=out.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmpzip, "w", compression=zipfile.ZIP_STORED) as z:
                for name, raw in sorted(files.items()):
                    z.writestr(name, raw)
            # Link atomico sem sobrescrever backup preexistente.
            os.link(tmpzip, out)
        except Exception:
            raise
        finally:
            Path(tmpzip).unlink(missing_ok=True)
    return {
        "estado": "BACKUP_OPERACIONAL_LOCAL_VERIFICADO_NAO_HOMOLOGADO",
        "arquivo": str(out),
        "capturas": manifest["capturas"],
        "vintages": manifest["vintages"],
        "objetos_e_recibos": len(files) - 2,
        "manifesto_sha256": _hash(files["manifesto.json"]),
        "publicacao_autorizada": False,
        "treinamento_autorizado": False,
    }


def restaurar_backup_pam(
    *, arquivo_zip: str | Path, destino: str | Path,
    max_bytes: int = 64 * 1024 * 1024,
) -> dict:
    """Restaura APENAS em diretorio novo, valida backup, SQL e cofre antes de expor."""
    _validar_tamanho(max_bytes)
    archive, dst = Path(arquivo_zip), Path(destino)
    if (archive.is_symlink() or not archive.is_file()
            or dst.exists() or dst.is_symlink()
            or not dst.parent.is_dir() or dst.parent.is_symlink()):
        raise ErroBackupPAM("origem ou destino de restauracao invalido")
    try:
        with zipfile.ZipFile(archive, "r") as z:
            info = z.infolist()
            if not 2 <= len(info) <= _MAX_ENTRADAS:
                raise ErroBackupPAM("quantidade de arquivos fora do limite")
            names = [x.filename for x in info]
            if len(set(names)) != len(names):
                raise ErroBackupPAM("arquivos duplicados no ZIP")
            total = 0
            for item in info:
                if (item.filename not in ("manifesto.json", "operacional.sqlite")
                        and not _OBJ.fullmatch(item.filename)
                        and not _REC.fullmatch(item.filename)):
                    raise ErroBackupPAM("caminho nao permitido no ZIP")
                if (item.compress_type != zipfile.ZIP_STORED
                        or stat.S_ISLNK(item.external_attr >> 16)):
                    raise ErroBackupPAM("ZIP com compressao ou links nao suportados")
                total += item.file_size
                if total > max_bytes + 100_000:
                    raise ErroBackupPAM("ZIP excede quota descomprimida")
            manifest = json.loads(z.read("manifesto.json"))
            if (not isinstance(manifest, dict)
                    or manifest.get("schema") != "nivon_ivo_pam_backup_operacional_v1"
                    or manifest.get("direitos_externos_comprovados") is not False
                    or manifest.get("publicacao_oficial_atestada") is not False
                    or manifest.get("registro_canonico_modificado") is not False
                    or manifest.get("homologacao_operacional") is not False):
                raise ErroBackupPAM("manifesto nao e staging bloqueado")
            hashes = manifest.get("arquivos")
            if (not isinstance(hashes, dict)
                    or set(names) != set(hashes) | {"manifesto.json"}
                    or "operacional.sqlite" not in hashes):
                raise ErroBackupPAM("inventario ZIP divergente")
            chunks = {}
            tamanho_de_dados = 0
            for name in hashes:
                expected = hashes[name]
                if (not isinstance(expected, dict)
                        or not isinstance(expected.get("sha256"), str)
                        or not _HASH.fullmatch(expected["sha256"])
                        or type(expected.get("bytes")) is not int):
                    raise ErroBackupPAM("checksum ausente")
                raw = z.read(name)
                tamanho_de_dados += len(raw)
                # A margem de 100 KiB acima e reservada EXCLUSIVAMENTE ao
                # inventario JSON: bytes SQLite + arquivos obedecem a quota.
                if tamanho_de_dados > max_bytes:
                    raise ErroBackupPAM("restauracao excede quota de dados")
                if len(raw) != expected["bytes"] or _hash(raw) != expected["sha256"]:
                    raise ErroBackupPAM("conteudo de backup adulterado")
                chunks[name] = raw
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, TypeError) as exc:
        if isinstance(exc, ErroBackupPAM):
            raise
        raise ErroBackupPAM("arquivo ZIP ou manifesto invalido") from exc

    staging = Path(tempfile.mkdtemp(prefix=".nivon_restore_", dir=dst.parent))
    try:
        for name, raw in chunks.items():
            path = staging / name
            path.parent.mkdir(exist_ok=True, mode=0o700)
            path.write_bytes(raw)
            path.chmod(0o600)
        with closing(_abrir_db_ro(staging / "operacional.sqlite")) as db:
            status = _conferir_base(db, staging)
        if (status["capturas_registradas"] != manifest.get("capturas")
                or status["vintages_verificadas"] != manifest.get("vintages")):
            raise ErroBackupPAM("restauracao diverge do inventario SQL")
        if dst.exists() or dst.is_symlink():
            raise ErroBackupPAM("destino foi ocupado durante restauracao")
        staging.rename(dst)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "estado": "RESTAURO_OPERACIONAL_LOCAL_VERIFICADO_NAO_HOMOLOGADO",
        "destino": str(dst),
        "capturas": manifest["capturas"],
        "vintages": manifest["vintages"],
        "integridade_local_aprovada": True,
        "registro_canonico_modificado": False,
        "publicacao_autorizada": False,
        "treinamento_autorizado": False,
    }
