"""Replica estado incremental PAM em GCS sem bibliotecas externas.\n\nUsa exclusivamente o formato canonico ZIP_STORED de ivo_pam_backup da PR #78.

Fluxo: restauração/auditoria local -> objeto imutável SHA256 -> readback
completo -> troca condicional (GCS generation) do ponteiro ultimo.json.
Não cria bucket, não habilita APIs, não altera IAM, não usa chave persistente
e não executa custo se o workflow não possuir WIF/bucket pré-aprovados.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .ivo_pam_backup import restaurar_backup_pam, ErroBackupPAM

_BASE = "https://storage.googleapis.com"
_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9._-]*[a-z0-9]\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_PREFIX = "nivon/ivo/pam/v1"
_POINTER = _PREFIX + "/controle/ultimo.json"
_MAX_BYTES = 128 * 1024 * 1024


class ErroGCSState(ValueError):
    pass


class _HTTPStatus(ErroGCSState):
    def __init__(self,status):
        super().__init__(f"Google Cloud Storage respondeu HTTP {status}")
        self.status=status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ErroGCSState("redirect proibido no armazenamento")


def _http(method,url,headers,body=None):
    req=urllib.request.Request(url,data=body,method=method,headers=headers)
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}),_NoRedirect,
        urllib.request.HTTPSHandler())
    try:
        with opener.open(req,timeout=20) as reply:
            if reply.status not in (200,201):
                raise _HTTPStatus(reply.status)
            raw=reply.read(_MAX_BYTES+1)
            if len(raw)>_MAX_BYTES:
                raise ErroGCSState("resposta maior que 128 MiB")
            return raw
    except urllib.error.HTTPError as exc:
        raise _HTTPStatus(exc.code) from exc
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ErroGCSState("falha de transporte do Google Cloud Storage") from exc


class ClienteGCS:
    def __init__(self,*,bucket,token,transporte=None):
        if (not isinstance(bucket,str) or not _BUCKET.fullmatch(bucket)
                or ".." in bucket or bucket.count(".")>=4):
            raise ErroGCSState("nome de bucket inválido")
        if not isinstance(token,str) or not token.strip() or len(token)>12000:
            raise ErroGCSState("token temporário GCS obrigatório")
        if transporte is not None and not callable(transporte):
            raise ErroGCSState("transporte inválido")
        self.bucket=bucket
        self._token=token
        self._transport=transporte or _http

    def _request(self,method,path,*,params=None,body=None):
        query=urllib.parse.urlencode(params or {})
        url=_BASE+path+("?" + query if query else "")
        headers={"Authorization":"Bearer "+self._token,
                 "Accept":"application/json,application/octet-stream",
                 "Accept-Encoding":"identity"}
        if body is not None:
            headers["Content-Type"]="application/octet-stream"
        raw=self._transport(method,url,headers,body)
        if not isinstance(raw,bytes) or len(raw)>_MAX_BYTES:
            raise ErroGCSState("resposta GCS fora de contrato")
        return raw

    def _object_path(self,name,upload=False):
        if not isinstance(name,str) or not (
              name==_POINTER or re.fullmatch(
              re.escape(_PREFIX)+r"/backups/sha256-[a-f0-9]{64}\.zip",name)):
            raise ErroGCSState("nome de objeto fora do namespace PAM")
        root="/upload/storage/v1/b/" if upload else "/storage/v1/b/"
        return root+self.bucket+("/o" if upload else "/o/"+urllib.parse.quote(name,safe=""))

    def meta(self,name):
        try:
            raw=self._request("GET",self._object_path(name))
        except _HTTPStatus as exc:
            if exc.status==404:
                return None
            raise
        try:
            obj=json.loads(raw)
            gen=obj["generation"]
        except (ValueError,KeyError,TypeError) as exc:
            raise ErroGCSState("metadados de objeto inválidos") from exc
        if (obj.get("name")!=name or not isinstance(gen,str)
                or not gen.isdecimal() or int(gen)<=0):
            raise ErroGCSState("objeto/geração GCS não coincidem")
        return obj

    def download(self,name,*,generation=None):
        if generation is not None and (type(generation) is not int or generation<=0):
            raise ErroGCSState("geração inválida")
        params={"alt":"media"}
        if generation is not None:
            params["generation"]=str(generation)
        return self._request("GET",self._object_path(name),params=params)

    def upload(self,name,data,*,geracao_esperada):
        if not isinstance(data,bytes) or not 0<len(data)<=_MAX_BYTES:
            raise ErroGCSState("payload inválido ou grande demais")
        if type(geracao_esperada) is not int or geracao_esperada<0:
            raise ErroGCSState("pré-condição GCS obrigatória")
        raw=self._request("POST",self._object_path(name,upload=True),params={
            "uploadType":"media","name":name,
            "ifGenerationMatch":str(geracao_esperada)},body=data)
        try:
            obj=json.loads(raw)
            gen=obj["generation"]
        except (ValueError,KeyError,TypeError) as exc:
            raise ErroGCSState("upload GCS sem metadados de confirmação") from exc
        if obj.get("name")!=name or not str(gen).isdecimal():
            raise ErroGCSState("upload confirmado para objeto incorreto")
        return int(gen)

    def ponteiro(self):
        meta=self.meta(_POINTER)
        if meta is None:
            return None,0
        gen=int(meta["generation"])
        raw=self.download(_POINTER,generation=gen)
        try:
            p=json.loads(raw)
        except (UnicodeError,ValueError) as exc:
            raise ErroGCSState("ponteiro GCS não é JSON") from exc
        if (not isinstance(p,dict) or p.get("schema")!="nivon_ivo_pam_gcs_v1"
              or not isinstance(p.get("sha256"),str)
              or not _SHA.fullmatch(p["sha256"])
              or p.get("objeto")!=_PREFIX+"/backups/sha256-"+p["sha256"]+".zip"
              or type(p.get("capturas")) is not int or p["capturas"]<1
              or type(p.get("vintages")) is not int or p["vintages"]<1
              or p.get("treinamento_habilitado") is not False):
            raise ErroGCSState("ponteiro publicado não é confiável")
        return p,gen


def _arquivo_confiavel(caminho):
    p=Path(caminho)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=_MAX_BYTES:
        raise ErroGCSState("backup de entrada ausente, symlink ou excessivo")
    return p.read_bytes()


def _auditar_zip_bytes(data):
    with tempfile.TemporaryDirectory(prefix="ivo-pam-gcs-") as temp:
        root=Path(temp)
        path=root/"estado_pam.zip"
        path.write_bytes(data)
        try:
            r=restaurar_backup_pam(arquivo_zip=path,destino=root/"restaurado")
        except (ErroBackupPAM,sqlite3.Error,OSError) as exc:
            raise ErroGCSState("ZIP não passou restauração/auditoria PAM") from exc
    return r


def publicar_backup_gcs(*,cliente:ClienteGCS,arquivo,permitir_bootstrap=False):
    """Publica backup imutável e só então ponteiro via compare-and-swap.

    Exige aumento real de capturas. Não troca o ponteiro se um outro job
    publicá-lo entre leitura inicial e atualização final.
    """
    if type(permitir_bootstrap) is not bool:
        raise ErroGCSState("bootstrap deve ser explícito")
    data=_arquivo_confiavel(arquivo)
    audit=_auditar_zip_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    name=_PREFIX+"/backups/sha256-"+sha+".zip"
    anterior,gen=cliente.ponteiro()
    if anterior is None and not permitir_bootstrap:
        raise ErroGCSState("bucket sem estado; bootstrap explicitamente obrigatório")
    if anterior is not None:
        # Antes de avançar, o backup remoto anterior deve ser realmente íntegro.
        orig=cliente.download(anterior["objeto"])
        if hashlib.sha256(orig).hexdigest()!=anterior["sha256"]:
            raise ErroGCSState("cadeia anterior no GCS corrompida")
        prev=_auditar_zip_bytes(orig)
        if (prev["capturas"]!=anterior["capturas"] or
                prev["vintages"]!=anterior["vintages"]):
            raise ErroGCSState("ponteiro anterior incoerente com SQLite")
        if audit["capturas"]<=anterior["capturas"]:
            raise ErroGCSState("backup não avança número de capturas no histórico")
        if audit["vintages"]<anterior["vintages"]:
            raise ErroGCSState("novo backup perdeu vintages")
        # O novo backup precisa conter todas as capturas anteriores.
        # Comparação de PKs protege contra reconstrução artificial com
        # o mesmo número de linhas.
        with tempfile.TemporaryDirectory(prefix="ivo-pam-compare-") as tmp:
            folder=Path(tmp)
            for titulo,raw in (("anterior",orig),("novo",data)):
                arq=folder/(titulo+".zip")
                arq.write_bytes(raw)
                restaurar_backup_pam(arquivo_zip=arq,destino=folder/titulo)
            a=sqlite3.connect(folder/"anterior"/"operacional.sqlite")
            b=sqlite3.connect(folder/"novo"/"operacional.sqlite")
            try:
                for tabela in ("pam_capturas","pam_vintages"):
                    # Comparar linhas completas, não somente PKs: é
                    # proibido reescrever valores, classificação, origem,
                    # captura, recibo ou status de um registro histórico.
                    consulta="SELECT * FROM "+tabela
                    antigos={tuple(x) for x in a.execute(consulta)}
                    atuais={tuple(x) for x in b.execute(consulta)}
                    if not antigos.issubset(atuais):
                        raise ErroGCSState(
                            "backup novo perdeu ou alterou registros históricos: "+tabela)
            finally:
                a.close()
                b.close()
    current=cliente.meta(name)
    if current is not None:
        if hashlib.sha256(cliente.download(name)).hexdigest()!=sha:
            raise ErroGCSState("objeto existente com mesmo nome/hash e bytes diferentes")
    else:
        cliente.upload(name,data,geracao_esperada=0)
    readback=cliente.download(name)
    if hashlib.sha256(readback).hexdigest()!=sha:
        raise ErroGCSState("readback GCS divergente; ponteiro não atualizado")
    _auditar_zip_bytes(readback)
    pointer={
        "schema":"nivon_ivo_pam_gcs_v1",
        "objeto":name,"sha256":sha,
        "capturas":audit["capturas"],"vintages":audit["vintages"],
        "gravado_em":datetime.now(timezone.utc).isoformat(),
        "treinamento_habilitado":False,
    }
    raw=(json.dumps(pointer,sort_keys=True,separators=(",",":"))+"\n").encode()
    try:
        pointer_gen=cliente.upload(_POINTER,raw,geracao_esperada=gen)
    except _HTTPStatus as exc:
        if exc.status==412:
            raise ErroGCSState("outro processo alterou ponteiro; não sobrescrever") from exc
        raise
    got,confirmed_gen=cliente.ponteiro()
    if got!=pointer or confirmed_gen!=pointer_gen:
        raise ErroGCSState("ponteiro GCS não corresponde ao backup publicado")
    return {"estado":"BACKUP_PAM_PUBLICADO_COM_READBACK",
            "bucket":cliente.bucket,"objeto":name,"sha256":sha,
            "capturas":audit["capturas"],"vintages":audit["vintages"],
            "pointer_generation":pointer_gen,
            "cloud_verified":True,"treinamento_habilitado":False}


def baixar_backup_gcs(*,cliente:ClienteGCS,saida):
    destino=Path(saida)
    if destino.exists() or destino.is_symlink() or not destino.parent.is_dir():
        raise ErroGCSState("destino de recuperação precisa ser arquivo novo")
    pointer,_=cliente.ponteiro()
    if pointer is None:
        raise ErroGCSState("nenhum backup PAM no bucket, não reiniciar automaticamente")
    raw=cliente.download(pointer["objeto"])
    if hashlib.sha256(raw).hexdigest()!=pointer["sha256"]:
        raise ErroGCSState("backup baixado difere do SHA do ponteiro")
    audit=_auditar_zip_bytes(raw)
    if (audit["capturas"]!=pointer["capturas"]
            or audit["vintages"]!=pointer["vintages"]):
        raise ErroGCSState("backup não corresponde às contagens publicadas")
    # O modo exclusivo impede perda de arquivo anterior em qualquer falha.
    with destino.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"estado":"BACKUP_PAM_RECUPERADO_COM_READBACK",
            "arquivo":str(destino),"sha256":pointer["sha256"],
            "capturas":audit["capturas"],"vintages":audit["vintages"],
            "treinamento_habilitado":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON PAM: réplica verificada no Google Cloud Storage")
    p.add_argument("operacao",choices=("upload","recuperar","estado"))
    p.add_argument("--bucket",required=True)
    p.add_argument("--arquivo",type=Path)
    p.add_argument("--bootstrap",action="store_true")
    args=p.parse_args(argv)
    token=os.environ.get("NIVON_GCS_ACCESS_TOKEN")
    try:
        cliente=ClienteGCS(bucket=args.bucket,token=token)
        if args.operacao=="estado":
            if args.bootstrap or args.arquivo is not None:
                raise ErroGCSState("estado não recebe arquivo/bootstrap")
            p,_=cliente.ponteiro()
            if p is None:
                print(json.dumps({"estado":"SEM_BACKUP_GCS"},ensure_ascii=False))
                return 3
            print(json.dumps({"estado":"BACKUP_GCS_DISPONIVEL",
                              "capturas":p["capturas"],"vintages":p["vintages"]},
                              ensure_ascii=False))
            return 0
        if args.arquivo is None:
            raise ErroGCSState("arquivo obrigatório")
        if args.operacao=="upload":
            r=publicar_backup_gcs(cliente=cliente,arquivo=args.arquivo,
                                  permitir_bootstrap=args.bootstrap)
        else:
            if args.bootstrap:
                raise ErroGCSState("bootstrap não pertence à recuperação")
            r=baixar_backup_gcs(cliente=cliente,saida=args.arquivo)
        print(json.dumps(r,ensure_ascii=False,sort_keys=True))
        return 0
    except (OSError,ValueError,sqlite3.Error) as exc:
        print(json.dumps({"estado":"BLOQUEADO",
                          "erro":str(exc)[:240]},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
