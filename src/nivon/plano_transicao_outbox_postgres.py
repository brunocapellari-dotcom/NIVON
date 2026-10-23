"""Plano READ-ONLY de saída SQLite -> banco PostgreSQL compartilhado.

Não cria schemas, não acessa Postgres/GCP, não expõe destinatários e não move
dados. Os gates têm de ser liberados por revisor/operador fora deste módulo.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from .auditoria_outbox_integrada import auditar_integridade_envios
from .backup_outbox import estado_logico
from .migracao_outbox_legada import planejar_migracao, hash_snapshot_legado


class ErroTransicao(ValueError):
    pass


REQUIRED={
    "consentimentos","reservas","recibos","post_tentativas",
    "quarentena_legacy",
}
TRIGGERS={
    "trg_consentimento_guard","trg_consentimento_revogacao",
    "trg_reserva_guard","trg_recibo_guard","trg_post_guard",
}


def validar_contrato_postgres(sql: str) -> dict:
    """Checagem lexical mínima: NÃO afirma que SQL executa no PostgreSQL."""
    if not isinstance(sql,str) or not sql or len(sql)>500_000:
        raise ErroTransicao("DDL ausente ou grande demais")
    if not re.search(r"(?im)^\s*BEGIN\s*;",sql) or not re.search(
            r"(?im)^\s*COMMIT\s*;",sql):
        raise ErroTransicao("DDL deve declarar BEGIN/COMMIT explícitos")
    tabelas=set(re.findall(
        r"(?im)^\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+nivon_mensageria\.([a-z_]+)\s*\(",
        sql))
    gatilhos=set(re.findall(
        r"(?im)^\s*CREATE\s+TRIGGER\s+(trg_[a-z_]+)",sql))
    faltam=sorted((REQUIRED-tabelas)|(TRIGGERS-gatilhos))
    if faltam:
        raise ErroTransicao("contrato incompleto: "+",".join(faltam))
    if "PRIMARY KEY(dia_local,destinatario_hmac)" not in sql:
        raise ErroTransicao("única reserva diária não comprovada no arquivo")
    if "FOR UPDATE OF c,r" not in sql:
        raise ErroTransicao("lock de tentativa de POST não encontrado")
    return {"status":"DDL_ESTATICAMENTE_COMPLETO_NAO_EXECUTADO",
            "esquema_sha256":hashlib.sha256(sql.encode()).hexdigest(),
            "tabelas":sorted(tabelas),"triggers":sorted(gatilhos),
            "teste_em_postgres_real":False,
            "implantacao_autorizada":False}


def planejar_transicao(db: sqlite3.Connection, *, sql_postgres: str) -> dict:
    """O resultado só contém métricas agregadas e hashes opacos."""
    if db.in_transaction:
        raise ErroTransicao("não auditar durante transação de escrita")
    contract=validar_contrato_postgres(sql_postgres)
    audit=auditar_integridade_envios(db)
    legacy=planejar_migracao(db)
    snapshot=estado_logico(db)
    inconsistente=audit["total_anomalias"]>0
    steps=[
        "01_REVISAR_ORIGEM_DESTINO_DIREITOS_CUSTOS_IDENTIDADES",
        "02_INTERROMPER_TODOS_OS_REMETENTES_E_RECONCILIAR_PROVIDER",
        "03_CRIAR_BACKUP_CRIPTOGRAFADO_E_TESTAR_RESTORE",
        "04_VALIDAR_DDL_E_TRANSACTION_LOCKS_EM_POSTGRES_DESCARTAVEL",
        "05_STAGE_QUARENTENA_HISTORICA_SEM_PROMOVER_ENTREGAS",
        "06_COMPARAR_CONTAGENS_E_HASHES_COM_SNAPSHOT_IMUTAVEL",
        "07_TESTAR_CONCORRENCIA_FAILOVER_OPT_OUT_E_WEBHOOK",
        "08_SOLICITAR_APROVACAO_EXPLICITA_PARA_CUTOVER",
    ]
    return {
        "estado":"BLOQUEADA_POR_DIVERGENCIAS" if inconsistente
                 else "PENDENTE_DE_HOMOLOGACAO_EXTERNA",
        "contrato":contract,
        "origen_sqlite": {
            "tabelas":snapshot["tabelas"],
            "total_linhas":snapshot["total_linhas"],
            "digest_logico":snapshot["conteudo_sha256"],
            "schema_sha256":snapshot.get("esquema_sha256"),
            "snapshot_legacy_sha256":hash_snapshot_legado(db),
        },
        "reconciliacao":{
            "anomalias":audit["anomalias"],
            "total":audit["total_anomalias"],
            "legado_total":legacy["total"],
            "grupos_quarentena":legacy["grupos"],
        },
        "passos":steps,
        "banco_postgres_acessado":False,
        "copias_de_registros_geradas":0,
        "credenciais_usadas":False,"envio_autorizado":False,
        "implantacao_autorizada":False,
    }


def auditar_arquivo_sqlite(
    *, sqlite_path: str | Path, ddl_path: str | Path,
) -> dict:
    origin=Path(sqlite_path)
    ddl=Path(ddl_path)
    if not origin.is_absolute() or not origin.is_file() or origin.is_symlink():
        raise ErroTransicao("fonte SQLite existente exige caminho absoluto")
    if not ddl.is_file() or ddl.is_symlink():
        raise ErroTransicao("DDL SQL local inexistente")
    script=ddl.read_text(encoding="utf-8")
    db=sqlite3.connect(origin.as_uri()+"?mode=ro",uri=True)
    db.execute("PRAGMA query_only=ON")
    try:
        return planejar_transicao(db,sql_postgres=script)
    finally:
        db.close()
