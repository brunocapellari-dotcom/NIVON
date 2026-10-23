"""Abertura exclusivamente de leitura do SQLite operacional da PAM.

A consulta do IVO não pode criar um banco vazio silenciosamente. Detecta
schema ausente, symlinks e não exige permissão de escrita no diretório.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class ErroLeituraPAM(ValueError):
    pass


def abrir_pam_somente_leitura(caminho: str | Path) -> sqlite3.Connection:
    if not isinstance(caminho, (str,Path)):
        raise ErroLeituraPAM("caminho SQLite obrigatório")
    p=Path(caminho).expanduser()
    if p.is_symlink() or not p.is_file():
        raise ErroLeituraPAM("SQLite PAM operacional inexistente ou symlink")
    p=p.resolve(strict=True)
    if p.stat().st_size == 0:
        raise ErroLeituraPAM("SQLite PAM está vazio")
    db=sqlite3.connect(p.as_uri()+"?mode=ro",uri=True,timeout=5)
    db.row_factory=sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA foreign_keys=ON")
        rows=db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('pam_vintages','pam_capturas')").fetchall()
        if {r["name"] for r in rows}!={"pam_vintages","pam_capturas"}:
            raise ErroLeituraPAM("SQLite não contém tabelas operacionais PAM")
        if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise ErroLeituraPAM("SQLite PAM não passou verificação de integridade")
        return db
    except (sqlite3.Error, ErroLeituraPAM):
        db.close()
        raise
