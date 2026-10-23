"""Lote CONAB: baixar referências GitHub fixadas -> auditar -> estágio SQLite LAB.

As fontes binárias são fixtures públicas de TERCEIRO, não capturas CONAB.
Tudo roda em diretório temporário e SQLite em memória; jamais toca banco real.
Não integra ou habilita coletor contínuo, publica dados ou altera catálogo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .auditoria_vintages_conab import (
    ErroAuditoriaVintages, _json_strict, auditar_vintages_conab, validar_catalogo_vintages,
)
from .conab_replay_xlsx import reexecutar_xlsx_conab

GITHUB_COMMIT = "befb27dd2e9929fab51d0eb308968927fe361840"
GITHUB_REPO = "bruno-portfolio/agrobr"
GITHUB_HOST = "raw.githubusercontent.com"
_GIT_PREFIX = f"https://{GITHUB_HOST}/{GITHUB_REPO}/{GITHUB_COMMIT}/"
_MAX_FILE = 20_000_000
_MAX_BATCH = 25_000_000


class ErroLoteConab(ValueError):
    pass


class _SemRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _http_real():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SemRedirect(),
        urllib.request.HTTPSHandler(),
    ).open


def _url_fixada(reference: dict) -> str:
    path=reference["origem_repositorio"]
    if (not isinstance(path,str) or not path.startswith("tests/golden_data/conab_progresso/")
            or not path.endswith(".xlsx") or ".." in path or "%" in path):
        raise ErroLoteConab("caminho de terceiro não permitido")
    return _GIT_PREFIX+path


def _baixar_arquivo(reference: dict, *, transport=None) -> bytes:
    """Download de UM arquivo do commit imutável; nenhum fallback não verificado."""
    url=_url_fixada(reference)
    request=urllib.request.Request(url,method="GET",headers={
        "Accept":"application/octet-stream",
        "User-Agent":"NIVON-data-validation/0.1 (public pinned GitHub reference)",
    })
    opener=transport or _http_real()
    try:
        with opener(request,timeout=15) as response:
            if getattr(response,"status",None)!=200 or response.geturl()!=url:
                raise ErroLoteConab("resposta HTTP inesperada ou redirect")
            declared=response.headers.get("Content-Length")
            if declared is not None and int(declared)!=reference["bytes"]:
                raise ErroLoteConab("Content-Length difere do catálogo de referência")
            chunks=[]
            size=0
            while True:
                b=response.read(65536)
                if not isinstance(b,bytes):
                    raise ErroLoteConab("download não retornou bytes")
                if not b:break
                size+=len(b)
                if size>_MAX_FILE or size>reference["bytes"]:
                    raise ErroLoteConab("arquivo maior que o hash/tamanho esperado")
                chunks.append(b)
    except (OSError,urllib.error.URLError,OverflowError) as exc:
        raise ErroLoteConab("falha em download GitHub de referência; sem contorno de origem") from exc
    data=b"".join(chunks)
    if len(data)!=reference["bytes"] or hashlib.sha256(data).hexdigest()!=reference["sha256"]:
        raise ErroLoteConab("bytes GitHub divergem do SHA-256/tamanho fixados")
    return data


def _gravar_apenas_novo(path: Path, data: bytes):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def obter_referencias_terceiro(catalogo: dict, destino: Path, *, transport=None) -> dict:
    """Obtém a lista inteira ou falha sem deixar arquivo parcial na pasta."""
    refs=validar_catalogo_vintages(catalogo)["edicoes"]
    if not destino.is_absolute() or destino.is_symlink() or not destino.is_dir() or any(destino.iterdir()):
        raise ErroLoteConab("pasta temporária absoluta precisa existir e estar vazia")
    if sum(ref["bytes"] for ref in refs)>_MAX_BATCH:
        raise ErroLoteConab("lote total excede limite")
    payloads=[]
    for ref in refs:
        payloads.append((ref["arquivo"],_baixar_arquivo(ref,transport=transport)))
    created=[]
    try:
        for name,data in payloads:
            f=destino/name
            _gravar_apenas_novo(f,data)
            created.append(f)
    except OSError:
        for f in created:f.unlink(missing_ok=True)
        raise
    return {"baixados":len(created),"bytes":sum(len(raw) for _,raw in payloads),
            "origem":"GITHUB_PUBLICO_COMMIT_FIXADO_NAO_CONAB_DIRETO",
            "git_sha_commit":GITHUB_COMMIT,
            "migracao_permitida":False}


def _stage(db: sqlite3.Connection):
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lab_referencia_conab (
            sha TEXT PRIMARY KEY, referencia_id TEXT NOT NULL UNIQUE,
            competencia TEXT NOT NULL, origem TEXT NOT NULL,
            parser_sha TEXT NOT NULL, qtde INTEGER NOT NULL CHECK(qtde>0)
        );
        CREATE TABLE IF NOT EXISTS lab_observacao_conab(
            sha TEXT NOT NULL REFERENCES lab_referencia_conab(sha),
            chave TEXT NOT NULL, observacao_json TEXT NOT NULL,
            PRIMARY KEY(sha,chave)
        );
    """)


def executar_lote_laboratorio(catalogo: dict, pasta: str | Path,
                             db: sqlite3.Connection) -> dict:
    """Auditoria obrigatória seguida de carga transacional em banco LAB isolado.

    Não escreve fora da conexão fornecida pelo chamador. Se uma edição falhar,
    nenhum registro de nova rodada é adicionado. Pode repetir sem duplicar.
    """
    report=auditar_vintages_conab(catalogo,pasta)
    if report["edicoes_pendentes"] or report["edicoes_presentes_reprocessadas"]<2:
        raise ErroLoteConab("lote exige todas referências, mínimo duas vintages processadas")
    entries=catalogo["edicoes"]
    batch=[]
    for ref in entries:
        raw=(Path(pasta)/ref["arquivo"]).read_bytes()
        if len(raw)!=ref["bytes"] or hashlib.sha256(raw).hexdigest()!=ref["sha256"]:
            raise ErroLoteConab("fonte local alterada após primeira auditoria")
        parsed=reexecutar_xlsx_conab(raw,sha256_origem=ref["sha256"],
            url_origem=ref["url_original_declarada"],
            coletado_em=ref["captura_declarada"],publicado_em=None)
        pairs=sorted((json.dumps(k,ensure_ascii=False,separators=(",",":")),v)
                     for k,v in parsed["mapa_semantico"].items())
        if len(pairs)!=parsed["observacoes"]:
            raise ErroLoteConab("chaves colidiram no staging")
        batch.append((ref,parsed,pairs))
    _stage(db)
    antes=db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0]
    try:
        with db:
            for ref,parsed,pairs in batch:
                record=db.execute("SELECT referencia_id,competencia,origem,parser_sha,qtde FROM lab_referencia_conab WHERE sha=?",
                                  (ref["sha256"],)).fetchone()
                wanted=(ref["id"],ref["competencia"],ref["origem_repositorio"],
                        parsed["parser_codigo_sha256"],len(pairs))
                if record is not None and tuple(record)!=wanted:
                    raise ErroLoteConab("mesma SHA com metadados LAB divergentes")
                if record is None:
                    db.execute("INSERT INTO lab_referencia_conab VALUES(?,?,?,?,?,?)",
                               (ref["sha256"],*wanted))
                old=dict(db.execute("SELECT chave,observacao_json FROM lab_observacao_conab WHERE sha=?",
                                    (ref["sha256"],)))
                if old and old!=dict(pairs):
                    raise ErroLoteConab("mesmo SHA com conteúdo de observações divergente")
                if not old:
                    db.executemany("INSERT INTO lab_observacao_conab VALUES(?,?,?)",
                        [(ref["sha256"],k,v) for k,v in pairs])
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise ErroLoteConab("chaves estrangeiras do LAB inconsistentes")
    except sqlite3.Error as exc:
        raise ErroLoteConab("transação LAB SQLite falhou") from exc
    depois=db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0]
    counts=dict(db.execute("SELECT sha,COUNT(*) FROM lab_observacao_conab GROUP BY sha"))
    if any(counts.get(ref["sha256"])!=len(pairs) for ref,_,pairs in batch):
        raise ErroLoteConab("contagem armazenada difere do parsing")
    return {
        "estado":"STAGING_TRANSACIONAL_APENAS_LAB_REFERENCIA_TERCEIRO",
        "edicoes_auditadas":len(batch),
        "edicoes_novas":depois-antes,
        "edicoes_ja_existentes":len(batch)-(depois-antes),
        "observacoes_stage_total":sum(counts.values()),
        "observacoes_por_competencia":[{
            "competencia":ref["competencia"],"quantidade":len(pairs),
            "sha256":ref["sha256"],
        } for ref,_,pairs in batch],
        "idempotencia_verificada_na_mesma_transacao":False,
        "fonte_conab_direta":False,"direitos_homologados":False,
        "integracao_banco_produtivo":False,
        "migracao_permitida":False,"publicacao_permitida":False,
    }


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="E2E multi-vintage real de terceiro, somente laboratório temporário")
    p.add_argument("--catalogo",required=True)
    p.add_argument("--diretorio",help="arquivos XLSX previamente autorizados; sem rede")
    p.add_argument("--obter-do-github",action="store_true",
                   help="busca somente fixtures públicas no commit fixo do agrobr")
    p.add_argument("--resumo",action="store_true")
    args=p.parse_args(argv)
    if args.obter_do_github and args.diretorio:
        p.error("usar --obter-do-github OU --diretorio, não ambos")
    if not args.obter_do_github and not args.diretorio:
        p.error("informar --diretorio ou --obter-do-github")
    try:
        doc=_json_strict(Path(args.catalogo))
        validar_catalogo_vintages(doc)
        with tempfile.TemporaryDirectory(prefix="nivon-conab-lab-") as tmp:
            if args.obter_do_github:
                fetched=obter_referencias_terceiro(doc,Path(tmp))
                folder=Path(tmp)
            else:
                fetched=None
                folder=Path(args.diretorio)
            with sqlite3.connect(":memory:") as db:
                first=executar_lote_laboratorio(doc,folder,db)
                second=executar_lote_laboratorio(doc,folder,db)
                if second["edicoes_novas"]!=0 or first["observacoes_stage_total"]!=second["observacoes_stage_total"]:
                    raise ErroLoteConab("rodada repetida não foi idempotente")
                first["idempotencia_verificada_na_mesma_transacao"]=True
            if fetched is not None:
                first["download_terceiro"]=fetched
        if args.resumo:
            first.pop("observacoes_por_competencia")
        print(json.dumps(first,ensure_ascii=False,sort_keys=True,indent=2))
        return 0
    except (OSError,ValueError,sqlite3.Error) as exc:
        p.error(str(exc))


if __name__=="__main__":
    raise SystemExit(main())
