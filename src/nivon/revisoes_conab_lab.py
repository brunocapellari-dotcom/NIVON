"""LAB exclusivamente: retificações explícitas, imutáveis e encadeadas.

Não representa retificação publicada pela CONAB. Eventos de teste
alteram artificialmente os bytes de fixture pública de terceiro,
identificados inequivocamente como SIMULACAO_LAB. Nunca remove versões.
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
from datetime import datetime, timezone
from pathlib import Path

from .auditoria_vintages_conab import _json_strict, validar_catalogo_vintages
from .conab_replay_xlsx import ErroXlsxProgresso, reexecutar_xlsx_conab
from .sincronizacao_incremental_conab_lab import (
    ErroIncrementalConab, abrir_db_lab, _auditar_historico_local,
    _dir_private, _fingerprint, _sha_observacoes,
)

SCHEMA="NIVON_CONAB_RETIFICACOES_SINTETICAS_LAB_V1"
_SHA=re.compile(r"[a-f0-9]{64}\Z")
_FILE=re.compile(r"retificacao-[0-9]{8}-[0-9]{3}\.xlsx\Z")
_ID=re.compile(r"RETIF_LAB_[0-9]{8}_[0-9]{3}\Z")
_REASON="SIMULACAO_LAB_NAO_PUBLICADA_PELA_CONAB"
_EVIDENCE="XLSX_FIXTURE_ALTERADA_SINTETICAMENTE"
_PARSER_FILE=Path(__file__).parent/"conab_replay_xlsx.py"
_FIELDS={"id","id_base","sha_base","sha_anterior","sha256",
         "arquivo","tamanho","competencia","coletado_em","motivo","evidencia"}


class ErroRetificacaoConab(ValueError):
    pass


def _schema(db):
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lab_retificacoes_conab(
          sha TEXT PRIMARY KEY,
          id TEXT NOT NULL UNIQUE,
          sha_base TEXT NOT NULL REFERENCES lab_referencia_conab(sha),
          sha_anterior TEXT NOT NULL,
          competencia TEXT NOT NULL,
          revisao INTEGER NOT NULL CHECK(revisao>0),
          sha_parser TEXT NOT NULL,
          sha_semantico TEXT NOT NULL,
          quantidade INTEGER NOT NULL CHECK(quantidade>0),
          coletado_utc TEXT NOT NULL,
          motivo TEXT NOT NULL CHECK(motivo='SIMULACAO_LAB_NAO_PUBLICADA_PELA_CONAB'),
          evidencia TEXT NOT NULL,
          alterados INTEGER NOT NULL CHECK(alterados>=0),
          incluidos INTEGER NOT NULL CHECK(incluidos>=0),
          excluidos INTEGER NOT NULL CHECK(excluidos>=0),
          UNIQUE(sha_base,revisao), UNIQUE(sha_base,sha_anterior)
        );
        CREATE TABLE IF NOT EXISTS lab_retificacao_observacoes(
          sha TEXT NOT NULL REFERENCES lab_retificacoes_conab(sha),
          chave TEXT NOT NULL,
          observacao_json TEXT NOT NULL,
          PRIMARY KEY(sha,chave)
        );
        CREATE TABLE IF NOT EXISTS lab_retificacao_eventos(
          seq INTEGER PRIMARY KEY,
          sha TEXT NOT NULL UNIQUE REFERENCES lab_retificacoes_conab(sha),
          sha_anterior TEXT NOT NULL,
          id_base TEXT NOT NULL,
          registrado_utc TEXT NOT NULL
        );
    """)
    db.commit()


def _validate_ref(ref, catalog):
    if not isinstance(ref,dict) or set(ref)!=_FIELDS:
        raise ErroRetificacaoConab("manifesto de retificação não segue campos estritos")
    if (not _ID.fullmatch(str(ref["id"])) or
        not _FILE.fullmatch(str(ref["arquivo"])) or
        ref["arquivo"].removeprefix("retificacao-").removesuffix(".xlsx").replace("-","_") !=
        ref["id"].removeprefix("RETIF_LAB_").lower()):
        raise ErroRetificacaoConab("ID e arquivo da simulação não correspondem")
    if (not all(type(ref[k]) is str and _SHA.fullmatch(ref[k]) for k in
                ("sha_base","sha_anterior","sha256"))
        or ref["sha256"] in {ref["sha_anterior"],ref["sha_base"]}):
        raise ErroRetificacaoConab("SHA da retificação inválido/igual ao anterior")
    if type(ref["tamanho"]) is not int or not 0<ref["tamanho"]<=20_000_000:
        raise ErroRetificacaoConab("tamanho da retificação inválido")
    if ref["motivo"]!=_REASON or ref["evidencia"]!=_EVIDENCE:
        raise ErroRetificacaoConab("somente simulação LAB é permitida nesta etapa")
    base=next((x for x in catalog["edicoes"] if x["id"]==ref["id_base"]),None)
    if base is None or base["sha256"]!=ref["sha_base"] or base["competencia"]!=ref["competencia"]:
        raise ErroRetificacaoConab("base/competência não corresponde à fonte catalogada")
    try:
        now=datetime.fromisoformat(ref["coletado_em"].replace("Z","+00:00"))
        start=datetime.fromisoformat(base["captura_declarada"].replace("Z","+00:00"))
        if now.tzinfo is None or now.utcoffset() is None or now<start:
            raise ValueError("data de revisão antecede o arquivo de referência")
    except (ValueError,TypeError) as exc:
        raise ErroRetificacaoConab("instante simulado da revisão inválido") from exc
    return base,now.astimezone(timezone.utc).isoformat()


def _load_manifest(doc, catalog):
    validar_catalogo_vintages(catalog)
    if (not isinstance(doc,dict) or set(doc)!={"schema","revisoes"} or doc["schema"]!=SCHEMA
        or not isinstance(doc["revisoes"],list) or not 1<=len(doc["revisoes"])<=12):
        raise ErroRetificacaoConab("manifesto de simulação inválido")
    for r in doc["revisoes"]:_validate_ref(r,catalog)
    for key in ("id","sha256","arquivo"):
        vals=[r[key] for r in doc["revisoes"]]
        if len(vals)!=len(set(vals)):
            raise ErroRetificacaoConab("revisão duplicada no manifesto: "+key)
    return doc["revisoes"]


def _head(db,sha_base):
    rows=list(db.execute("""SELECT sha,sha_anterior,revisao FROM lab_retificacoes_conab
                  WHERE sha_base=? ORDER BY revisao""",(sha_base,)))
    last=sha_base
    for n,(sha,parent,seq) in enumerate(rows,start=1):
        if seq!=n or parent!=last:
            raise ErroRetificacaoConab("linhagem contém lacuna, desvio ou bifurcação")
        last=sha
    return last,len(rows)


def _instante_utc(value):
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("sem timezone")
        return dt.astimezone(timezone.utc)
    except (AttributeError,ValueError) as exc:
        raise ErroRetificacaoConab("instante de corte sem fuso ou inválido") from exc


def _pairs(db,sha):
    if db.execute("SELECT 1 FROM lab_referencia_conab WHERE sha=?",(sha,)).fetchone():
        return dict(db.execute("SELECT chave,observacao_json FROM lab_observacao_conab WHERE sha=?",(sha,)))
    return dict(db.execute("SELECT chave,observacao_json FROM lab_retificacao_observacoes WHERE sha=?",(sha,)))


def _difference(old,new):
    a,b=set(old),set(new)
    changed=sum(old[k]!=new[k] for k in a&b)
    return {"alterados":changed,"incluidos":len(b-a),"excluidos":len(a-b)}


def _audit_revisions(db):
    parser_sha=hashlib.sha256(_PARSER_FILE.read_bytes()).hexdigest()
    rows=list(db.execute("""SELECT sha,id,sha_base,sha_anterior,competencia,revisao,
              sha_parser,sha_semantico,quantidade,alterados,incluidos,excluidos
              FROM lab_retificacoes_conab ORDER BY sha_base,revisao"""))
    by_base={}
    for row in rows:
        sha,ident,base,parent,week,step,p_sha,semantic,n,changed,added,removed=row
        b=db.execute("SELECT competencia FROM lab_referencia_conab WHERE sha=?",(base,)).fetchone()
        if not b or b[0]!=week or p_sha!=parser_sha:
            raise ErroRetificacaoConab("base, competência ou parser da revisão divergentes")
        by_base.setdefault(base,[]).append((sha,parent,step))
        pairs=_pairs(db,sha)
        if len(pairs)!=n or _sha_observacoes(pairs.items())!=semantic:
            raise ErroRetificacaoConab("conteúdo das retificações alterado/incompleto")
        predecessor=_pairs(db,parent)
        if not predecessor or _difference(predecessor,pairs)!={
                "alterados":changed,"incluidos":added,"excluidos":removed}:
            raise ErroRetificacaoConab("delta retificado diverge da versão anterior")
        ev=db.execute("SELECT COUNT(*) FROM lab_retificacao_eventos WHERE sha=? AND sha_anterior=?",
                      (sha,parent)).fetchone()[0]
        if ev!=1:
            raise ErroRetificacaoConab("evento de revisão ausente/divergente")
    for base,items in by_base.items():
        last=base
        for i,(sha,parent,step) in enumerate(items,start=1):
            if step!=i or parent!=last:
                raise ErroRetificacaoConab("linhagem de revisão perdeu ordem ou bifurcou")
            last=sha
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ErroRetificacaoConab("revisões violam integridade referencial")


def _rev_fingerprint(db):
    digest=hashlib.sha256()
    for query in (
        """SELECT sha,id,sha_base,sha_anterior,competencia,revisao,sha_parser,sha_semantico,
               quantidade,coletado_utc,motivo,evidencia,alterados,incluidos,excluidos
               FROM lab_retificacoes_conab ORDER BY sha""",
        "SELECT sha,chave,observacao_json FROM lab_retificacao_observacoes ORDER BY sha,chave",
        "SELECT seq,sha,sha_anterior,id_base,registrado_utc FROM lab_retificacao_eventos ORDER BY seq",
    ):
        for r in db.execute(query):
            digest.update(json.dumps(r,ensure_ascii=False,separators=(",",":")).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def verificar_integridade_retificacoes_lab(db,folder):
    existing=db.execute("""SELECT 1 FROM sqlite_master
                            WHERE type='table' AND name='lab_retificacoes_conab'""").fetchone()
    if not existing:
        return {"revisoes":0,"backup_retificacoes_valido":True}
    _audit_revisions(db)
    revs=db.execute("SELECT COUNT(*) FROM lab_retificacoes_conab").fetchone()[0]
    if not revs:
        return {"revisoes":0,"backup_retificacoes_valido":True}
    n=db.execute("SELECT MAX(seq) FROM lab_retificacao_eventos").fetchone()[0]
    file=_dir_private(folder)/f"conab-retif-seq-{n:04d}.sqlite"
    if file.is_symlink() or not file.is_file():
        raise ErroRetificacaoConab("backup da retificação ausente ou symlink")
    if os.name=="posix" and stat.S_IMODE(file.stat().st_mode)&0o077:
        raise ErroRetificacaoConab("backup de retificação exposto")
    try:
        with closing(sqlite3.connect("file:"+str(file)+"?mode=ro",uri=True)) as b:
            if b.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ErroRetificacaoConab("backup da retificação corrompido")
            if b.execute("PRAGMA foreign_key_check").fetchall():
                raise ErroRetificacaoConab("backup da retificação com FK inválida")
            if _rev_fingerprint(b)!=_rev_fingerprint(db):
                raise ErroRetificacaoConab("backup da retificação diverge da versão atual")
    except sqlite3.Error as exc:
        raise ErroRetificacaoConab("erro de leitura no backup de retificação") from exc
    return {"revisoes":revs,"backup_retificacoes_valido":True}


def _backup_revisoes(db,folder):
    folder=_dir_private(folder)
    n=db.execute("SELECT MAX(seq) FROM lab_retificacao_eventos").fetchone()[0]
    file=folder/f"conab-retif-seq-{n:04d}.sqlite"
    if file.exists() or file.is_symlink():
        raise ErroRetificacaoConab("backup de retificação já existe; sem sobrescrita")
    db.commit()
    original=_rev_fingerprint(db)
    try:
        fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
        os.close(fd)
        with closing(sqlite3.connect(str(file))) as b:
            db.backup(b,pages=64,sleep=0.01)
            b.commit()
        if os.name=="posix":os.chmod(file,0o600)
        with closing(sqlite3.connect("file:"+str(file)+"?mode=ro",uri=True)) as restored:
            if restored.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or (
                restored.execute("PRAGMA foreign_key_check").fetchall()):
                raise ErroRetificacaoConab("backup de retificação falhou integrity/fk")
            if _rev_fingerprint(restored)!=original:
                raise ErroRetificacaoConab("backup de retificação divergiu do original")
        sha=hashlib.sha256(file.read_bytes()).hexdigest()
    except BaseException:
        file.unlink(missing_ok=True)
        raise
    return {"arquivo":file.name,"sha256":sha,"restore_verificado":True,"producao":False}


def aplicar_retificacoes_lab(catalogo,manifesto,banco,pasta_raw,pasta_backups):
    refs=_load_manifest(manifesto,catalogo)
    root=Path(pasta_raw)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ErroRetificacaoConab("pasta local de RAW não encontrada")
    _dir_private(pasta_backups)
    with closing(abrir_db_lab(banco)) as db:
        _auditar_historico_local(db)
        _schema(db)
        _audit_revisions(db)
        before=verificar_integridade_retificacoes_lab(db,pasta_backups)
        items=[]
        # O lote é encadeado na ordem apresentada: pode conter mais de uma
        # revisão da mesma base, sempre com parent exato anterior.
        heads={x["sha_base"]:list(_head(db,x["sha_base"])) for x in refs}
        new_ids=set()
        for entry in refs:
            base,ts=_validate_ref(entry,catalogo)
            row=db.execute("""SELECT id,sha_base,sha_anterior,competencia,coletado_utc
                    FROM lab_retificacoes_conab WHERE sha=?""",(entry["sha256"],)).fetchone()
            if row is not None:
                if tuple(row)!=(entry["id"],entry["sha_base"],entry["sha_anterior"],
                                   entry["competencia"],ts):
                    raise ErroRetificacaoConab("mesmo SHA com evidência de retificação divergente")
                items.append((entry,None,None,None,True))
                continue
            if entry["sha256"] in new_ids:
                raise ErroRetificacaoConab("mesmo SHA repetido no lote")
            h,n=heads[entry["sha_base"]]
            if entry["sha_anterior"]!=h:
                raise ErroRetificacaoConab("revisão sem predecessor linear exato")
            if h==entry["sha_base"]:
                parent_time=_instante_utc(base["captura_declarada"])
            elif h in new_ids:
                parent_time=_instante_utc(next(
                    item[1] for item in items if item[0]["sha256"]==h))
            else:
                prev=db.execute("SELECT coletado_utc FROM lab_retificacoes_conab WHERE sha=?",(h,)).fetchone()
                if not prev:
                    raise ErroRetificacaoConab("predecessor não possui horário de captura")
                parent_time=_instante_utc(prev[0])
            if _instante_utc(ts)<=parent_time:
                raise ErroRetificacaoConab("retificação capturada antes ou junto à versão predecessora")
            original=db.execute("SELECT 1 FROM lab_referencia_conab WHERE sha=?",
                                (entry["sha_base"],)).fetchone()
            if original is None:
                raise ErroRetificacaoConab("a referência original precisa ter sido persistida")
            file=root/entry["arquivo"]
            if file.is_symlink() or not file.is_file() or file.stat().st_size!=entry["tamanho"]:
                raise ErroRetificacaoConab("XLSX da revisão ausente, symlink ou tamanho errado")
            raw=file.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
                raise ErroRetificacaoConab("SHA do XLSX retificado não confere")
            try:
                parsed=reexecutar_xlsx_conab(raw,sha256_origem=entry["sha256"],
                    url_origem=base["url_original_declarada"],
                    coletado_em=entry["coletado_em"],publicado_em=None)
            except ErroXlsxProgresso as exc:
                raise ErroRetificacaoConab("layout ou valores da revisão rejeitados pelo parser") from exc
            if parsed["parser_codigo_sha256"]!=hashlib.sha256(_PARSER_FILE.read_bytes()).hexdigest():
                raise ErroRetificacaoConab("parser mudou durante lote")
            pairs=sorted((json.dumps(k,ensure_ascii=False,separators=(",",":")),v)
                          for k,v in parsed["mapa_semantico"].items())
            if not pairs or len(pairs)!=parsed["observacoes"]:
                raise ErroRetificacaoConab("revisão vazia ou chaves colididas")
            if {json.loads(v)["competencia"] for _,v in pairs}!={entry["competencia"]}:
                raise ErroRetificacaoConab("semana extraída difere da revisão declarada")
            if any(json.loads(v)["source_url"]!=base["url_original_declarada"] for _,v in pairs):
                raise ErroRetificacaoConab("origem alterada no conteúdo")
            parent_map=_pairs(db,h) if h not in new_ids else next(
                dict(j[2]) for j in items if j[0]["sha256"]==h)
            diff=_difference(parent_map,dict(pairs))
            if not sum(diff.values()):
                raise ErroRetificacaoConab("bytes alterados mas nenhuma observação revisada")
            new_ids.add(entry["sha256"])
            heads[entry["sha_base"]]=[entry["sha256"],n+1]
            items.append((entry,ts,pairs,diff,False))
        new=[x for x in items if not x[4]]
        if not new:
            return {
                "estado":"SEM_RETIFICACAO_NOVA","retificacoes_novas":0,
                "retificacoes_preservadas":before["revisoes"],
                "backup_criado":False,
                "rede_consultada":False,
                "publicacao_permitida":False,"migracao_permitida":False,
            }
        try:
            with db:
                for e,ts,pairs,diff,_ in new:
                    step=db.execute("""SELECT COUNT(*) FROM lab_retificacoes_conab
                                       WHERE sha_base=?""",(e["sha_base"],)).fetchone()[0]+1
                    db.execute("""INSERT INTO lab_retificacoes_conab
                        (sha,id,sha_base,sha_anterior,competencia,revisao,
                        sha_parser,sha_semantico,quantidade,coletado_utc,
                        motivo,evidencia,alterados,incluidos,excluidos)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                        e["sha256"],e["id"],e["sha_base"],e["sha_anterior"],
                        e["competencia"],step,
                        hashlib.sha256(_PARSER_FILE.read_bytes()).hexdigest(),
                        _sha_observacoes(pairs),len(pairs),ts,
                        e["motivo"],e["evidencia"],diff["alterados"],
                        diff["incluidos"],diff["excluidos"]))
                    db.executemany("INSERT INTO lab_retificacao_observacoes VALUES(?,?,?)",
                        [(e["sha256"],k,v) for k,v in pairs])
                    db.execute("""INSERT INTO lab_retificacao_eventos
                        (sha,sha_anterior,id_base,registrado_utc) VALUES(?,?,?,?)""",
                        (e["sha256"],e["sha_anterior"],e["id_base"],ts))
                _audit_revisions(db)
        except sqlite3.Error as exc:
            raise ErroRetificacaoConab("transação de revisão falhou; nenhuma versão substituída") from exc
        backup=_backup_revisoes(db,pasta_backups)
        return {
            "estado":"RETIFICACOES_SINTETICAS_LAB_ENCADEADAS",
            "retificacoes_novas":len(new),
            "retificacoes_preservadas":before["revisoes"],
            "retificacoes_totais":before["revisoes"]+len(new),
            "deltas":[{
                "id":e["id"],"sha_anterior":e["sha_anterior"],
                "sha_novo":e["sha256"],**diff
            } for e,_,_,diff,_ in new],
            "backup":backup,"rede_consultada":False,
            "dados_conab_retificados_de_fato":False,
            "direitos_homologados":False,
            "publicacao_permitida":False,"migracao_permitida":False,
        }


def consultar_versao_asof_lab(db, catalogo: dict, *, id_base: str,
                              corte_coleta: str) -> dict:
    """Visão histórica por COLETA, nunca por publicação presumida.

    Apenas laboratório: permite comparar as versões preservadas sem
    olhar uma retificação capturada após o corte.
    """
    cat=validar_catalogo_vintages(catalogo)
    target=next((x for x in cat["edicoes"] if x["id"]==id_base),None)
    if target is None:
        raise ErroRetificacaoConab("ID de edição base inexistente")
    cutoff=_instante_utc(corte_coleta)
    root=target["sha256"]
    base=db.execute("SELECT 1 FROM lab_referencia_conab WHERE sha=? AND referencia_id=?",
                    (root,id_base)).fetchone()
    if base is None:
        return {
            "estado":"EDICAO_NAO_PERSISTIDA_ATÉ_O_CORTE",
            "observacoes":0,
            "sha_versao":None,
            "asof":"DATA_DE_COLETA_NAO_COMPROVA_PUBLICACAO",
            "publicacao_permitida":False,
        }
    _auditar_historico_local(db)
    rev_table=db.execute("""SELECT 1 FROM sqlite_master
                            WHERE type='table' AND name='lab_retificacoes_conab'""").fetchone()
    revisions=[]
    if rev_table:
        _audit_revisions(db)
        revisions=list(db.execute("""SELECT sha,coletado_utc,revisao FROM lab_retificacoes_conab
                                   WHERE sha_base=? ORDER BY revisao""",(root,)))
    first=_instante_utc(target["captura_declarada"])
    if cutoff<first:
        return {
            "estado":"AINDA_SEM_EVIDENCIA_DE_COLETA",
            "observacoes":0,"sha_versao":None,
            "asof":"DATA_DE_COLETA_NAO_COMPROVA_PUBLICACAO",
            "publicacao_permitida":False,
        }
    last=first
    sha=root
    step=0
    for rev_sha,ts,n in revisions:
        instante=_instante_utc(ts)
        if instante<=last:
            raise ErroRetificacaoConab("revisões temporalmente fora de ordem")
        last=instante
        if instante<=cutoff:
            sha=rev_sha
            step=n
    pairs=_pairs(db,sha)
    if not pairs:
        raise ErroRetificacaoConab("edição vigente sem observações")
    return {
        "estado":"VERSAO_LAB_ASOF_POR_COLETA_SEM_HOMOLOGACAO",
        "id_base":id_base,
        "competencia":target["competencia"],
        "revisao":step,
        "sha_versao":sha,
        "observacoes":len(pairs),
        "sha_semantico":_sha_observacoes(pairs.items()),
        "asof":"DATA_DE_COLETA_NAO_COMPROVA_PUBLICACAO",
        "origem_conab_direta":False,"publicacao_permitida":False,
        "migracao_permitida":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Retificações simuladas, LAB local apenas")
    p.add_argument("--catalogo",required=True)
    p.add_argument("--manifesto",required=True)
    p.add_argument("--banco",required=True)
    p.add_argument("--raw-dir",required=True)
    p.add_argument("--backup-dir",required=True)
    args=p.parse_args(argv)
    try:
        cat=_json_strict(Path(args.catalogo))
        manifest=_json_strict(Path(args.manifesto))
        result=aplicar_retificacoes_lab(cat,manifest,args.banco,args.raw_dir,args.backup_dir)
    except (OSError,sqlite3.Error,ValueError) as exc:
        p.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
