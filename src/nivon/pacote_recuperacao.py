"""Pacote de recuperação SQLite NIVON: backup, manifesto e prova local de restore.

Não contém upload nem criptografia; proibido enviar a repositório público.
SHA-256 é integridade acidental, não autenticidade de origem/assinatura.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from .backup_sqlite import ErroBackup, criar_backup, restaurar_backup

class ErroPacote(ValueError):
    pass

_NOME = re.compile(r"[A-Za-z0-9_-]{3,60}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")

def _tabelas(conn:sqlite3.Connection)->dict[str,int]:
    """Contagens e nomes de tabelas, nenhum registro ou coluna com PII."""
    nomes=[r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    if len(nomes)>200:raise ErroPacote("muitas tabelas para prova de recuperação")
    out={}
    for nome in nomes:
        if len(nome)>100:raise ErroPacote("identificador de tabela fora do limite")
        quoted='"'+nome.replace('"','""')+'"'
        out[nome]=conn.execute("SELECT count(*) FROM "+quoted).fetchone()[0]
    return out

def _version(conn:sqlite3.Connection)->int:
    return conn.execute("PRAGMA user_version").fetchone()[0]

def criar_pacote_recuperacao(conn:sqlite3.Connection, diretorio:str|Path, *,
                            nome:str)->dict:
    """Backup em diretório privado já existente, sem overwrite."""
    if not isinstance(nome,str) or not _NOME.fullmatch(nome):
        raise ErroPacote("nome deve ser identificador ASCII seguro de 3-60 caracteres")
    path=Path(diretorio)
    if path.is_symlink() or not path.is_dir():
        raise ErroPacote("destino deve ser diretório local regular")
    backup=path/(nome+".sqlite")
    manifest=path/(nome+".manifest.json")
    if backup.exists() or backup.is_symlink() or manifest.exists() or manifest.is_symlink():
        raise ErroPacote("pacote existente: jamais sobrescrever")
    antes=_tabelas(conn)
    ver=_version(conn)
    b=criar_backup(conn,backup)
    with tempfile.TemporaryDirectory(prefix=".nivon-restore-",dir=path) as scratch:
        destino=Path(scratch)/"drill.sqlite"
        restaurar_backup(backup,destino,sha256_esperado=b["sha256"])
        with sqlite3.connect(destino) as restaurado:
            depois=_tabelas(restaurado)
            v2=_version(restaurado)
    if antes!=depois or ver!=v2:
        raise ErroPacote("restore diverge do banco original")
    doc={
        "formato":"NIVON_SQLITE_RECOVERY_V1",
        "arquivo":backup.name,
        "sha256":b["sha256"],
        "bytes":b["bytes"],
        "user_version":ver,
        "tabelas":depois,
        "restore_local_executado":True,
        "armazenamento_remoto_confirmado":False,
        "criptografia_confirmada":False,
        "status":"PACOTE_LOCAL_NAO_DURAVEL_NEM_HOMOLOGADO_PARA_NUVEM",
    }
    dados=(json.dumps(doc,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"))+"\n").encode("utf-8")
    fd=os.open(str(manifest),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as arquivo:
            arquivo.write(dados)
            arquivo.flush()
            os.fsync(arquivo.fileno())
    except BaseException:
        manifest.unlink(missing_ok=True)
        raise
    return {"manifesto":str(manifest),"backup":str(backup),
            "sha256":b["sha256"],"tabelas_verificadas":len(depois),
            "status":"RESTORE_LOCAL_VALIDADO_SEM_BACKUP_REMOTO"}

def _read_doc(path:Path)->dict:
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=30_000:
        raise ErroPacote("manifesto ausente/fora do limite ou link simbólico")
    def pairs(p):
        d={}
        for k,v in p:
            if k in d:raise ErroPacote("manifesto com chave JSON duplicada")
            d[k]=v
        return d
    try:
        d=json.loads(path.read_text(encoding="utf-8"),object_pairs_hook=pairs)
    except (UnicodeError,ValueError) as exc:
        raise ErroPacote("manifesto JSON inválido") from exc
    if not isinstance(d,dict) or d.get("formato")!="NIVON_SQLITE_RECOVERY_V1":
        raise ErroPacote("formato manifesto incompatível")
    if not isinstance(d.get("arquivo"),str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{3,60}\.sqlite",d["arquivo"]):
        raise ErroPacote("nome de backup inseguro")
    if not isinstance(d.get("sha256"),str) or not _SHA.fullmatch(d["sha256"]):
        raise ErroPacote("SHA-256 inválido")
    if type(d.get("bytes")) is not int or not 0<d["bytes"]<=1_000_000_000:
        raise ErroPacote("bytes inválidos")
    if (not isinstance(d.get("tabelas"),dict) or not d["tabelas"]
        or len(d["tabelas"])>200
        or any(not isinstance(k,str) or type(v) is not int or v<0
               for k,v in d["tabelas"].items())):
        raise ErroPacote("contagens de tabelas inválidas")
    if type(d.get("user_version")) is not int:
        raise ErroPacote("versão SQLite inválida")
    return d

def testar_restore_pacote(manifesto:str|Path, *, diretorio_temporario:str|Path)->dict:
    """Verificar SHA, integridade, restore e contagens sem sobrescrever dados."""
    caminho=Path(manifesto)
    doc=_read_doc(caminho)
    backup=caminho.parent/doc["arquivo"]
    if backup.is_symlink() or not backup.is_file() or backup.stat().st_size!=doc["bytes"]:
        raise ErroPacote("arquivo do backup mudou")
    destino_temp=Path(diretorio_temporario)
    if destino_temp.is_symlink() or not destino_temp.is_dir():
        raise ErroPacote("destino de restore deve ser diretório regular")
    with tempfile.TemporaryDirectory(prefix=".nivon-drill-",dir=destino_temp) as root:
        alvo=Path(root)/"restore.sqlite"
        restaurar_backup(backup,alvo,sha256_esperado=doc["sha256"])
        with sqlite3.connect(alvo) as conn:
            depois=_tabelas(conn)
            versao=_version(conn)
    if depois!=doc["tabelas"] or versao!=doc["user_version"]:
        raise ErroPacote("estrutura restaurada não corresponde ao manifesto")
    return {"estado":"DRILL_LOCAL_APROVADO","tabelas_verificadas":len(depois),
            "arquivo_sha256":doc["sha256"],
            "backup_remoto_confirmado":False,"segredo_ou_criptografia_validada":False}
