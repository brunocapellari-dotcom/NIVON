"""Auditoria offline de vínculo entre página CONAB e XLSX oferecido localmente.

O endereço de publicação pode ser verificado publicamente, mas NÃO prova
que bytes fornecidos pelo operador vieram daquele endereço. Nunca coleta,
migra, registra autorização de direitos ou divulga números.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .conab_replay_xlsx import reexecutar_xlsx_conab, ErroXlsxProgresso
from .verificador_bytes_origem import conferir_bytes_origem, ErroBytesOrigem

_SC = "NIVON_CONAB_PAGINA_ANEXO_V1"
_PREFIX = "/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class ErroProvenienciaConab(ValueError):
    pass


def _dia(value: str) -> date:
    try:
        d = date.fromisoformat(value)
        if d.isoformat() != value:
            raise ValueError("data não canônica")
        return d
    except (TypeError, ValueError) as exc:
        raise ErroProvenienciaConab("datas do portal precisam ser YYYY-MM-DD") from exc


def _url(value: str, *, anexo: bool) -> str:
    if not isinstance(value, str):
        raise ErroProvenienciaConab("endereço não é string")
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.hostname not in {"www.gov.br","conab.gov.br","www.conab.gov.br"}
                or p.username or p.password or p.port not in (None,443)
                or p.query or p.fragment or not p.path.startswith(_PREFIX)
                or "//" in p.path or ".." in p.path or "%" in p.path):
            raise ErroProvenienciaConab("URL CONAB fora do contrato")
        end = p.path.removeprefix(_PREFIX).strip("/").split("/")
        if len(end) != 2 or not end[0].startswith("acompanhamento-das-lavouras-"):
            raise ErroProvenienciaConab("não é uma página de edição semanal da CONAB")
        if anexo and not end[1].startswith("plantio-e-colheita-"):
            raise ErroProvenienciaConab("URL de anexo não identifica plantio e colheita")
        if not anexo and not end[1].startswith("acompanhamento-das-lavouras-"):
            raise ErroProvenienciaConab("URL de publicação semanal inesperada")
    except ValueError as exc:
        if isinstance(exc, ErroProvenienciaConab):
            raise
        raise ErroProvenienciaConab("URL com porta malformada") from exc
    return value


def validar_publicacao_conab(reg: dict) -> dict:
    """Registra evidência editorial verificável, não declara posse do RAW."""
    expected = {"id_edicao","url_pagina","url_anexo","publicacao_data",
                "pagina_inicio","pagina_fim","planilha_inicio","planilha_fim",
                "conteudo_sha256_verificado"}
    if not isinstance(reg,dict) or set(reg) != expected:
        raise ErroProvenienciaConab("contrato da edição semanal incompleto")
    key = reg["id_edicao"]
    if not isinstance(key,str) or not re.fullmatch(r"CONAB_PROG_[0-9]{4}_[0-9]{2}_[0-9]{2}",key):
        raise ErroProvenienciaConab("identificador da edição inválido")
    page = _url(reg["url_pagina"],anexo=False)
    annex = _url(reg["url_anexo"],anexo=True)
    ap=urlsplit(page).path.strip("/").split("/")
    aa=urlsplit(annex).path.strip("/").split("/")
    if ap[-2] != aa[-2]:
        raise ErroProvenienciaConab("link de anexo aponta para outra edição")
    published = _dia(reg["publicacao_data"])
    page_start,page_end = _dia(reg["pagina_inicio"]),_dia(reg["pagina_fim"])
    xls_start,xls_end = _dia(reg["planilha_inicio"]),_dia(reg["planilha_fim"])
    if (page_start>page_end or xls_start>xls_end or page_start>published
            or page_end>published or xls_end>published
            or (page_end-page_start).days != 6
            or (xls_end-xls_start).days != 6
            or not 0 <= (page_start-xls_start).days <= 7
            or not 0 <= (page_end-xls_end).days <= 7):
        raise ErroProvenienciaConab("janelas semanais/publicação incoerentes")
    if key != "CONAB_PROG_"+page_end.strftime("%Y_%m_%d"):
        raise ErroProvenienciaConab("ID não corresponde à semana da publicação")
    digest=reg["conteudo_sha256_verificado"]
    if digest is not None and (not isinstance(digest,str) or not _SHA.fullmatch(digest)):
        raise ErroProvenienciaConab("hash declarado inválido")
    return {
        "id_edicao":key,"status":"PAGINA_E_ANEXO_IDENTIFICADOS_RAW_NAO_AUTENTICADO",
        "url_pagina":page,"url_anexo":annex,
        "pagina_publicada_data":published.isoformat(),
        "semana_planilha":xls_end.isoformat(),
        "raw_sha256_declarado":digest,
        "raw_verificado_localmente":False,
        "acesso_ao_anexo_comprovado":False,
        "direitos_individuais_comprovados":False,
        "migracao_permitida":False,
    }


def auditar_conab_local(reg: dict, *, bytes_anexo: bytes | None,
                       coletado_utc: str | None = None) -> dict:
    """Teste de estrutura: bytes entregues não provam origem via URL."""
    meta=validar_publicacao_conab(reg)
    if bytes_anexo is None:
        if coletado_utc is not None:
            raise ErroProvenienciaConab("coleta informada sem arquivo")
        return meta
    if not isinstance(bytes_anexo,bytes) or not bytes_anexo:
        raise ErroProvenienciaConab("arquivo bruto ausente ou não é bytes")
    if not isinstance(coletado_utc,str):
        raise ErroProvenienciaConab("timestamp de aquisição com fuso obrigatório")
    try:
        dt=datetime.fromisoformat(coletado_utc.replace("Z","+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("sem fuso")
        dt=dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ErroProvenienciaConab("timestamp de coleta inválido") from exc
    # Publicação sem timezone no portal: filtrar apenas por dia, não inventar hora UTC.
    if dt.date() < date.fromisoformat(meta["pagina_publicada_data"]):
        raise ErroProvenienciaConab("coleta anterior à publicação declarada")
    digest=hashlib.sha256(bytes_anexo).hexdigest()
    if reg["conteudo_sha256_verificado"] is not None and reg["conteudo_sha256_verificado"]!=digest:
        raise ErroProvenienciaConab("hash do arquivo local difere do manifesto")
    try:
        conferir_bytes_origem(payload=bytes_anexo,sha256_informado=digest,
                              tamanho_informado=len(bytes_anexo),
                              mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        extracted=reexecutar_xlsx_conab(
            bytes_anexo,sha256_origem=digest,url_origem=reg["url_anexo"],
            coletado_em=coletado_utc,publicado_em=None)
    except (ErroBytesOrigem, ErroXlsxProgresso) as exc:
        raise ErroProvenienciaConab("arquivo local XLSX inválido ou incompatível com parser") from exc
    weeks={key[-1] for key in extracted["mapa_semantico"]}
    if weeks != {meta["semana_planilha"]}:
        raise ErroProvenienciaConab("semana das observações difere da janela do anexo")
    return {
        **meta,"status":"BYTES_LOCAIS_VALIDOS_SEM_PROVA_CADEIA_DE_DOWNLOAD",
        "raw_sha256_calculado":digest,"bytes_validados":len(bytes_anexo),
        "quantidade_observacoes":extracted["observacoes"],
        "parser_id":extracted["parser_id"],
        "parser_codigo_sha256":extracted["parser_codigo_sha256"],
        "raw_verificado_localmente":True,
        "acesso_ao_anexo_comprovado":False,
        "direitos_individuais_comprovados":False,
        "migracao_permitida":False,
    }


def auditar_manifesto_edicoes(manifesto: dict) -> dict:
    if (not isinstance(manifesto,dict) or set(manifesto)!={"schema","edicoes"}
            or manifesto["schema"]!=_SC
            or not isinstance(manifesto["edicoes"],list)
            or not 1<=len(manifesto["edicoes"])<=52):
        raise ErroProvenienciaConab("manifesto de edições não segue V1")
    records=[validar_publicacao_conab(r) for r in manifesto["edicoes"]]
    ids=[x["id_edicao"] for x in records]
    if len(ids)!=len(set(ids)):
        raise ErroProvenienciaConab("edição duplicada no catálogo")
    annex=[x["url_anexo"] for x in records]
    if len(annex)!=len(set(annex)):
        raise ErroProvenienciaConab("anexo compartilhado por edições diferentes")
    return {
        "schema":_SC,"edicoes_identificadas":len(records),
        "edicoes_com_raw_autenticado":0,
        "edicoes_com_direitos_homologados":0,
        "estados":records,
        "migracao_permitida":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Auditoria offline das edições oficiais (sem baixar arquivos)")
    p.add_argument("--manifesto",required=True)
    p.add_argument("--resumo",action="store_true")
    a=p.parse_args(argv)
    f=Path(a.manifesto)
    if not f.is_file() or f.is_symlink() or f.stat().st_size>100_000:
        p.error("manifesto ausente, symlink ou muito grande")
    try:
        reg=json.loads(f.read_text(encoding="utf-8"))
        result=auditar_manifesto_edicoes(reg)
    except (OSError,UnicodeError,ValueError) as exc:
        p.error(str(exc))
    if a.resumo:
        result.pop("estados")
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
