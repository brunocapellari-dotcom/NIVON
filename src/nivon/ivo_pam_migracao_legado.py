"""Migração explícita do ZIP piloto PAM antigo para o backup canônico NIVON.

Aceita SOMENTE os arquivos históricos conhecidos (pam.sqlite, cofre/*,
resultado_coleta.json e auditoria.json). Nunca rede, GCS, promoção ou treino.
A validade temporal/licença da captura NÃO é estabelecida pela conversão.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import zipfile
from pathlib import Path

from .ivo_pam_backup import ErroBackupPAM, criar_backup_pam, restaurar_backup_pam
from .ivo_pam_qualidade import auditar_operacao_pam
from .ivo_pam_leitura import abrir_pam_somente_leitura


class ErroMigracaoPAM(ValueError):
    pass


_MAX = 128 * 1024 * 1024
_MAX_ITEMS = 6002
_OBJ = re.compile(r"cofre/objetos_sha256/([a-f0-9]{64})\.bin\Z")
_REC = re.compile(r"cofre/recibos/([a-f0-9]{64})\.json\Z")
_ALLOWED = frozenset({"pam.sqlite", "auditoria.json", "resultado_coleta.json"})


def converter_zip_piloto_pam(*, arquivo_legado: str | Path,
                             arquivo_canonico: str | Path) -> dict:
    """Verifica tudo antes de criar o ZIP canonico; não modifica origem.

    O artefato de entrada precisa ter sido preservado por via autorizada.
    A rotina não lê outros diretórios nem procura estados antigos no GitHub.
    """
    src, dest = Path(arquivo_legado), Path(arquivo_canonico)
    if (src.is_symlink() or not src.is_file() or
            not 0 < src.stat().st_size <= _MAX or
            dest.exists() or dest.is_symlink() or
            not dest.parent.is_dir() or dest.parent.is_symlink()):
        raise ErroMigracaoPAM("origem ou destino de migracao invalido")
    content: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(src) as z:
            entries = z.infolist()
            if not 3 <= len(entries) <= _MAX_ITEMS:
                raise ErroMigracaoPAM("inventario ZIP incompleto ou excessivo")
            if len({x.filename for x in entries}) != len(entries):
                raise ErroMigracaoPAM("nomes repetidos no ZIP")
            total = 0
            for entry in entries:
                name = entry.filename
                if (entry.is_dir() or name not in _ALLOWED and
                    not _OBJ.fullmatch(name) and not _REC.fullmatch(name)):
                    raise ErroMigracaoPAM("caminho nao previsto no backup piloto")
                if (stat.S_ISLNK(entry.external_attr >> 16) or
                        entry.flag_bits & 1 or entry.file_size <= 0 or
                        entry.file_size > _MAX or
                        entry.compress_type not in (zipfile.ZIP_STORED,
                                                   zipfile.ZIP_DEFLATED)):
                    raise ErroMigracaoPAM("entrada ZIP nao confiavel")
                if entry.compress_size <= 0 or entry.file_size / entry.compress_size > 1000:
                    raise ErroMigracaoPAM("expansao de ZIP suspeita")
                total += entry.file_size
                if total > _MAX:
                    raise ErroMigracaoPAM("quota de ZIP excedida")
            if ("pam.sqlite" not in {i.filename for i in entries} or
                    not any(_OBJ.fullmatch(i.filename) for i in entries) or
                    not any(_REC.fullmatch(i.filename) for i in entries)):
                raise ErroMigracaoPAM("faltam SQLite e acervo em quarentena")
            for entry in entries:
                raw = z.read(entry.filename)
                digest = _OBJ.fullmatch(entry.filename) or _REC.fullmatch(entry.filename)
                if digest and hashlib.sha256(raw).hexdigest() != digest.group(1):
                    raise ErroMigracaoPAM("objeto ou recibo alterado")
                content[entry.filename] = raw
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError, ValueError) as exc:
        if isinstance(exc, ErroMigracaoPAM):
            raise
        raise ErroMigracaoPAM("ZIP piloto invalido") from exc
    with tempfile.TemporaryDirectory(prefix="nivon-pam-migracao-") as temp:
        root = Path(temp)
        (root / "operacional.sqlite").write_bytes(content["pam.sqlite"])
        for name, raw in content.items():
            if name in _ALLOWED:
                continue
            new_name = name.removeprefix("cofre/")
            p = root / new_name
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(raw)
        try:
            with abrir_pam_somente_leitura(root / "operacional.sqlite") as db:
                state = auditar_operacao_pam(db=db, raiz=root)
            if state.get("integridade_local_aprovada") is not True:
                raise ErroMigracaoPAM("dados legados nao passam auditoria completa")
            # Construir e reauditar o arquivo em staging isolado.
            # SOMENTE após o restauro integral criar o destino pelo link
            # atômico sem sobrescrita (previne corrida com outro processo).
            with tempfile.TemporaryDirectory(
                prefix=".nivon_pam_convertido_", dir=dest.parent
            ) as local:
                candidate = Path(local) / "canonico.zip"
                criar_backup_pam(
                    banco=root / "operacional.sqlite", cofre=root,
                    arquivo_zip=candidate,
                )
                checked = restaurar_backup_pam(
                    arquivo_zip=candidate, destino=root / "restaurado",
                )
                if (checked["capturas"] != state["capturas_registradas"] or
                        checked["vintages"] != state["vintages_verificadas"]):
                    raise ErroMigracaoPAM("arquivo convertido difere da origem")
                os.link(candidate, dest)
        except (sqlite3.Error, OSError, ErroBackupPAM, ValueError) as exc:
            # Nunca apagar um destino possivelmente criado por terceiro.
            # Uma falha deixa apenas artefatos efêmeros fora do destino.
            raise ErroMigracaoPAM("falha de auditoria/migracao") from exc
    return {
        "estado": "PAM_LEGADO_CONVERTIDO_CANONICO_NAO_HOMOLOGADO",
        "capturas": state["capturas_registradas"],
        "vintages": state["vintages_verificadas"],
        "zip_original_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "zip_canonico_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "novo_formato": "nivon_ivo_pam_backup_operacional_v1",
        "homologacao_de_fonte": False,
        "direitos_de_uso_verificados": False,
        "treino_habilitado": False,
        "publicacao_autorizada": False,
        "promocoes": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Converte ZIP piloto PAM para formato canônico sem rede"
    )
    parser.add_argument("--origem", required=True, type=Path)
    parser.add_argument("--destino", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = converter_zip_piloto_pam(
            arquivo_legado=args.origem, arquivo_canonico=args.destino,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ErroMigracaoPAM, OSError) as exc:
        print(json.dumps({"estado": "BLOQUEADO_MIGRACAO_LEGADA",
                          "classe": type(exc).__name__,
                          "promocoes": 0}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
