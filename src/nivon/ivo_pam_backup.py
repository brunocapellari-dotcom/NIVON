"""Backup portátil e restauração fail-closed da operação PAM do NIVON.

Arquivo fechado contém snapshot SQLite consistente + bytes originais de
cada objeto + recibos. Manifesto com SHA por entrada, limite de expansão,
sem links/caminhos externos, auditoria antes de publicar a restauração.
Suporta arquivo legado do piloto SOMENTE com opt-in explícito e auditoria.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .ivo_pam_operacao import abrir_operacao_pam
from .ivo_pam_qualidade import auditar_operacao_pam


class ErroBackupPAM(ValueError):
    pass


_H = r"[a-f0-9]{64}"
_ENTRADA = re.compile(
    r"(?:pam.sqlite|cofre/objetos_sha256/"+_H+r"\.bin|"
    r"cofre/recibos/"+_H+r"\.json)")
_LEGADO = {"resultado_coleta.json", "auditoria.json"}
_LIMITE_BYTES = 128 * 1024 * 1024
_LIMITE_ARQUIVOS = 6000


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _validar_zip_member(member):
    nome=member.filename
    if (not isinstance(nome,str) or len(nome)>170
            or "\\" in nome or nome.startswith("/")
            or ".." in Path(nome).parts
            or member.is_dir()):
        raise ErroBackupPAM("entrada de ZIP inválida")
    # Entradas geradas em sistemas Unix não podem ser symlinks.
    modo=member.external_attr >> 16
    if modo & 0o170000 == 0o120000:
        raise ErroBackupPAM("links simbólicos proibidos em ZIP")
    if not (_ENTRADA.fullmatch(nome) or nome in _LEGADO or nome=="manifesto.json"):
        raise ErroBackupPAM("entrada não prevista no arquivo")
    if not 0 < member.file_size <= _LIMITE_BYTES:
        raise ErroBackupPAM("tamanho individual inválido")


def _audit(db,root):
    try:
        resultado=auditar_operacao_pam(db=db,raiz=root,max_vintages=3000)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError) as exc:
        raise ErroBackupPAM("falha na auditoria integrada PAM") from exc
    if not resultado["integridade_local_aprovada"]:
        raise ErroBackupPAM("SQLite/JSON/recibos inconsistentes")
    return resultado


def criar_backup_pam(*,db:sqlite3.Connection,raiz,saida)->dict:
    """Produz ZIP somente se banco e acervo estiverem íntegros."""
    if not isinstance(db,sqlite3.Connection):
        raise ErroBackupPAM("conexão SQLite operacional obrigatória")
    origem=Path(raiz)
    destino=Path(saida)
    if not origem.is_dir() or origem.is_symlink():
        raise ErroBackupPAM("acervo inválido")
    if destino.exists() or destino.is_symlink():
        raise ErroBackupPAM("backup já existe e não será sobrescrito")
    _audit(db,origem)
    destino.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pam-snapshot-",dir=destino.parent) as temp:
        snap=Path(temp)/"pam.sqlite"
        target=sqlite3.connect(snap)
        try:
            db.backup(target)
        finally:
            target.close()
        entradas={"pam.sqlite":snap.read_bytes()}
        for nome in ("objetos_sha256","recibos"):
            pasta=origem/nome
            if pasta.is_symlink() or not pasta.is_dir():
                raise ErroBackupPAM("pasta de acervo ausente ou symlink")
            for item in sorted(pasta.iterdir()):
                rel="cofre/"+nome+"/"+item.name
                if item.is_symlink() or not item.is_file() or not _ENTRADA.fullmatch(rel):
                    raise ErroBackupPAM("objeto não regular ou com identidade inesperada")
                if item.stat().st_size > _LIMITE_BYTES:
                    raise ErroBackupPAM("objeto grande demais")
                entradas[rel]=item.read_bytes()
        total=sum(map(len,entradas.values()))
        if total>_LIMITE_BYTES or len(entradas)>_LIMITE_ARQUIVOS:
            raise ErroBackupPAM("snapshot ultrapassa limites do projeto")
        manifesto={
            "schema":"nivon_pam_backup_v1",
            "algoritmo":"sha256",
            "arquivos":{p:{"sha256":_sha(raw),"bytes":len(raw)}
                        for p,raw in sorted(entradas.items())},
            "conteudo_total_bytes":total,
            "publicacao_ibge_certificada":False,
            "treinamento_liberado":False,
        }
        destino_tmp=Path(temp)/"backup.zip"
        with zipfile.ZipFile(destino_tmp,"w",compression=zipfile.ZIP_DEFLATED) as z:
            for nome,raw in sorted(entradas.items()):
                z.writestr(nome,raw)
            z.writestr("manifesto.json",json.dumps(manifesto,sort_keys=True,
                         ensure_ascii=False,separators=(",",":")).encode())
        # Releitura e validação independente de metadados + bytes comprimidos.
        _ler_backup(destino_tmp,permitir_legado=False)
        try:
            with destino_tmp.open("rb") as stream:
                os.fsync(stream.fileno())
            os.link(destino_tmp,destino)
        except OSError as exc:
            raise ErroBackupPAM("não foi possível publicar backup sem sobrescrever") from exc
    return {"estado":"BACKUP_PAM_VERIFICADO",
            "sha256_arquivo":_sha(destino.read_bytes()),
            "arquivos":len(entradas),"bytes_originais":total,
            "vintages":db.execute("SELECT COUNT(*) FROM pam_vintages").fetchone()[0],
            "capturas":db.execute("SELECT COUNT(*) FROM pam_capturas").fetchone()[0],
            "destino":str(destino),"homologado_para_treino":False}


def _ler_backup(caminho,*,permitir_legado):
    caminho=Path(caminho)
    if not caminho.is_file() or caminho.is_symlink() or caminho.stat().st_size>_LIMITE_BYTES:
        raise ErroBackupPAM("backup ausente/inválido/excessivo")
    try:
        with zipfile.ZipFile(caminho) as z:
            infos=z.infolist()
            if not infos or len(infos)>_LIMITE_ARQUIVOS or sum(x.file_size for x in infos)>_LIMITE_BYTES:
                raise ErroBackupPAM("número de entradas ou expansão excessiva")
            nomes=[i.filename for i in infos]
            if len(nomes)!=len(set(nomes)) or "pam.sqlite" not in nomes:
                raise ErroBackupPAM("faltam base SQLite ou nomes são repetidos")
            for i in infos:
                _validar_zip_member(i)
                if i.compress_size==0 or (i.file_size/i.compress_size)>1000:
                    raise ErroBackupPAM("taxa de compressão excessiva")
            bruto={i.filename:z.read(i) for i in infos}
    except (zipfile.BadZipFile,EOFError,OSError,RuntimeError) as exc:
        raise ErroBackupPAM("arquivo ZIP corrompido") from exc
    if "manifesto.json" not in bruto:
        if not permitir_legado:
            raise ErroBackupPAM("ZIP piloto legado sem manifesto; importação requer opção explícita")
        if any(n not in _LEGADO and not _ENTRADA.fullmatch(n) for n in bruto):
            raise ErroBackupPAM("ZIP legado contém caminhos imprevistos")
        return {k:v for k,v in bruto.items() if k not in _LEGADO},True
    try:
        m=json.loads(bruto.pop("manifesto.json"))
    except (ValueError,UnicodeError) as exc:
        raise ErroBackupPAM("manifesto não é JSON") from exc
    if (not isinstance(m,dict) or m.get("schema")!="nivon_pam_backup_v1"
            or m.get("algoritmo")!="sha256" or m.get("treinamento_liberado") is not False
            or m.get("publicacao_ibge_certificada") is not False
            or not isinstance(m.get("arquivos"),dict)
            or set(m["arquivos"])!=set(bruto)
            or any(k in _LEGADO for k in bruto)):
        raise ErroBackupPAM("manifesto incompleto ou com estados indevidos")
    for nome,raw in bruto.items():
        info=m["arquivos"][nome]
        if (not isinstance(info,dict) or info.get("sha256")!=_sha(raw)
                or info.get("bytes")!=len(raw)):
            raise ErroBackupPAM("arquivo não corresponde ao manifesto")
    if m.get("conteudo_total_bytes")!=sum(map(len,bruto.values())):
        raise ErroBackupPAM("tamanho total incompatível com manifesto")
    return bruto,False


def restaurar_backup_pam(*,arquivo,destino,permitir_legado=False)->dict:
    """Extrai em diretório NOVO e publica somente após auditoria integrada.

    Nunca mescla em banco ou diretório existente. ZIP legado do Actions
    anterior pode ser usado para bootstrap, mas não tem manifesto global.
    """
    if type(permitir_legado) is not bool:
        raise ErroBackupPAM("opção de legado inválida")
    alvo=Path(destino)
    if alvo.exists() or alvo.is_symlink():
        raise ErroBackupPAM("restauração não sobrescreve destino existente")
    if not alvo.parent.is_dir() or alvo.parent.is_symlink():
        raise ErroBackupPAM("diretório pai não confiável")
    dados,legado=_ler_backup(arquivo,permitir_legado=permitir_legado)
    with tempfile.TemporaryDirectory(prefix=".pam-restore-",dir=alvo.parent) as folder:
        temp=Path(folder)
        for nome,raw in dados.items():
            p=temp/nome
            p.parent.mkdir(parents=True,exist_ok=True)
            if p.is_symlink():
                raise ErroBackupPAM("symlink no destino de extração")
            with p.open("xb") as out:
                out.write(raw)
        root=temp/"cofre"
        if not root.is_dir():
            raise ErroBackupPAM("backup sem diretório de objetos e recibos")
        try:
            db=abrir_operacao_pam(temp/"pam.sqlite")
            try:
                aud=_audit(db,root)
            finally:
                db.close()
        except (sqlite3.Error,ValueError,OSError) as exc:
            raise ErroBackupPAM("backup restaurado falhou na auditoria") from exc
        os.rename(temp,alvo)
    return {"estado":"PAM_RESTAURADA_E_AUDITADA",
            "vintages":aud["vintages_verificadas"],
            "capturas":aud["capturas_registradas"],
            "legado_sem_manifesto":legado,
            "destino":str(alvo),
            "fonte_oficial_historica_homologada":False}
