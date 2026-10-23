"""Operação INMET/ANA por manifesto local, backups e verificação sem rede.

Nenhum modo baixa dados, chama ANA SSO, solicita credenciais ou agenda tarefas.
Recebe arquivos previamente autorizados e mantém fontes reais não homologadas.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .pipeline_medicoes_horarias import (
    ErroPipelineAmbiental, TIPOS, MAX_RAW, _pasta, abrir_banco_medicoes,
    preparar_arquivo_medicoes, importar_ciclo_medicoes, auditar_acervo_medicoes,
    relatorio_revisoes_medicoes,
)


def _lotes(path):
    source = Path(path)
    if (source.is_symlink() or not source.is_file() or
        source.suffix.lower() != ".json" or source.stat().st_size > 100_000):
        raise ErroPipelineAmbiental("manifesto JSON local regular obrigatório")
    try:
        obj = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ErroPipelineAmbiental("manifesto JSON inválido") from exc
    if (not isinstance(obj, dict) or set(obj) != {"schema", "projeto", "lotes"}
            or obj["schema"] != "1.0" or obj["projeto"] != "NIVON"
            or not isinstance(obj["lotes"], list) or not 1<=len(obj["lotes"])<=40):
        raise ErroPipelineAmbiental("estrutura do manifesto NIVON inválida")
    base=source.resolve().parent
    editions=[]
    seen=set()
    for entry in obj["lotes"]:
        if not isinstance(entry, dict) or set(entry) != {
            "arquivo","formato","estacao_id","ano","zona","coletado_em","classe"
        }:
            raise ErroPipelineAmbiental("entrada de manifesto incompleta")
        filename=entry["arquivo"]
        if (not isinstance(filename,str) or len(filename)>160 or
            filename in (".","..") or Path(filename).is_absolute() or
            "/" in filename or "\\" in filename or filename in seen):
            raise ErroPipelineAmbiental("caminho ou arquivo duplicado proibido")
        seen.add(filename)
        file=base / filename
        if file.is_symlink() or not file.is_file() or file.resolve().parent != base:
            raise ErroPipelineAmbiental("arquivo fora do diretório do manifesto")
        fmt=entry["formato"]
        if fmt not in TIPOS or not 12<=file.stat().st_size<=MAX_RAW[fmt]:
            raise ErroPipelineAmbiental("arquivo maior do que o limite por formato")
        raw=file.read_bytes()
        edition=preparar_arquivo_medicoes(
            formato=fmt,raw=raw,estacao_id=entry["estacao_id"],
            ano=entry["ano"],zona=entry["zona"],
            coletado_em=entry["coletado_em"],classe=entry["classe"])
        editions.append(edition)
    return editions


def executar_manifesto_medicoes(
    *, manifesto, modo="validar", banco=None, raw_dir=None,
    confirmar_gravacao=False,
):
    """Analisa todos os arquivos primeiro; grava de maneira atômica se pedido."""
    if modo not in ("validar","executar"):
        raise ErroPipelineAmbiental("modo inválido")
    edicoes=_lotes(manifesto)
    if modo=="validar":
        return {"estado":"PREFLIGHT_INMET_ANA_OK","arquivos":len(edicoes),
                "medidas":sum(len(e["registros"]) for e in edicoes),
                "http":0,"gravacoes":0,"homologado":False}
    if confirmar_gravacao is not True or not banco or not raw_dir:
        raise PermissionError("guarda requer confirmação explícita e caminhos locais")
    path=Path(banco)
    if path==Path(":memory:") or path.is_symlink() or not path.parent.is_dir():
        raise ErroPipelineAmbiental("banco SQLite persistente e diretório pai necessários")
    db=abrir_banco_medicoes(path)
    try:
        return importar_ciclo_medicoes(db,raw_dir=raw_dir,edicoes=edicoes)
    finally:
        db.close()


def exportar_backup_medicoes(db, *, raw_dir, destino):
    """Backup SQLite+RAW; comprova capacidade técnica de restauração."""
    src=_pasta(raw_dir,criar=False)
    audit=auditar_acervo_medicoes(db,raw_dir=src)
    if audit["estado"]=="ACERVO_VAZIO":
        raise ErroPipelineAmbiental("backup de acervo vazio bloqueado")
    path=Path(destino)
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ErroPipelineAmbiental("backup precisa de novo diretório válido")
    temp=Path(tempfile.mkdtemp(prefix=".nivon-hidro-",dir=path.parent))
    try:
        (temp / "raw").mkdir(mode=0o700)
        copy=abrir_banco_medicoes(temp / "medicoes.sqlite")
        try:
            db.backup(copy)
        finally:
            copy.close()
        for row in db.execute("SELECT sha256 FROM medidas_edicoes"):
            shutil.copyfile(src / (row[0]+".raw"),temp/"raw"/(row[0]+".raw"))
        check=abrir_banco_medicoes(temp/"medicoes.sqlite")
        try:
            validation=auditar_acervo_medicoes(check,raw_dir=temp/"raw")
        finally:
            check.close()
        if audit["medidas_auditadas"] != validation["medidas_auditadas"]:
            raise ErroPipelineAmbiental("backup não restitui toda a série")
        metadata={
            "schema":"1.0","tipo":"BACKUP_INMET_ANA",
            "db_sha256":sha256((temp/"medicoes.sqlite").read_bytes()).hexdigest(),
            "raw_shas":sorted(row[0] for row in db.execute("SELECT sha256 FROM medidas_edicoes")),
            "edicoes":validation["edicoes_auditadas"],
            "medidas":validation["medidas_auditadas"],
            "homologado":False,
        }
        (temp/"manifesto_backup.json").write_text(
            json.dumps(metadata,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        temp.rename(path)
        return {"estado":"BACKUP_INMET_ANA_VERIFICADO","destino":str(path),
                "edicoes":metadata["edicoes"],"medidas":metadata["medidas"],
                "homologado":False}
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def validar_backup_medicoes(*, caminho):
    root=Path(caminho)
    if root.is_symlink() or not root.is_dir():
        raise ErroPipelineAmbiental("diretório de backup ausente/inseguro")
    dbpath=root/"medicoes.sqlite"
    meta=root/"manifesto_backup.json"
    if any(p.is_symlink() or not p.is_file() for p in (dbpath,meta)):
        raise ErroPipelineAmbiental("backup incompleto ou com symlink")
    try:
        doc=json.loads(meta.read_text(encoding="utf-8"))
    except (UnicodeError,ValueError) as exc:
        raise ErroPipelineAmbiental("manifesto de backup não legível") from exc
    if (doc.get("tipo")!="BACKUP_INMET_ANA" or doc.get("schema")!="1.0" or
        doc.get("db_sha256")!=sha256(dbpath.read_bytes()).hexdigest()):
        raise ErroPipelineAmbiental("hash/contrato do backup divergente")
    uri=dbpath.resolve().as_uri()+"?mode=ro"
    db=sqlite3.connect(uri,uri=True)
    db.row_factory=sqlite3.Row
    try:
        out=auditar_acervo_medicoes(db,raw_dir=root/"raw")
        names=sorted(r[0] for r in db.execute("SELECT sha256 FROM medidas_edicoes"))
        if (names!=doc["raw_shas"] or out["edicoes_auditadas"]!=doc["edicoes"]
                or out["medidas_auditadas"]!=doc["medidas"]):
            raise ErroPipelineAmbiental("reconciliação do backup falhou")
    finally:
        db.close()
    return {"estado":"BACKUP_INMET_ANA_RESTAURAVEL",
            "edicoes":out["edicoes_auditadas"],"medidas":out["medidas_auditadas"],
            "homologado":False}


def main(argv=None):
    cli=argparse.ArgumentParser(description="NIVON INMET/ANA local (sem rede)")
    cli.add_argument("modo",choices=["validar","executar","auditar","backup","validar-backup","relatorio"])
    cli.add_argument("--manifesto")
    cli.add_argument("--banco")
    cli.add_argument("--raw-dir")
    cli.add_argument("--destino-backup")
    cli.add_argument("--dataset-id")
    cli.add_argument("--estacao-id")
    cli.add_argument("--corte-em")
    cli.add_argument("--classe",default="SINTETICO")
    cli.add_argument("--confirmar-gravacao",action="store_true")
    args=cli.parse_args(argv)
    try:
        if args.modo in ("validar","executar"):
            if not args.manifesto:
                raise ErroPipelineAmbiental("manifesto obrigatório")
            result=executar_manifesto_medicoes(
                manifesto=args.manifesto,modo=args.modo,banco=args.banco,
                raw_dir=args.raw_dir,confirmar_gravacao=args.confirmar_gravacao)
        elif args.modo=="validar-backup":
            if not args.destino_backup:
                raise ErroPipelineAmbiental("destino obrigatório")
            result=validar_backup_medicoes(caminho=args.destino_backup)
        else:
            if not args.banco or not args.raw_dir or not Path(args.banco).is_file():
                raise ErroPipelineAmbiental("banco local existente obrigatório")
            db=abrir_banco_medicoes(args.banco)
            try:
                if args.modo=="auditar":
                    result=auditar_acervo_medicoes(db,raw_dir=args.raw_dir)
                elif args.modo=="relatorio":
                    if not args.dataset_id or not args.estacao_id or not args.corte_em:
                        raise ErroPipelineAmbiental("relatório exige fonte, estação e corte")
                    result=relatorio_revisoes_medicoes(
                        db,raw_dir=args.raw_dir,dataset_id=args.dataset_id,
                        estacao_id=args.estacao_id,corte_em=args.corte_em,
                        classe=args.classe)
                else:
                    if not args.destino_backup:
                        raise ErroPipelineAmbiental("destino de backup obrigatório")
                    result=exportar_backup_medicoes(
                        db,raw_dir=args.raw_dir,destino=args.destino_backup)
            finally:
                db.close()
    except (ErroPipelineAmbiental,PermissionError,ValueError,OSError,sqlite3.Error) as exc:
        print(json.dumps({"estado":"BLOQUEADO","motivo":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
