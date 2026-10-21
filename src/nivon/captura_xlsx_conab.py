"""Captura supervisionada de UM XLSX CONAB, com prova de transporte e RAW.

DESLIGADO POR PADRÃO: requer autorização expressa de coleta e direitos.
Não segue redirects, não acessa URLs arbitrárias, não aceita proxy do
ambiente, não grava SQLite, não ativa backfill nem libera publicação.
As regras de URL/competência são compartilhadas com a auditoria V1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .auditoria_publicacao_conab import (
    ErroProvenienciaConab, auditar_conab_local, validar_publicacao_conab,
)

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_BYTES = 20_000_000
MAX_TIMEOUT = 20
RAW_FILE = "conab_progresso_raw.xlsx"
EVIDENCE_FILE = "conab_captura_evidencia.json"
SCHEMA = "NIVON_CONAB_CAPTURA_SUPERVISIONADA_V1"


class ErroCapturaConab(ValueError):
    pass


class _BloquearRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _opener_sem_proxy_ou_redirect():
    # TLS valida por padrão cadeia de certificados e hostname, sem desabilitar.
    # Não usar proxies configurados por variáveis de ambiente e não enviar cookies.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _BloquearRedirect(),
        urllib.request.HTTPSHandler(),
    ).open


def _agora(clock=None) -> datetime:
    ts = clock() if clock is not None else datetime.now(timezone.utc)
    if not isinstance(ts, datetime) or ts.tzinfo is None or ts.utcoffset() is None:
        raise ErroCapturaConab("timestamp de captura precisa ter fuso")
    return ts.astimezone(timezone.utc)


def _download_uma_vez(url: str, *, transport=None, clock=None) -> tuple[bytes, dict]:
    opener=transport or _opener_sem_proxy_ou_redirect()
    request=urllib.request.Request(
        url, headers={
            "Accept":MIME,
            "User-Agent":"NIVON/0.1 (pesquisa nao comercial; coleta autorizada supervisionada)",
        }, method="GET",
    )
    started=_agora(clock)
    try:
        with opener(request,timeout=MAX_TIMEOUT) as response:
            status=getattr(response,"status",None)
            final_url=response.geturl()
            # Não revalidar destino apenas pelo domínio: exigir URL EXATA.
            if status!=200 or final_url!=url:
                raise ErroCapturaConab("HTTP não-200 ou redirecionamento não autorizado")
            content_type=(response.headers.get("Content-Type") or "").split(";",1)[0].strip().lower()
            if content_type!=MIME:
                raise ErroCapturaConab("resposta não é MIME XLSX; possível HTML/WAF")
            raw_length=response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    expected=int(raw_length)
                except (TypeError,ValueError) as exc:
                    raise ErroCapturaConab("Content-Length inválido") from exc
                if not 0<expected<=MAX_BYTES:
                    raise ErroCapturaConab("Content-Length acima do limite ou vazio")
            else:
                expected=None
            chunks=[]
            size=0
            while True:
                chunk=response.read(65536)
                if not isinstance(chunk,bytes):
                    raise ErroCapturaConab("resposta HTTP não contém bytes")
                if not chunk:
                    break
                size+=len(chunk)
                if size>MAX_BYTES:
                    raise ErroCapturaConab("corpo HTTP acima de 20 MB")
                chunks.append(chunk)
            if not size or (expected is not None and expected!=size):
                raise ErroCapturaConab("download incompleto/Content-Length incompatível")
            headers={
                "content_type":content_type,
                "content_length_declarado":expected,
                "etag":response.headers.get("ETag"),
                "last_modified":response.headers.get("Last-Modified"),
            }
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        # Falha fechada, sem retry que contorne bloqueios de WAF/proxy.
        raise ErroCapturaConab("download HTTPS falhou; não houve arquivo capturado") from exc
    finished=_agora(clock)
    if finished<started:
        raise ErroCapturaConab("relógio regrediu durante a captura")
    return b"".join(chunks),{
        "iniciado_utc":started.isoformat(),
        "finalizado_utc":finished.isoformat(),
        "url_solicitada":url,
        "url_resposta":url,
        "http_status":200,
        "tls_padrao_da_biblioteca":True,
        "sem_redirecionamento":True,
        "sem_proxy_de_ambiente":True,
        **headers,
    }


def _destino_privado(destino: str | Path) -> Path:
    path=Path(destino)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ErroCapturaConab("destino deve ser diretório absoluto existente e não symlink")
    if os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077:
        raise ErroCapturaConab("destino precisa estar privado: chmod 700")
    if any(path.iterdir()):
        raise ErroCapturaConab("destino não vazio: gravação exclusiva bloqueada")
    return path


def _salvar_exclusivo(path: Path, data: bytes):
    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def capturar_xlsx_conab(reg: dict, *, destino: str | Path,
                       autoriza_requisicao: bool = False,
                       direitos_coleta_conferidos: bool = False,
                       transport=None, clock=None) -> dict:
    """Apenas uma solicitação HTTPS; escreve 2 arquivos locais privados.

    Direitos e autorização são declarados pelo operador, NÃO verificados
    pelo módulo. O resultado NÃO é autorização para distribuir ou migrar.
    """
    if autoriza_requisicao is not True or direitos_coleta_conferidos is not True:
        raise PermissionError("captura desabilitada: verificar direitos e autorizar consulta")
    meta=validar_publicacao_conab(reg)
    out=_destino_privado(destino)
    raw,network=_download_uma_vez(meta["url_anexo"],transport=transport,clock=clock)
    audit=auditar_conab_local(reg,bytes_anexo=raw,
                             coletado_utc=network["finalizado_utc"])
    expected=reg["conteudo_sha256_verificado"]
    sha=hashlib.sha256(raw).hexdigest()
    if expected is not None and sha!=expected:
        raise ErroCapturaConab("sha RAW não coincide com SHA previamente homologado")
    manifest={
        "schema":SCHEMA,
        "dataset_id":"CONAB_PROGRESSO_SEMANAL",
        "id_edicao":meta["id_edicao"],
        "url_pagina":meta["url_pagina"],
        "url_anexo":meta["url_anexo"],
        "publicacao_data":meta["pagina_publicada_data"],
        "competencia":meta["semana_planilha"],
        "transport_evidencia":network,
        "arquivo_local":RAW_FILE,
        "bytes_sha256":sha,
        "bytes_tamanho":len(raw),
        "parser_id":audit["parser_id"],
        "parser_codigo_sha256":audit["parser_codigo_sha256"],
        "quantidade_observacoes":audit["quantidade_observacoes"],
        "direitos_coleta_declarados_pelo_operador":True,
        "direitos_auditoria_independente_concluida":False,
        "origem_publicada_arquivada_independentemente":False,
        "direitos_redistribuicao_verificados":False,
        "migracao_permitida":False,
        "publicacao_permitida":False,
    }
    created=[]
    try:
        rawpath=out/RAW_FILE
        _salvar_exclusivo(rawpath,raw)
        created.append(rawpath)
        evidence=out/EVIDENCE_FILE
        _salvar_exclusivo(evidence,(json.dumps(
            manifest,ensure_ascii=False,indent=2,sort_keys=True,
            allow_nan=False)+"\n").encode("utf-8"))
        created.append(evidence)
    except (OSError,ValueError):
        for p in reversed(created):
            p.unlink(missing_ok=True)
        raise
    return {
        "estado":"CAPTURA_HTTPS_PONTUAL_LOCAL_COM_EVIDENCIA_NAO_HOMOLOGADA",
        "id_edicao":meta["id_edicao"],
        "raw_sha256":sha,
        "raw_bytes":len(raw),
        "quantidade_observacoes":audit["quantidade_observacoes"],
        "relatorio":EVIDENCE_FILE,
        "migracao_permitida":False,
        "publicacao_permitida":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Captura CONAB pontual; desligada por padrão")
    p.add_argument("--manifesto",required=True)
    p.add_argument("--id-edicao",required=True)
    p.add_argument("--destino",required=True)
    p.add_argument("--autorizar-requisicao",action="store_true")
    p.add_argument("--direitos-coleta-conferidos",action="store_true")
    args=p.parse_args(argv)
    try:
        file=Path(args.manifesto)
        if not file.is_file() or file.is_symlink() or not 0<file.stat().st_size<=100_000:
            raise ErroCapturaConab("manifesto ausente, symlink ou grande")
        doc=json.loads(file.read_text(encoding="utf-8"))
        if (not isinstance(doc,dict) or doc.get("schema")!="NIVON_CONAB_PAGINA_ANEXO_V1"
                or not isinstance(doc.get("edicoes"),list)):
            raise ErroCapturaConab("manifesto fonte não atende esquema V1")
        entries=[x for x in doc["edicoes"] if isinstance(x,dict)
                 and x.get("id_edicao")==args.id_edicao]
        if len(entries)!=1:
            raise ErroCapturaConab("edição ausente ou duplicada no manifesto")
        result=capturar_xlsx_conab(
            entries[0],destino=args.destino,
            autoriza_requisicao=args.autorizar_requisicao,
            direitos_coleta_conferidos=args.direitos_coleta_conferidos,
        )
    except (OSError,ValueError,PermissionError) as exc:
        p.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
