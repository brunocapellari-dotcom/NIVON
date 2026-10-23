"""RAW ZARC content-addressed, imutável, vinculado ao ledger NIVON.

Recebe somente arquivo local já passado pelo staging ZARC e registrado no
ledger existente. Não faz rede, não cria banco externo, não agenda coletas.
Direitos para REAL_AUTORIZADO são exigidos pelo staging/ledger canônico.
Diretório precisa ser absoluto, privado (0700), sem symlink; arquivo final
é 0600, atômico via hard link sem sobrescrita.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import tempfile
from pathlib import Path

from .zarc_stream_mt import MAX_DOWNLOAD

_SHA=re.compile(r"[a-f0-9]{64}\Z")

class ErroRawZarc(ValueError):
    pass


def _root(raiz):
    p=Path(raiz)
    if (not p.is_absolute() or p.is_symlink() or not p.is_dir()
            or stat.S_IMODE(p.stat().st_mode)&0o077):
        raise ErroRawZarc("RAIZ_DEVE_SER_DIRETORIO_PRIVADO_0700_ABSOLUTO")
    return p


def _hash_path(path):
    h=hashlib.sha256()
    n=0
    with path.open("rb") as arq:
        for chunk in iter(lambda:arq.read(262144),b""):
            n+=len(chunk)
            if n>MAX_DOWNLOAD:
                raise ErroRawZarc("ARQUIVO_ULTRAPASSA_TETO_ZARC")
            h.update(chunk)
    return h.hexdigest(),n


def _arquivo_canonico(root,sha):
    if not isinstance(sha,str) or not _SHA.fullmatch(sha):
        raise ErroRawZarc("SHA_INVALIDO")
    return root/(sha+".csv")


def verificar_raw_zarc(*,db:sqlite3.Connection,raiz,sha256):
    """Confere hash, permissões, tamanho e ledger, sem regravar."""
    root=_root(raiz)
    p=_arquivo_canonico(root,sha256)
    if p.is_symlink() or not p.is_file() or stat.S_IMODE(p.stat().st_mode)&0o077:
        raise ErroRawZarc("RAW_AUSENTE_OU_NAO_PRIVADO")
    if p.stat().st_nlink!=1:
        raise ErroRawZarc("RAW_COM_LINK_ADICIONAL_NAO_AUTORIZADO")
    hash_atual,tamanho=_hash_path(p)
    if hash_atual!=sha256:
        raise ErroRawZarc("RAW_HASH_DIVERGENTE")
    row=db.execute("""SELECT s.bytes,s.tipo,e.linhas_mt,e.linhas_total
      FROM nivon_snapshots s JOIN zarc_edicoes e
        ON s.dataset_id=e.dataset_id AND s.sha256=e.sha256
      WHERE s.dataset_id='ZARC_JANELAS' AND s.sha256=?""",(sha256,)).fetchone()
    if row is None or int(row[0])!=tamanho:
        raise ErroRawZarc("RAW_SEM_LEDGER_COMPATIVEL")
    return {"dataset_id":"ZARC_JANELAS","sha256":sha256,
            "bytes":tamanho,"linhas_mt_ledger":int(row[2]),
            "linhas_total_ledger":int(row[3]),
            "ledger_tipo":row[1],"integridade":"SHA256_CONFERE_LEDGER",
            "nuvem_duravel":False,"publicavel":False}


def guardar_raw_zarc(*,db:sqlite3.Connection,arquivo,raiz):
    """Copia RAW binário local para vault após staging bem-sucedido.

    Qualquer exceção remove apenas arquivo temporário, nunca RAW imutável.
    Falha entre staging e armazenamento RAW deve constar como pendência de
    reconciliação e nunca como ingestão totalmente recuperável.
    """
    root=_root(raiz)
    if not isinstance(db,sqlite3.Connection):
        raise ErroRawZarc("CONEXAO_SQLITE_OBRIGATORIA")
    if not hasattr(arquivo,"read") or not hasattr(arquivo,"seek"):
        raise ErroRawZarc("ENTRADA_DEVE_SER_ARQUIVO_BINARIO_REPOSICIONAVEL")
    fd,temp_nome=tempfile.mkstemp(prefix=".zarc-raw-",suffix=".tmp",dir=str(root))
    os.fchmod(fd,0o600)
    temp=Path(temp_nome)
    try:
        h=hashlib.sha256()
        total=0
        arquivo.seek(0)
        with os.fdopen(fd,"wb") as saida:
            while True:
                chunk=arquivo.read(262144)
                if not isinstance(chunk,bytes):
                    raise ErroRawZarc("ARQUIVO_RAW_NAO_BINARIO")
                if not chunk:
                    break
                total+=len(chunk)
                if total>MAX_DOWNLOAD:
                    raise ErroRawZarc("LIMITE_RAW_ZARC_EXCEDIDO")
                saida.write(chunk)
                h.update(chunk)
            if total==0:
                raise ErroRawZarc("RAW_VAZIO")
            saida.flush()
            os.fsync(saida.fileno())
        sha=h.hexdigest()
        registro=db.execute("""SELECT s.bytes,s.tipo FROM nivon_snapshots s
            JOIN zarc_edicoes e ON e.dataset_id=s.dataset_id
              AND e.sha256=s.sha256
            WHERE s.dataset_id='ZARC_JANELAS' AND s.sha256=?""",(sha,)).fetchone()
        if registro is None or int(registro[0])!=total:
            raise ErroRawZarc("RAW_NAO_CORRESPONDE_A_EDICAO_REGISTRADA")
        final=_arquivo_canonico(root,sha)
        novo=True
        try:
            os.link(temp,final,follow_symlinks=False)
        except FileExistsError:
            novo=False
        # Ao criar via link atômico, existe uma segunda ligação temporária:
        # removê-la ANTES de impor st_nlink == 1 à cópia canônica.
        temp.unlink(missing_ok=True)
        if not novo:
            # Detecta corrupção e nunca sobrescreve RAW existente.
            verificar_raw_zarc(db=db,raiz=root,sha256=sha)
        fd_dir=os.open(root,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:
            os.fsync(fd_dir)
        finally:
            os.close(fd_dir)
        verificacao=verificar_raw_zarc(db=db,raiz=root,sha256=sha)
        return {**verificacao,"novo_arquivo":novo,
                "destino":"VAULT_RAW_LOCAL_PRIVADO",
                "backup_remoto_comprovado":False}
    finally:
        temp.unlink(missing_ok=True)
