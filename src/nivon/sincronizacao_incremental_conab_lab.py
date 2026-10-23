"""Sincronização incremental de referência CONAB em SQLite LAB persistente.

Execução deliberadamente limitada a XLSX públicos fixados do agrobr ou RAWs
locais com SHA; não interage com CONAB, bancos canônicos nem produção.
Uma edição nova exige parser/observações verificados antes de escrita.
Revisão de competência e mudança de SHA de edição conhecida falham fechadas.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .auditoria_vintages_conab import (
    _json_strict, auditar_vintages_conab, validar_catalogo_vintages,
)
from .conab_replay_xlsx import reexecutar_xlsx_conab, PARSER_ID
from .lote_conab_integracao import _stage, obter_referencias_terceiro

SCHEMA="NIVON_CONAB_INCREMENTAL_LAB_V1"
MAX_EDICOES=52


class ErroIncrementalConab(ValueError):
    pass


def _dir_private(path: str | Path):
    p=Path(path)
    if not p.is_absolute() or not p.is_dir() or p.is_symlink():
        raise ErroIncrementalConab("exige diretório absoluto existente, sem symlink")
    if os.name=="posix" and stat.S_IMODE(p.stat().st_mode)&0o077:
        raise ErroIncrementalConab("diretório LAB precisa ser privado (0700)")
    return p


def _db_file(path: str | Path):
    p=Path(path)
    _dir_private(p.parent)
    if p.is_symlink() or (p.exists() and not p.is_file()):
        raise ErroIncrementalConab("banco LAB inválido ou symlink")
    if p.exists() and os.name=="posix" and stat.S_IMODE(p.stat().st_mode)&0o077:
        raise ErroIncrementalConab("banco LAB precisa ser privado (0600)")
    return p


def abrir_db_lab(path: str | Path):
    p=_db_file(path)
    if not p.exists():
        try:
            fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
        except FileExistsError:
            _db_file(p)
        else:
            os.close(fd)
    db=sqlite3.connect(str(p),timeout=10)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        _stage(db)
        db.execute("""CREATE TABLE IF NOT EXISTS lab_eventos_incrementais (
           seq INTEGER PRIMARY KEY,
           executado_utc TEXT NOT NULL,
           manifesto_sha256 TEXT NOT NULL,
           referencias_novas INTEGER NOT NULL CHECK(referencias_novas>0),
           observacoes_novas INTEGER NOT NULL CHECK(observacoes_novas>0),
           observacoes_apos INTEGER NOT NULL CHECK(observacoes_apos>0),
           origem TEXT NOT NULL
        )""")
        db.commit()
        if os.name=="posix":
            os.chmod(p,0o600)
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ErroIncrementalConab("integridade SQLite LAB falhou")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ErroIncrementalConab("chaves estrangeiras SQLite LAB inválidas")
        return db
    except BaseException:
        db.close()
        raise


def _manifest_sha(catalogo: dict):
    canonical=json.dumps(catalogo,sort_keys=True,ensure_ascii=False,
                         separators=(",",":"),allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def planejar_delta(db: sqlite3.Connection, catalogo: dict):
    entries=validar_catalogo_vintages(catalogo)["edicoes"]
    _stage(db)
    olds=list(db.execute("""SELECT sha,referencia_id,competencia,origem,
                          parser_sha,qtde FROM lab_referencia_conab"""))
    by_id={r[1]:r for r in olds}
    by_sha={r[0]:r for r in olds}
    by_week={r[2]:r for r in olds}
    nova=[]
    intacta=[]
    conflicts=[]
    for e in entries:
        i=e["id"]; sha=e["sha256"]
        same=by_id.get(i)
        if same is not None:
            if (same[0]!=sha or same[2]!=e["competencia"] or
                    same[3]!=e["origem_repositorio"]):
                conflicts.append({"id":i,"motivo":"EDICAO_MUDOU_SEM_REVISAO_EXPLICITA"})
            else:
                intacta.append(e)
                if same[4]!=hashlib.sha256(
                        (Path(__file__).parent/"conab_replay_xlsx.py").read_bytes()
                    ).hexdigest():
                    conflicts.append({"id":i,"motivo":"PARSER_JA_ARMAZENADO_DIFERENTE"})
                elif e["observacoes_esperadas"] is not None and same[5]!=e["observacoes_esperadas"]:
                    conflicts.append({"id":i,"motivo":"CONTAGEM_ORACULO_MODIFICADA"})
        elif sha in by_sha:
            conflicts.append({"id":i,"motivo":"HASH_JA_ASSOCIADO_A_OUTRA_EDICAO"})
        elif e["competencia"] in by_week:
            conflicts.append({"id":i,"motivo":"REVISAO_DA_SEMANA_NECESSITA_VERSIONAMENTO"})
        else:
            nova.append(e)
    return {
        "novas":nova,"inalteradas":intacta,"conflitos":conflicts,
        "edicoes_historicas_existentes":len(olds),
        "sha_catalogo":_manifest_sha(catalogo),
        "edicoes_historicas_nao_apagadas":len([r for r in olds if r[1] not in {e["id"] for e in entries}]),
        "migracao_permitida":False,
    }


def _read_only_counts(db):
    return (
        db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0],
    )


def _fingerprint(db):
    digest=hashlib.sha256()
    for q in (
        "SELECT sha,referencia_id,competencia,origem,parser_sha,qtde FROM lab_referencia_conab ORDER BY sha",
        "SELECT sha,chave,observacao_json FROM lab_observacao_conab ORDER BY sha,chave",
        "SELECT seq,executado_utc,manifesto_sha256,referencias_novas,observacoes_novas,observacoes_apos,origem FROM lab_eventos_incrementais ORDER BY seq",
    ):
        for row in db.execute(q):
            digest.update(json.dumps(row,ensure_ascii=False,
                  separators=(",",":"),allow_nan=False).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def backup_restore_lab(db: sqlite3.Connection, pasta_backup: Path):
    """Snapshot SQLite durável LAB, reabertura read-only e replay de integridade.

    Não é backup de produção. Pasta/arquivo privados e sem sobrescrita.
    """
    folder=_dir_private(pasta_backup)
    seq=db.execute("SELECT COALESCE(MAX(seq),0) FROM lab_eventos_incrementais").fetchone()[0]
    target=folder/f"conab-lab-seq-{seq:04d}.sqlite"
    if target.exists() or target.is_symlink():
        raise ErroIncrementalConab("backup do lote já existe; jamais sobrescrever")
    db.commit()
    hash_before=_fingerprint(db)
    try:
        with sqlite3.connect(str(target)) as destination:
            db.backup(destination,pages=64,sleep=0.01)
            destination.execute("PRAGMA journal_mode=DELETE")
        if os.name=="posix":
            os.chmod(target,0o600)
        with sqlite3.connect("file:"+str(target)+"?mode=ro",uri=True) as shadow:
            if shadow.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ErroIncrementalConab("backup SQLite não passou integridade")
            if shadow.execute("PRAGMA foreign_key_check").fetchall():
                raise ErroIncrementalConab("backup SQLite tem chaves estrangeiras inválidas")
            if _fingerprint(shadow)!=hash_before:
                raise ErroIncrementalConab("backup restaurado diverge linha por linha do LAB")
        raw_hash=hashlib.sha256(target.read_bytes()).hexdigest()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {
        "arquivo_backup":target.name,
        "sha256_backup":raw_hash,
        "backup_restaurado_e_conferido":True,
        "comparacao_logica_sha256":hash_before,
        "backup_destino":"STORAGE_PRIVADO_SOMENTE_LAB",
        "backup_de_producao":False,
    }


def sincronizar_incremental_lab(catalogo: dict, db_path: str | Path, pasta_backup: str | Path,
                               *, arquivos_locais: str | Path | None = None,
                               obter_do_github: bool = False,
                               transport=None, clock=None):
    """Executa apenas DELTA; sem edição nova não há GET, escrita nem backup.

    Cada rodada que adiciona edições processa todas as novas em uma só
    transação. Falha de qualquer parte do lote impede novas observações.
    """
    if (arquivos_locais is None)==(obter_do_github is False):
        raise ErroIncrementalConab("escolher exatamente uma entrada: pasta local ou GitHub")
    validated=validar_catalogo_vintages(catalogo)
    backupdir=_dir_private(pasta_backup)
    with closing(abrir_db_lab(db_path)) as db:
        plan=planejar_delta(db,validated)
        if plan["conflitos"]:
            raise ErroIncrementalConab("conflito de edição/revisão/política parser: "+
                                       json.dumps(plan["conflitos"],ensure_ascii=False))
        before=_read_only_counts(db)
        if not plan["novas"]:
            return {
                "estado":"SEM_DELTA_NENHUM_DOWNLOAD_OU_GRAVACAO",
                "edicoes_novas":0,"edicoes_inalteradas":len(plan["inalteradas"]),
                "edicoes_historicas_preservadas":before[0],
                "observacoes_no_lab":before[1],
                "requisicoes_previstas":0,"backup_criado":False,
                "fonte_oficial_conab":False,"direitos_uso_auditados":False,
                "migracao_permitida":False,"publicacao_permitida":False,
            }
        subset={**validated,"edicoes":plan["novas"]}
        with tempfile.TemporaryDirectory(prefix="nivon-delta-xlsx-") as tmp:
            selected=Path(tmp)
            if obter_do_github:
                fetch=obter_referencias_terceiro(subset,selected,transport=transport)
            else:
                rawdir=Path(arquivos_locais)
                if not rawdir.is_absolute() or not rawdir.is_dir() or rawdir.is_symlink():
                    raise ErroIncrementalConab("diretório de RAW local inválido")
                for entry in plan["novas"]:
                    file=rawdir/entry["arquivo"]
                    if file.is_symlink() or not file.is_file() or file.stat().st_size!=entry["bytes"]:
                        raise ErroIncrementalConab("RAW novo ausente, symlink ou tamanho incorreto")
                    raw=file.read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
                        raise ErroIncrementalConab("SHA de RAW local difere do catálogo")
                    (selected/entry["arquivo"]).write_bytes(raw)
                fetch={"baixados":0,"bytes":0}
            audit=auditar_vintages_conab(subset,selected)
            if audit["edicoes_pendentes"] or audit["edicoes_presentes_reprocessadas"]!=len(plan["novas"]):
                raise ErroIncrementalConab("delta incompleto não deve escrever LAB")
            batch=[]
            for e in plan["novas"]:
                raw=(selected/e["arquivo"]).read_bytes()
                result=reexecutar_xlsx_conab(
                    raw,sha256_origem=e["sha256"],
                    url_origem=e["url_original_declarada"],
                    coletado_em=e["captura_declarada"],publicado_em=None,
                )
                pairs=sorted((json.dumps(k,ensure_ascii=False,separators=(",",":")),v)
                             for k,v in result["mapa_semantico"].items())
                if len(pairs)!=result["observacoes"] or not pairs:
                    raise ErroIncrementalConab("parsing do delta contém chaves conflitantes")
                batch.append((e,result,pairs))
            now=clock() if clock else datetime.now(timezone.utc)
            if not isinstance(now,datetime) or now.utcoffset() is None:
                raise ErroIncrementalConab("instante da execução sem fuso")
            try:
                with db:
                    for entry,parsed,pairs in batch:
                        db.execute("INSERT INTO lab_referencia_conab VALUES (?,?,?,?,?,?)",
                                   (entry["sha256"],entry["id"],entry["competencia"],
                                    entry["origem_repositorio"],parsed["parser_codigo_sha256"],len(pairs)))
                        db.executemany("INSERT INTO lab_observacao_conab VALUES (?,?,?)",
                            [(entry["sha256"],k,v) for k,v in pairs])
                    after=_read_only_counts(db)
                    if after!=(before[0]+len(batch),before[1]+sum(len(x[2]) for x in batch)):
                        raise ErroIncrementalConab("contagens da transação não conferem")
                    db.execute("""INSERT INTO lab_eventos_incrementais
                        (executado_utc,manifesto_sha256,referencias_novas,
                         observacoes_novas,observacoes_apos,origem)
                        VALUES(?,?,?,?,?,?)""",
                        (now.astimezone(timezone.utc).isoformat(),
                         plan["sha_catalogo"],len(batch),
                         sum(len(x[2]) for x in batch),after[1],
                         "GITHUB_PUBLICO_REFERENCIA_TERCEIRO" if obter_do_github
                         else "ARQUIVOS_LOCAIS_SHA_VERIFICADOS"))
                    if db.execute("PRAGMA foreign_key_check").fetchall():
                        raise ErroIncrementalConab("falha foreign_key_check no delta")
            except sqlite3.Error as exc:
                raise ErroIncrementalConab("transação de delta foi abortada") from exc
            backup=backup_restore_lab(db,backupdir)
            return {
                "estado":"DELTA_LAB_GRAVADO_E_BACKUP_RECONFERIDO",
                "edicoes_novas":len(batch),
                "edicoes_inalteradas":len(plan["inalteradas"]),
                "edicoes_historicas_preservadas":before[0],
                "observacoes_novas":sum(len(x[2]) for x in batch),
                "observacoes_no_lab":after[1],
                "requisicoes_previstas":len(batch) if obter_do_github else 0,
                "download_terceiro":fetch,
                "backup":backup,
                "edicoes_processadas":[{
                    "competencia":e["competencia"],"observacoes":len(pairs),
                    "sha256":e["sha256"],
                } for e,_,pairs in batch],
                "fonte_oficial_conab":False,"direitos_uso_auditados":False,
                "migracao_permitida":False,"publicacao_permitida":False,
            }


def main(argv=None):
    p=argparse.ArgumentParser(description="Sincronização incremental LAB CONAB, nunca dados oficiais")
    p.add_argument("--catalogo",required=True)
    p.add_argument("--banco",required=True)
    p.add_argument("--backup-dir",required=True)
    p.add_argument("--arquivos-locais")
    p.add_argument("--obter-do-github",action="store_true")
    p.add_argument("--resumo",action="store_true")
    a=p.parse_args(argv)
    try:
        doc=_json_strict(Path(a.catalogo))
        report=sincronizar_incremental_lab(
            doc,a.banco,a.backup_dir,
            arquivos_locais=a.arquivos_locais,
            obter_do_github=a.obter_do_github,
        )
    except (OSError,ValueError,sqlite3.Error) as exc:
        p.error(str(exc))
    if a.resumo:
        report.pop("edicoes_processadas",None)
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
