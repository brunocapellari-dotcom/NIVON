"""Auditoria estritamente offline de planilhas semanais de várias vintages.

Compara bytes locais com hashes/tamanhos publicados por TERCEIRO (agrobr),
depois reexecuta parser NIVON e oráculos disponíveis. Não baixa fonte,
não concede direitos, não altera banco e não libera migração/publicação.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import date, datetime
from pathlib import Path

from .conab_replay_xlsx import ErroXlsxProgresso, reexecutar_xlsx_conab

SCHEMA = "NIVON_CONAB_REFERENCIAS_TERCEIRO_V1"
_PROVIDER = "bruno-portfolio/agrobr"
_MAX_RAW = 20_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GITSHA = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"AGROBR_20[0-9]{6}\Z")
_BASENAME = re.compile(r"agrobr_20[0-9]{6}\.xlsx\Z")
_SOURCE = re.compile(r"tests/golden_data/conab_progresso/[a-z0-9_/]+\.xlsx\Z")


class ErroAuditoriaVintages(ValueError):
    pass


def _datetime(text: str) -> datetime:
    try:
        value=datetime.fromisoformat(text)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone não declarado")
        return value
    except (TypeError,ValueError) as exc:
        raise ErroAuditoriaVintages("data de captura do terceiro ausente/inválida") from exc


def _validar_referencia(entry: dict):
    mandatory={"id","arquivo","origem_repositorio","git_blob_sha1","sha256","bytes",
               "competencia","captura_declarada","url_original_declarada",
               "observacoes_esperadas","culturas_esperadas"}
    if not isinstance(entry,dict) or set(entry)!=mandatory:
        raise ErroAuditoriaVintages("registro de referência fora de esquema")
    if (not _ID.fullmatch(str(entry["id"])) or not _BASENAME.fullmatch(str(entry["arquivo"]))
            or entry["arquivo"] != entry["id"].lower().replace("agrobr_","agrobr_")+".xlsx"
            or not _SOURCE.fullmatch(str(entry["origem_repositorio"]))
            or not _GITSHA.fullmatch(str(entry["git_blob_sha1"]))
            or not _SHA256.fullmatch(str(entry["sha256"]))):
        raise ErroAuditoriaVintages("ID, nome, origem git ou digest inválido")
    if type(entry["bytes"]) is not int or not 0<entry["bytes"]<=_MAX_RAW:
        raise ErroAuditoriaVintages("tamanho bruto inválido")
    try:
        competencia=date.fromisoformat(entry["competencia"])
        if competencia.isoformat()!=entry["competencia"]:
            raise ValueError("noncanonical date")
    except (TypeError,ValueError) as exc:
        raise ErroAuditoriaVintages("competência inválida") from exc
    captura=_datetime(entry["captura_declarada"])
    if captura.date()<competencia:
        raise ErroAuditoriaVintages("arquivo capturado antes de semana declarada")
    url=entry["url_original_declarada"]
    from .conab_agrobr import _url_conab,ErroProgresso
    try:
        _url_conab(url)
        if "/progresso-de-safra/" not in url:
            raise ErroProgresso("path errado")
    except ErroProgresso as exc:
        raise ErroAuditoriaVintages("URL original de CONAB fora do contrato") from exc
    n=entry["observacoes_esperadas"]
    if n is not None and (type(n) is not int or not 1<=n<=5000):
        raise ErroAuditoriaVintages("contagem oracular inválida")
    cultures=entry["culturas_esperadas"]
    if cultures is not None and (not isinstance(cultures,list)
            or not 1<=len(cultures)<=20
            or any(not isinstance(x,str) or not x for x in cultures)
            or len(cultures)!=len(set(cultures))):
        raise ErroAuditoriaVintages("oráculo de culturas inválido")


def validar_catalogo_vintages(catalogo: dict):
    if (not isinstance(catalogo,dict)
            or set(catalogo)!={"schema","fornecedor_referencia","natureza","edicoes"}
            or catalogo["schema"]!=SCHEMA
            or catalogo["fornecedor_referencia"]!=_PROVIDER
            or catalogo["natureza"]!="REFERENCIAS_PUBLICADAS_POR_TERCEIRO_NAO_CAPTURA_DIRETA_CONAB"
            or not isinstance(catalogo["edicoes"],list)
            or not 1<=len(catalogo["edicoes"])<=52):
        raise ErroAuditoriaVintages("catálogo multivintage sem contrato conhecido")
    for entry in catalogo["edicoes"]:
        _validar_referencia(entry)
    for key in ("id","arquivo","competencia","sha256","origem_repositorio"):
        values=[x[key] for x in catalogo["edicoes"]]
        if len(values)!=len(set(values)):
            raise ErroAuditoriaVintages("referência duplicada: "+key)
    return catalogo


def auditar_vintages_conab(catalogo: dict, diretorio: str | Path) -> dict:
    """Reexecuta apenas arquivos já disponibilizados pelo operador na pasta.

    Ausência de arquivos é explícita; qualquer arquivo encontrado que não
    passe SHA/oráculo causa erro fatal, nunca é ignorado ou reaproveitado.
    """
    entries=validar_catalogo_vintages(catalogo)["edicoes"]
    folder=Path(diretorio)
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
        raise ErroAuditoriaVintages("pasta absoluta existente e sem symlink necessária")
    found={p.name for p in folder.iterdir()}
    known={e["arquivo"] for e in entries}
    if not found<=known:
        raise ErroAuditoriaVintages("diretório contém arquivo não catalogado")
    passed=0
    summaries=[]
    parser_sha=None
    for entry in entries:
        file=folder/entry["arquivo"]
        info={
            "id":entry["id"],"competencia":entry["competencia"],
            "estado":"AGUARDANDO_RAW_DO_TERCEIRO",
            "hash_catalogado_sha256":entry["sha256"],
            "hash_validado_neste_ambiente":False,
            "parser_executado_neste_ambiente":False,
            "captura_direta_conab_atestada":False,
            "direitos_por_operacao_homologados":False,
        }
        if entry["arquivo"] not in found:
            summaries.append(info)
            continue
        if file.is_symlink() or not file.is_file():
            raise ErroAuditoriaVintages("RAW não regular ou symlink: "+entry["id"])
        if os.name=="posix" and stat.S_IMODE(file.stat().st_mode)&0o002:
            raise ErroAuditoriaVintages("RAW gravável por outros: "+entry["id"])
        if file.stat().st_size != entry["bytes"]:
            raise ErroAuditoriaVintages("tamanho diferente da origem catalogada: "+entry["id"])
        raw=file.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
            raise ErroAuditoriaVintages("SHA256 não coincide com registro do terceiro: "+entry["id"])
        try:
            parsed=reexecutar_xlsx_conab(
                raw,sha256_origem=entry["sha256"],
                url_origem=entry["url_original_declarada"],
                coletado_em=entry["captura_declarada"],
                publicado_em=None)
        except ErroXlsxProgresso as exc:
            raise ErroAuditoriaVintages("parser não suporta esta vintage: "+entry["id"]) from exc
        from json import loads
        rows=[loads(row) for row in parsed["mapa_semantico"].values()]
        weeks={row["competencia"] for row in rows}
        if weeks!={entry["competencia"]}:
            raise ErroAuditoriaVintages("semana observada difere da fonte catalogada: "+entry["id"])
        expected=entry["observacoes_esperadas"]
        if expected is not None and len(rows)!=expected:
            raise ErroAuditoriaVintages("contagem diverge do oráculo: "+entry["id"])
        cultures=entry["culturas_esperadas"]
        if cultures is not None and {row["cultura"] for row in rows}!=set(cultures):
            raise ErroAuditoriaVintages("culturas divergiram do oráculo: "+entry["id"])
        if parser_sha is not None and parser_sha!=parsed["parser_codigo_sha256"]:
            raise ErroAuditoriaVintages("versão do código do parser não foi estável")
        parser_sha=parsed["parser_codigo_sha256"]
        passed+=1
        info.update({
            "estado":"RAW_TERCEIRO_REPRODUZIDO_SEM_HOMOLOGACAO_OFICIAL",
            "hash_validado_neste_ambiente":True,
            "parser_executado_neste_ambiente":True,
            "observacoes_extraidas":len(rows),
            "parser_id":parsed["parser_id"],
            "parser_codigo_sha256":parsed["parser_codigo_sha256"],
        })
        summaries.append(info)
    return {
        "schema":"NIVON_CONAB_MULTI_VINTAGE_AUDIT_V1",
        "fornecedor_referencia":_PROVIDER,
        "edicoes_catalogadas":len(entries),
        "edicoes_presentes_reprocessadas":passed,
        "edicoes_pendentes":len(entries)-passed,
        "parser_multivintage_testado_localmente":passed>=2,
        "captura_proveniencia_oficial_comprovada":False,
        "licencas_confirmadas_individualmente":False,
        "migracao_permitida":False,
        "publicacao_permitida":False,
        "itens":summaries,
    }


def _json_strict(path: Path):
    if not path.is_file() or path.is_symlink() or not 0<path.stat().st_size<=100000:
        raise ErroAuditoriaVintages("catálogo inexistente ou inválido")
    def unique(pairs):
        v={}
        for key,value in pairs:
            if key in v:
                raise ErroAuditoriaVintages("JSON com chave duplicada")
            v[key]=value
        return v
    return json.loads(path.read_text(encoding="utf-8"),object_pairs_hook=unique)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Auditoria offline multi-vintage CONAB, sem download")
    parser.add_argument("--catalogo",required=True)
    parser.add_argument("--diretorio",required=True)
    parser.add_argument("--resumo",action="store_true")
    args=parser.parse_args(argv)
    try:
        doc=_json_strict(Path(args.catalogo))
        report=auditar_vintages_conab(doc,args.diretorio)
    except (OSError,ValueError,UnicodeError) as exc:
        parser.error(str(exc))
    if args.resumo:
        report.pop("itens")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
