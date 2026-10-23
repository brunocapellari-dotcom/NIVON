"""Uma só execução OFFLINE: inventário -> backup prévio -> quarentena -> backup -> restore.

CLI padrão SOMENTE LEITURA. --executar-lote-local exige diretório de backups
explícito e exclusivo. Não chama WhatsApp, Cloud API, rede, cron ou provedores.
Os backups contêm HMAC de destinatários e exigem storage privado criptografado.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .backup_outbox import criar_backup_validado, restaurar_backup_validado
from .migracao_outbox_legada import planejar_migracao, registrar_quarentena


def _source(path: str | Path, *, mutate: bool) -> sqlite3.Connection:
    p=Path(path)
    if not p.is_absolute() or not p.is_file() or p.is_symlink():
        raise ValueError("outbox existente requer path absoluto, arquivo regular não-symlink")
    # mode=ro garante que auditoria não crie tabelas/WAL ou modifique fonte.
    con=sqlite3.connect(p.as_uri()+("?mode=rw" if mutate else "?mode=ro"),
                        uri=True,timeout=15)
    if not mutate:
        con.execute("PRAGMA query_only=ON")
    return con


def _counts(plan: dict) -> dict:
    # NÃO retornar HMAC de destinatário ou nome de transportadora/cliente.
    return {"status":plan["status"],"total":plan["total"],
            "motivos":plan["grupos"],
            "envios_novos":0,"autorizacao_producao":False}


def executar_lote(
    *, banco: str | Path, pasta_segura: str | Path | None = None,
    aplicar_quarentena: bool = False,
    agora: str | None = None,
) -> dict:
    """Orquestra todas as etapas locais, conferindo backup anterior e restaurado."""
    con=_source(banco,mutate=aplicar_quarentena)
    try:
        plano=planejar_migracao(con)
        result={"auditoria":_counts(plano),"modo":"SOMENTE_LEITURA",
                "envio_executado":False,"coleta_executada":False}
        if not aplicar_quarentena:
            return result
        if pasta_segura is None:
            raise PermissionError("diretório de backup obrigatório antes de quarentena")
        root=Path(pasta_segura)
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise ValueError("diretório local seguro não configurado")
        if root.resolve()==Path(banco).resolve():
            raise ValueError("destino e origem são iguais")
        # Se etapa intermediária falhar, backup PRÉ-migração continua disponível.
        pre=criar_backup_validado(
            con,destino=root/"nivon-antes-migracao.sqlite",
            autorizar_backup=True,
        )
        stage=registrar_quarentena(
            con,autorizar_staging=True,
            registrado_em=agora or datetime.now(timezone.utc).isoformat(),
        )
        post=criar_backup_validado(
            con,destino=root/"nivon-depois-migracao.sqlite",
            autorizar_backup=True,
        )
        restored=restaurar_backup_validado(
            root/"nivon-depois-migracao.sqlite",
            destino=root/"nivon-restauracao-teste.sqlite",
            sha256_esperado=post["arquivo_sha256"],
            autorizar_restauracao=True,
        )
        if post["conteudo_sha256"]!=restored["conteudo_sha256"]:
            raise RuntimeError("restore não reproduziu outbox consolidada")
        result.update({
            "modo":"QUARENTENA_E_BACKUP_LOCAL",
            "quarentena":stage,
            "backup_pre_sha256":pre["arquivo_sha256"],
            "backup_pos_sha256":post["arquivo_sha256"],
            "restauracao_validada":True,
            "conteudo_sha256":post["conteudo_sha256"],
            "registros_persistidos":post["total_linhas"],
            "envio_autorizado":False,
        })
        return result
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(
        description="NIVON R10: auditar ou recuperar outbox offline em lote")
    parser.add_argument("--banco",required=True,help="path absoluto de SQLite EXISTENTE")
    parser.add_argument("--diretorio-backup",default=None,help="diretório privado existente")
    parser.add_argument("--executar-lote-local",action="store_true",
                        help="opt-in: backup prévio, quarentena, novo backup e restore-teste")
    args=parser.parse_args(argv)
    resultado=executar_lote(
        banco=args.banco,pasta_segura=args.diretorio_backup,
        aplicar_quarentena=args.executar_lote_local,
    )
    print(json.dumps(resultado,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
