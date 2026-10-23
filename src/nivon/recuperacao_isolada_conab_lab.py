"""Recuperação de SQLite exclusivamente LAB em diretório novo e isolado.

Exige SHA-256 externo conhecido da cópia, confirma integridade e linhagem,
executa cópia SQLite no destino SEM sobrescrever, reconcilia com banco vivo
opcional e preserva evidência da restauração. Não escreve fonte/canônico,
não altera Cloud, não prova autenticidade externa ou direitos dos dados.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .auditoria_vintages_conab import _json_strict, validar_catalogo_vintages
from .sincronizacao_incremental_conab_lab import (
    _auditar_historico_local, _fingerprint, _dir_private,
)
from .revisoes_conab_lab import (
    _audit_revisions, _rev_fingerprint, consultar_versao_asof_lab,
)

SCHEMA="NIVON_CONAB_RESTAURACAO_ISOLADA_LAB_V1"
FILE_RE=re.compile(r"conab-(?:lab|retif)-seq-[0-9]{4}\.sqlite\Z")
SHA_RE=re.compile(r"[0-9a-f]{64}\Z")
RESTORED_NAME="conab-recuperado-lab.sqlite"
EVIDENCE_NAME="recuperacao-evidencia-lab.json"
MAX_SIZE=100_000_000


class ErroRecuperacaoConab(ValueError):
    pass


def _readonly(path: Path):
    # URI escapada: nomes com '?', '#' etc não podem modificar parâmetros SQLite
    uri="file:"+quote(str(path),safe="/")+ "?mode=ro"
    db=sqlite3.connect(uri,uri=True,timeout=5)
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA query_only=ON")
    return db


def _validate_path(path: Path, *, expect_file=True):
    if not path.is_absolute() or path.is_symlink():
        raise ErroRecuperacaoConab("caminho precisa ser absoluto e sem symlink")
    if expect_file:
        if not path.is_file() or not 0<path.stat().st_size<=MAX_SIZE:
            raise ErroRecuperacaoConab("SQLite de origem não regular, ausente ou acima do limite")
        if os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077:
            raise ErroRecuperacaoConab("SQLite original não é privado (0600)")
    return path


def _hexdigest(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as file:
        for piece in iter(lambda:file.read(1024*1024),b""):
            h.update(piece)
    return h.hexdigest()


def _audit_sql(db, cat):
    if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
        raise ErroRecuperacaoConab("SQLite não passou integrity_check")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ErroRecuperacaoConab("SQLite viola foreign_key_check")
    _auditar_historico_local(db)
    current_sha=hashlib.sha256(
        (Path(__file__).parent/"conab_replay_xlsx.py").read_bytes()
    ).hexdigest()
    rows=list(db.execute("""SELECT referencia_id,sha,competencia,parser_sha
                             FROM lab_referencia_conab ORDER BY competencia,referencia_id"""))
    known={e["id"]:e for e in validar_catalogo_vintages(cat)["edicoes"]}
    for ident,sha,week,parser in rows:
        if ident not in known or known[ident]["sha256"]!=sha or known[ident]["competencia"]!=week:
            raise ErroRecuperacaoConab("referência no backup não pertence ao catálogo validado")
        if parser!=current_sha:
            raise ErroRecuperacaoConab("versão do parser não corresponde às linhas gravadas")
    revisions=db.execute("""SELECT 1 FROM sqlite_master
                            WHERE name='lab_retificacoes_conab' AND type='table'""").fetchone()
    rev_count=0
    rev_fingerprint=None
    if revisions:
        _audit_revisions(db)
        rev_count=db.execute("SELECT COUNT(*) FROM lab_retificacoes_conab").fetchone()[0]
        rev_fingerprint=_rev_fingerprint(db)
    if not rows:
        raise ErroRecuperacaoConab("snapshot LAB vazio não serve à recuperação")
    return {
        "fingerprint_base":_fingerprint(db),
        "fingerprint_retificacoes":rev_fingerprint,
        "originais":len(rows),
        "retificacoes":rev_count,
        "observacoes_originais":db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0],
        "observacoes_retificacoes":(
            db.execute("SELECT COUNT(*) FROM lab_retificacao_observacoes").fetchone()[0]
            if revisions else 0),
    }


def _asof(db, cat, cutoffs):
    output=[]
    for entry in cat["edicoes"]:
        # Pode-se restaurar snapshot anterior à inclusão de uma edição catalogada.
        known=db.execute("SELECT 1 FROM lab_referencia_conab WHERE referencia_id=? AND sha=?",
                         (entry["id"],entry["sha256"])).fetchone()
        if known is None:
            continue
        for cutoff in cutoffs:
            row=consultar_versao_asof_lab(db,cat,id_base=entry["id"],corte_coleta=cutoff)
            output.append({
                "id":entry["id"],"corte_coleta":cutoff,
                "versao_sha":row.get("sha_versao"),
                "revisao":row.get("revisao"),
                "observacoes":row["observacoes"],
                "sha_semantico":row.get("sha_semantico"),
            })
    return output


def recuperar_backup_isolado(
    backup_path: str | Path,
    sha256_esperado: str,
    catalogo: dict,
    destino: str | Path,
    *,
    banco_vivo: str | Path | None = None,
    cortes_coleta: list[str] | None = None,
):
    """Somente cria SQLite + relatório em pasta privada VAZIA.

    A evidência SHA esperada deve vir de canal externo a este diretório:
    ler o próprio SHA do snapshot suspeito não constitui comprovação.
    """
    if type(sha256_esperado) is not str or not SHA_RE.fullmatch(sha256_esperado):
        raise ErroRecuperacaoConab("SHA-256 esperado inválido/ausente")
    cat=validar_catalogo_vintages(catalogo)
    path=_validate_path(Path(backup_path))
    if not FILE_RE.fullmatch(path.name):
        raise ErroRecuperacaoConab("backup não pertence ao contrato de nomes LAB")
    folder=_dir_private(destino)
    if any(folder.iterdir()):
        raise ErroRecuperacaoConab("destino de recuperação deve estar vazio; não sobrescrever")
    if banco_vivo is not None:
        live_path=_validate_path(Path(banco_vivo))
        if live_path.resolve()==path.resolve():
            raise ErroRecuperacaoConab("banco vivo não pode ser o próprio backup")
    else:
        live_path=None
    if cortes_coleta is None:
        cortes_coleta=[]
    if (not isinstance(cortes_coleta,list) or len(cortes_coleta)>20
        or any(not isinstance(x,str) or len(x)>64 for x in cortes_coleta)):
        raise ErroRecuperacaoConab("cortes de coleta inválidos")
    if _hexdigest(path)!=sha256_esperado:
        raise ErroRecuperacaoConab("SHA do backup difere da evidência fornecida")
    recovered=folder/RESTORED_NAME
    evidence=folder/EVIDENCE_NAME
    created=[]
    try:
        with closing(_readonly(path)) as origin:
            orig_state=_audit_sql(origin,cat)
            orig_asof=_asof(origin,cat,cortes_coleta)
            # O_EXCL impede corrida/sobrescrita, não confiamos em check-then-write.
            fd=os.open(recovered,os.O_WRONLY|os.O_CREAT|os.O_EXCL
                       |getattr(os,"O_NOFOLLOW",0),0o600)
            os.close(fd)
            created.append(recovered)
            with closing(sqlite3.connect(str(recovered))) as shadow:
                origin.backup(shadow,pages=64,sleep=0.01)
                shadow.commit()
        with closing(_readonly(recovered)) as destdb:
            dest_state=_audit_sql(destdb,cat)
            dest_asof=_asof(destdb,cat,cortes_coleta)
        if orig_state!=dest_state or orig_asof!=dest_asof:
            raise ErroRecuperacaoConab("restauração difere do snapshot original")
        live_comparison={
            "comparacao_realizada":False,
            "equivalencia_com_banco_vivo":None,
            "observacao":"banco vivo não informado; snapshot conferido internamente",
        }
        if live_path is not None:
            with closing(_readonly(live_path)) as live:
                live_state=_audit_sql(live,cat)
                live_asof=_asof(live,cat,cortes_coleta)
            live_comparison={
                "comparacao_realizada":True,
                "equivalencia_com_banco_vivo":live_state==dest_state and live_asof==dest_asof,
                "divergencias":{
                    "originais":live_state["originais"]-dest_state["originais"],
                    "retificacoes":live_state["retificacoes"]-dest_state["retificacoes"],
                    "observacoes_originais":live_state["observacoes_originais"]-dest_state["observacoes_originais"],
                    "observacoes_retificacoes":live_state["observacoes_retificacoes"]-dest_state["observacoes_retificacoes"],
                    "fingerprint_base_divergente":live_state["fingerprint_base"]!=dest_state["fingerprint_base"],
                    "fingerprint_retificacoes_divergente":live_state["fingerprint_retificacoes"]!=dest_state["fingerprint_retificacoes"],
                    "visao_asof_divergente":live_asof!=dest_asof,
                },
            }
        result={
            "schema":SCHEMA,
            "estado":"BACKUP_RESTAURADO_EM_AMBIENTE_ISOLADO_LAB",
            "snapshot_original":path.name,
            "sha256_snapshot_esperado":sha256_esperado,
            "sha256_snapshot_verificado":True,
            "arquivo_restaurado":RESTORED_NAME,
            "sha256_restaurado":_hexdigest(recovered),
            "bytes_restaurados":recovered.stat().st_size,
            "restauracao_integridade_fk_semantica_conferida":True,
            "resumo_restaurado":dest_state,
            "cortes_asof":dest_asof,
            "comparacao":live_comparison,
            "evidencia_produzida_localmente_sem_assinatura_externa":True,
            "sha_externo_autenticado_criptograficamente":False,
            "origem_conab_direta_autenticada":False,
            "direitos_de_uso_homologados":False,
            "banco_canonico_modificado":False,
            "banco_de_producao_modificado":False,
            "migracao_permitida":False,
            "publicacao_permitida":False,
        }
        payload=(json.dumps(result,ensure_ascii=False,indent=2,
                            sort_keys=True,allow_nan=False)+"\n").encode("utf-8")
        fd=os.open(evidence,os.O_WRONLY|os.O_CREAT|os.O_EXCL
                   |getattr(os,"O_NOFOLLOW",0),0o600)
        created.append(evidence)
        with os.fdopen(fd,"wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        return result
    except BaseException:
        for f in reversed(created):
            f.unlink(missing_ok=True)
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description="Restaurar backup LAB CONAB em pasta nova sem tocar original")
    p.add_argument("--backup",required=True)
    p.add_argument("--sha256-esperado",required=True)
    p.add_argument("--catalogo",required=True)
    p.add_argument("--destino",required=True)
    p.add_argument("--banco-vivo")
    p.add_argument("--corte-coleta",action="append",default=[])
    args=p.parse_args(argv)
    try:
        cat=_json_strict(Path(args.catalogo))
        result=recuperar_backup_isolado(
            args.backup,args.sha256_esperado,cat,args.destino,
            banco_vivo=args.banco_vivo,cortes_coleta=args.corte_coleta)
    except (sqlite3.Error,OSError,ValueError) as exc:
        p.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
