"""Plano, integridade e backup/restauração PTAX — fluxo integrado offline.

Operações NÃO alteram o banco-fonte, não chamam rede, não publicam.
O pacote de backup guarda bytes SQLite integrais e SHA-256; pode ser
exportado por infraestrutura posteriormente, mas NÃO é WORM/assinatura
nem prova de relógio ou autorização editorial.
"""
from __future__ import annotations

from hashlib import sha256
import sqlite3
from typing import Mapping

from .ptax_coexistencia import conferir_observacoes_legadas
from .ptax_odata_bruta_mercados import _consulta, verificar_ptax_odata_bruta
from .ptax_plano import planejar_consultas_ptax


class ErroContinuidadePTAX(ValueError):
    """Incompatibilidade temporal, evidência inválida ou backup inseguro."""


VERSAO = "NIVON_PTAX_BACKUP_SQLITE_V1"
LIMITE_BYTES = 64 * 1024 * 1024
MAX_CAPTURAS = 10000
SCHEMAS = frozenset(("PTAX_ODATA_1", "PTAX_ODATA_RAW_V1"))


def _tab(db: sqlite3.Connection, nome: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (nome,),
    ).fetchone() is not None


def auditar_integridade_ptax(db: sqlite3.Connection) -> dict:
    """Confere conteúdo bruto, vínculos e todos os snapshots legados.

    Inspeciona até 10 mil capturas, nunca substitui dados ausentes e
    falha se encontrar RAW órfão, adulterado ou sintético disfarçado.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroContinuidadePTAX("banco sqlite obrigatório")
    try:
        db.execute("PRAGMA foreign_keys=ON")
        status = db.execute("PRAGMA quick_check").fetchone()
        if status is None or status[0] != "ok":
            raise ErroContinuidadePTAX("integridade física SQLite reprovada")
        fk = db.execute("PRAGMA foreign_key_check").fetchone()
        if fk is not None:
            raise ErroContinuidadePTAX("chave estrangeira violada")
        if not (_tab(db, "nivon_snapshots") and _tab(db, "nivon_coletas")):
            raise ErroContinuidadePTAX("ledger de snapshots obrigatório ausente")
        raw_capturas = _tab(db, "nivon_ptax_raw_capturas")
        raw_blobs = _tab(db, "nivon_ptax_raw_blobs")
        if raw_capturas != raw_blobs:
            raise ErroContinuidadePTAX("tabelas PTAX RAW parcialmente ausentes")
        snapshots = db.execute(
            "SELECT id,sha256,schema_versao,tipo FROM nivon_snapshots "
            "WHERE dataset_id='BCB_PTAX' ORDER BY id"
        ).fetchall()
        captura = db.execute(
            "SELECT c.snapshot_id,c.sha256,c.coletado_em,c.consulta_url,"
            "c.moeda,c.tipo,c.origem_execucao,b.dados,b.bytes,"
            "s.schema_versao,s.sha256,s.tipo,s.evidencia_direitos "
            "FROM nivon_ptax_raw_capturas c "
            "JOIN nivon_ptax_raw_blobs b ON b.sha256=c.sha256 "
            "JOIN nivon_snapshots s ON s.id=c.snapshot_id "
            "ORDER BY c.id LIMIT 10001"
        ).fetchall() if raw_capturas else []
        if len(captura) > MAX_CAPTURAS:
            raise ErroContinuidadePTAX("limite de capturas excedido")
        ligados = set()
        for (sid, digest, coleta, url, moeda, tipo, origem,
             raw, tamanho, schema, snapshot_sha, snapshot_tipo, direitos) in captura:
            if (schema not in SCHEMAS or digest != snapshot_sha
                    or tipo != snapshot_tipo or
                    (tipo == "SINTETICO" and origem != "TRANSPORTE_INJETADO_SINTETICO")
                    or (tipo == "REAL_AUTORIZADO" and
                        (origem != "HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO"
                         or not direitos))):
                raise ErroContinuidadePTAX("classificação ou ligação RAW inconsistente")
            if not isinstance(raw, bytes) or tamanho != len(raw) or (
                sha256(raw).hexdigest() != digest
            ):
                raise ErroContinuidadePTAX("bytes PTAX adulterados")
            match = db.execute(
                "SELECT 1 FROM nivon_coletas "
                "WHERE snapshot_id=? AND coletado_utc=?",
                (sid, coleta),
            ).fetchone()
            if match is None:
                raise ErroContinuidadePTAX("captura sem coleta no ledger")
            try:
                start, end = _consulta(url, moeda)
                prova = verificar_ptax_odata_bruta(
                    raw, consulta_url=url, moeda=moeda, coletado_em=coleta,
                    as_of=coleta, raw_sha256_esperado=digest,
                )
                if schema == "PTAX_ODATA_1":
                    plano = planejar_consultas_ptax(
                        moeda=moeda, inicio=start.isoformat(),
                        fim=end.isoformat(), dias_janela=(end-start).days+1,
                    )[0]
                    conferir_observacoes_legadas(
                        db, snapshot_id=sid, payload=raw,
                        plano=plano, coletado_em=coleta,
                    )
            except (TypeError, ValueError, IndexError) as exc:
                raise ErroContinuidadePTAX("parser ou observações legadas divergentes") from exc
            ligados.add(sid)
        # Blobs órfãos (sem captura) podem indicar gravação parcial manual.
        orfaos = (db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_blobs b "
            "WHERE NOT EXISTS (SELECT 1 FROM nivon_ptax_raw_capturas c "
            "WHERE c.sha256=b.sha256)"
        ).fetchone()[0] if raw_blobs else 0)
        if orfaos:
            raise ErroContinuidadePTAX("blobs RAW sem captura")
        schemas = {name: sum(s[2] == name for s in snapshots)
                   for name in SCHEMAS}
        pendentes = [s[1] for s in snapshots
                     if s[2] == "PTAX_ODATA_1" and s[0] not in ligados]
        invalidos = [s[2] for s in snapshots if s[2] not in SCHEMAS]
        if invalidos:
            raise ErroContinuidadePTAX("schema PTAX desconhecido no ledger")
        return {
            "estado": "LEDGER_PTAX_LOCAL_CONFERIDO",
            "total_snapshots": len(snapshots),
            "total_capturas_raw": len(captura),
            "snapshots_raw_ligados": len(ligados),
            "schemas": schemas,
            "legados_sem_raw": len(pendentes),
            "sha_legados_sem_raw": sorted(pendentes),
            "classificacao": "LOCAL_SEM_PROVA_WORM_OU_PUBLICACAO",
            "publicavel": False,
            "apto_backtest_por_publicacao": False,
        }
    except sqlite3.Error as exc:
        raise ErroContinuidadePTAX("falha de leitura/integridade SQLite") from exc


def planejar_migracao_ptax(db: sqlite3.Connection) -> dict:
    """Classifica o progresso da adoção; não fabrica RAW a partir de float."""
    exame = auditar_integridade_ptax(db)
    return {
        "estado": ("AGUARDAR_DOCUMENTOS_ORIGINAIS"
                   if exame["legados_sem_raw"] else "RAW_DISPONIVEIS_LOCALMENTE"),
        "snapshots": exame["total_snapshots"],
        "capturas_raw": exame["total_capturas_raw"],
        "schema": exame["schemas"],
        "documentos_a_recuperar": exame["legados_sem_raw"],
        "sha_sem_raw": exame["sha_legados_sem_raw"],
        "proxima_acao": ("Recuperar os bytes OData originais por fonte autorizada;"
                         " nunca reconstruir bytes originais de floats"
                         if exame["legados_sem_raw"]
                         else "Auditar períodos/cobertura e comparar legacy/Decimal"),
        "migracao_automatica_autorizada": False,
        "publicavel": False,
    }


def criar_pacote_backup_ptax(db: sqlite3.Connection) -> dict:
    """Gera backup consistente em memória, sob limite de tamanho.

    Usar infraestrutura separada para persistir bytes e manifest.
    Não iniciar enquanto conexão-fonte mantiver transação aberta.
    """
    if not isinstance(db, sqlite3.Connection) or db.in_transaction:
        raise ErroContinuidadePTAX("backup requer banco SQLite sem transação aberta")
    origem = auditar_integridade_ptax(db)
    clone = sqlite3.connect(":memory:")
    try:
        db.backup(clone)
        verificado = auditar_integridade_ptax(clone)
        if origem != verificado:
            raise ErroContinuidadePTAX("backup divergente do banco-fonte")
        data = clone.serialize()
    except sqlite3.Error as exc:
        raise ErroContinuidadePTAX("falha ao realizar backup SQLite") from exc
    finally:
        clone.close()
    if not isinstance(data, bytes) or not 1 <= len(data) <= LIMITE_BYTES:
        raise ErroContinuidadePTAX("backup maior que limite local permitido")
    manifest = {
        "versao": VERSAO, "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "inventario": origem,
        "tempo_confiavel_independente": False,
        "backup_externo_immutavel": False,
    }
    return {"manifesto": manifest, "sqlite_bytes": data,
            "publicavel": False}


def restaurar_pacote_backup_ptax(pacote: Mapping) -> sqlite3.Connection:
    """Restitui cópia SQLite independente, fail-closed e sem mutar origem."""
    if not isinstance(pacote, Mapping):
        raise ErroContinuidadePTAX("pacote de backup inválido")
    m, data = pacote.get("manifesto"), pacote.get("sqlite_bytes")
    if (not isinstance(m, dict) or set(m) != {
        "versao", "bytes", "sha256", "inventario",
        "tempo_confiavel_independente", "backup_externo_immutavel"
    } or m.get("versao") != VERSAO or
        m.get("tempo_confiavel_independente") is not False or
        m.get("backup_externo_immutavel") is not False or
        type(data) is not bytes or not 1 <= len(data) <= LIMITE_BYTES or
        m.get("bytes") != len(data) or
        sha256(data).hexdigest() != m.get("sha256")):
        raise ErroContinuidadePTAX("manifesto/digest do backup inválido")
    clone = sqlite3.connect(":memory:")
    try:
        clone.deserialize(data)
        clone.row_factory = sqlite3.Row
        clone.execute("PRAGMA foreign_keys=ON")
        inv = auditar_integridade_ptax(clone)
        if inv != m["inventario"]:
            raise ErroContinuidadePTAX("inventário da restauração divergente")
        return clone
    except (sqlite3.Error, ValueError, TypeError) as exc:
        clone.close()
        if isinstance(exc, ErroContinuidadePTAX):
            raise
        raise ErroContinuidadePTAX("restauração SQLite inválida") from exc
