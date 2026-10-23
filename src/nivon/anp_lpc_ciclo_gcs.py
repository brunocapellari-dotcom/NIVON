"""Ciclo durável da ANP/LPC num bucket GCS já existente e privado.

Um snapshot SQLite SHA-256 é o commit durável final de um lote.
Restauração valida bytes, integridade SQLite/FKs e TODO o RAW necessário.
Nenhum objeto anterior é sobrescrito. Não há criação de infraestrutura,
agendamento, emissão de credenciais ou mudança de homologação.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
import tempfile

from .anp_lpc_coletor_real import coletar_lpc, _raw_privado
from .anp_lpc_gcs import (
    ErroGCSANP, _gravar_objeto, _validar_destino, exportar_lpc_staging_gcs,
)
from .anp_lpc_staging_real import iniciar_staging, auditar_arquivos_origem_lpc

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_SQLITE = 64_000_000
_MAX_SNAPSHOTS = 1000


def _verificar_sqlite(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ErroGCSANP("snapshot SQLite não passou na auditoria de integridade")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ErroGCSANP("snapshot SQLite contém relacionamentos inválidos")
    nomes = {x[0] for x in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    essenciais = {
        "anp_lpc_staging_edicoes", "anp_lpc_staging_indices",
        "anp_lpc_staging_capturas", "anp_lpc_staging_observacoes",
    }
    if not essenciais.issubset(nomes):
        raise ErroGCSANP("snapshot não é um staging LPC compatível")


def _inventario(bucket, prefixo: str):
    snapshots=[]
    outros=0
    for blob in bucket.list_blobs(prefix=f"{prefixo}/"):
        name=blob.name
        if name.startswith(f"{prefixo}/snapshots/"):
            parte=name.removeprefix(f"{prefixo}/snapshots/")
            if not re.fullmatch(r"[0-9a-f]{64}\.sqlite", parte):
                raise ErroGCSANP("objeto inesperado no namespace de snapshots")
            if (blob.time_created is None or blob.time_created.tzinfo is None):
                raise ErroGCSANP("snapshot sem horário confiável do GCS")
            snapshots.append(blob)
            if len(snapshots)>_MAX_SNAPSHOTS:
                raise ErroGCSANP("limite de snapshots excedido, revisão necessária")
        else:
            outros+=1
    return snapshots, outros


def _baixar_verificado(bucket, key: str, digest: str, limite: int) -> bytes:
    if not _SHA_RE.fullmatch(digest):
        raise ErroGCSANP("digest remoto inválido")
    blob=bucket.blob(key)
    if not blob.exists():
        raise ErroGCSANP(f"objeto remoto obrigatório não existe: {key}")
    blob.reload()
    if (blob.metadata or {}).get("sha256")!=digest:
        raise ErroGCSANP("SHA metadata remoto não corresponde ao objeto esperado")
    conteudo=blob.download_as_bytes()
    if (not isinstance(conteudo, bytes) or len(conteudo)>limite
            or sha256(conteudo).hexdigest()!=digest):
        raise ErroGCSANP("conteúdo remoto diverge do hash esperado")
    return conteudo


def restaurar_ultimo_staging_gcs(
    *, bucket, db_path: Path, raw_dir: Path,
    prefixo: str = "nivon/anp/lpc/v1",
) -> dict:
    """Restaura snapshot mais novo sem retroceder silenciosamente.

    Destino deve estar vazio para evitar misturar dados locais não enviados.
    Se existem objetos históricos mas nenhum commit SQLite, falha fechado.
    """
    _validar_destino(bucket,prefixo)
    db_path,raw_dir=Path(db_path),Path(raw_dir)
    if (db_path.exists() or db_path.is_symlink()
            or not db_path.parent.is_dir() or not raw_dir.is_dir()
            or raw_dir.is_symlink() or any(raw_dir.iterdir())):
        raise ErroGCSANP("restauração exige DB ausente e diretório RAW vazio")
    snapshots, outros = _inventario(bucket,prefixo)
    if not snapshots:
        if outros:
            raise ErroGCSANP("bucket contém dados órfãos sem snapshot confirmado")
        with closing(sqlite3.connect(db_path)) as db:
            iniciar_staging(db)
        return {
            "status":"STAGING_NOVO_SEM_SNAPSHOT", "edicoes_restauradas":0,
            "snapshots_disponiveis":0, "publicavel":False,
        }
    # O tempo é fornecido pelo armazenamento (não pelo XLSX ou coletor).
    # Se o MAIS RECENTE estiver corrompido, NÃO voltar ao antigo.
    latest=max(snapshots,key=lambda b:(b.time_created,b.name))
    digest=latest.name.removeprefix(f"{prefixo}/snapshots/").removesuffix(".sqlite")
    conteudo=_baixar_verificado(bucket, latest.name,digest,_MAX_SQLITE)
    temporario=db_path.with_name(db_path.name+".restaurando")
    if temporario.exists() or temporario.is_symlink():
        raise ErroGCSANP("arquivo temporário de restauração já existe")
    try:
        with temporario.open("xb") as arq:
            arq.write(conteudo)
        with closing(sqlite3.connect(f"file:{temporario}?mode=ro",uri=True)) as audit:
            _verificar_sqlite(audit)
            audit.row_factory=sqlite3.Row
            rows=audit.execute("""
                SELECT sha256 FROM anp_lpc_staging_edicoes
                WHERE raw_arquivado=1 ORDER BY sha256""").fetchall()
            indices=audit.execute("""
                SELECT DISTINCT indice_sha256 FROM anp_lpc_staging_indices
                ORDER BY indice_sha256""").fetchall()
            pendentes=audit.execute("""
                SELECT COUNT(*) FROM anp_lpc_staging_edicoes
                WHERE raw_arquivado!=1""").fetchone()[0]
            if pendentes:
                raise ErroGCSANP("snapshot exige RAW de todas as edições")
            for item in rows:
                sha=item["sha256"]
                if not _SHA_RE.fullmatch(sha):
                    raise ErroGCSANP("hash XLSX no snapshot inválido")
                data=_baixar_verificado(
                    bucket, f"{prefixo}/planilhas/{sha}.xlsx",sha,14_000_000)
                _raw_privado(raw_dir,subpasta="planilhas",
                            nome=f"{sha}.xlsx",payload=data)
            for item in indices:
                sha=item["indice_sha256"]
                if not _SHA_RE.fullmatch(sha):
                    raise ErroGCSANP("hash índice no snapshot inválido")
                data=_baixar_verificado(
                    bucket, f"{prefixo}/indices/{sha}.html",sha,4_000_000)
                _raw_privado(raw_dir,subpasta="indices",
                            nome=f"{sha}.html",payload=data)
            verificado=auditar_arquivos_origem_lpc(
                audit,raiz_raw=str(raw_dir),as_of=datetime.now(timezone.utc).isoformat(),
            )
            if verificado["status"]!="RAW_VERIFICADO_LOCALMENTE":
                raise ErroGCSANP("RAW restaurado não passou na auditoria")
        temporario.replace(db_path)
    finally:
        temporario.unlink(missing_ok=True)
    return {
        "status":"STAGING_RESTAURADO_GCS",
        "snapshot_sha256":digest,
        "edicoes_restauradas":len(rows),
        "indices_restaurados":len(indices),
        "snapshots_disponiveis":len(snapshots),
        "publicavel":False,
    }


def confirmar_snapshot_gcs(
    db: sqlite3.Connection, *, bucket,
    prefixo: str = "nivon/anp/lpc/v1",
) -> dict:
    """Grava commit durável após exportação de todos os objetos originais."""
    _validar_destino(bucket,prefixo)
    _verificar_sqlite(db)
    with tempfile.TemporaryDirectory(prefix="nivon-anp-snapshot-") as pasta:
        path=Path(pasta)/"snapshot.sqlite"
        with closing(sqlite3.connect(path)) as destino:
            db.backup(destino)
            _verificar_sqlite(destino)
        if path.stat().st_size>_MAX_SQLITE:
            raise ErroGCSANP("snapshot ultrapassa limite de 64 MB")
        sha=sha256(path.read_bytes()).hexdigest()
        novo=_gravar_objeto(
            bucket, chave=f"{prefixo}/snapshots/{sha}.sqlite",
            sha=sha,tipo="application/vnd.sqlite3",caminho=path,
        )
    return {
        "status":"SNAPSHOT_GCS_CONFIRMADO",
        "snapshot_sha256":sha,"snapshot_novo":novo,
        "publicavel":False,
    }


def executar_ciclo_lpc_gcs(
    *, bucket, ano: int, limite_semanas: int=3,
    prefixo: str="nivon/anp/lpc/v1",
    indice_bytes: bytes | None=None,
    arquivos_locais: dict | None=None,
    abridor=None,
    esperar_segundos: float=1.0,
) -> dict:
    """Restaura > coleta/normaliza > audita > exporta > confirma snapshot.

    Uma execução não exige volume local permanente. Não existe cron, billing,
    credencial ou provisionamento embutido. Testes passam fixtures opcionais.
    """
    _validar_destino(bucket,prefixo)
    with tempfile.TemporaryDirectory(prefix="nivon-anp-gcs-") as tmp:
        raiz=Path(tmp)
        raw=raiz/"raw"
        raw.mkdir(mode=0o700)
        db_path=raiz/"staging.sqlite"
        restauracao=restaurar_ultimo_staging_gcs(
            bucket=bucket,db_path=db_path,raw_dir=raw,prefixo=prefixo,
        )
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            batch=coletar_lpc(
                db,ano=ano,limite_semanas=limite_semanas,raw_dir=raw,
                indice_bytes=indice_bytes,arquivos_locais=arquivos_locais,
                abridor=abridor,esperar_segundos=esperar_segundos,
            )
            if batch["status"]=="LOTE_FALHOU":
                raise ErroGCSANP("nenhum XLSX válido; snapshot não será avançado")
            corte=datetime.now(timezone.utc).isoformat()
            exportacao=exportar_lpc_staging_gcs(
                db,raiz_raw=str(raw),bucket=bucket,as_of=corte,
                prefixo=prefixo,
            )
            confirmado=confirmar_snapshot_gcs(
                db,bucket=bucket,prefixo=prefixo,
            )
        return {
            "status":"CICLO_GCS_COMPLETO" if batch["status"]=="LOTE_COMPLETO"
                     else "CICLO_GCS_PARCIAL",
            "restauracao":restauracao,"coleta":{
                "status":batch["status"],
                "edicoes_integradas":batch["edicoes_integradas"],
                "edicoes_novas":batch["edicoes_novas"],
                "capturas_novas":batch["capturas_novas"],
                "observacoes_integradas":batch["observacoes_integradas"],
                "erros":batch["erros"],
            },
            "exportacao":exportacao,"snapshot":confirmado,
            "publicavel":False,"homologado":False,
        }
