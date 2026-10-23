"""AgroBR 2.0 -> CONAB safras mensais, consulta EXPLÍCITA por levantamento.

Conector é alternativa de TRANSPORTE E PARSING, não autoridade sobre
vintage/as-of: dados normalizados nunca liberam retroteste/treino/publicação.
A leitura de um DataFrame não prova hash ou disponibilidade da fonte original.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from importlib import import_module
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit

class ErroAgroBRSafras(ValueError):
    pass

_SAFRA = re.compile(r"(20\d{2})/(\d{2})\Z")
_UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
_COLS = frozenset(("fonte", "produto", "safra", "uf",
                   "area_plantada", "area_colhida", "produtividade",
                   "producao", "levantamento", "data_publicacao"))
_METRICS = (("area_plantada", "mil_ha"), ("produtividade", "kg_ha"),
            ("producao", "mil_t"))
_STATUS = "AGROBR_CONAB_NORMALIZADO_SEM_RAW_OU_VINTAGE"


def _safra(valor):
    if not isinstance(valor,str):
        raise ErroAgroBRSafras("safra explícita obrigatória")
    m = _SAFRA.fullmatch(valor)
    if not m or (int(m[1])+1)%100 != int(m[2]):
        raise ErroAgroBRSafras("safra inválida")
    return valor


def _url_fonte(value):
    if not isinstance(value,str):
        raise ErroAgroBRSafras("AgroBR sem URL oficial do boletim")
    p = urlsplit(value)
    if (p.scheme != "https" or p.hostname not in
            ("www.gov.br", "www.conab.gov.br", "conab.gov.br") or
            p.username or p.password or p.port not in (None,443) or
            not p.path.startswith(("/conab/", "/pt-br/", "/"))):
        raise ErroAgroBRSafras("URL de origem não corresponde à CONAB")
    return value


def _numero(valor, campo):
    if valor is None or str(valor).strip().lower() in ("nan","nat","none","<na>"):
        return None
    try:
        text = str(valor).strip()
        if not 0<len(text)<=50:
            raise ValueError()
        d=Decimal(text)
        if not d.is_finite() or d<0 or d>Decimal("100000000000000"):
            raise ValueError()
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ErroAgroBRSafras("número inválido: "+campo) from exc
    return format(d,"f")


def _date(value):
    if value is None or str(value).strip().lower() in ("nan","nat","none","<na>"):
        return None
    if isinstance(value,datetime):
        return value.date().isoformat()
    if isinstance(value,date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ErroAgroBRSafras("data_publicacao inválida") from exc


def _coleta(value):
    if not isinstance(value,str) or "T" not in value:
        raise ErroAgroBRSafras("coleta requer ISO com timezone")
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        if d.tzinfo is None or d.utcoffset() is None:
            raise ValueError()
    except ValueError as exc:
        raise ErroAgroBRSafras("coleta inválida/sem timezone") from exc
    return d.astimezone(timezone.utc).isoformat()


def _records(frame):
    if hasattr(frame,"to_dict"):
        try:
            result=frame.to_dict(orient="records")
        except (TypeError, ValueError) as exc:
            raise ErroAgroBRSafras("DataFrame não compatível com pandas") from exc
    else:
        result=frame
    if not isinstance(result,list) or not result or len(result)>70:
        raise ErroAgroBRSafras("consulta sem registros ou excessiva")
    if any(not isinstance(x,dict) or not _COLS.issubset(x) for x in result):
        raise ErroAgroBRSafras("contrato de colunas CONAB 2.0 incompleto")
    return result


def _proveniencia(meta, target_safra, target_levantamento):
    details=getattr(meta,"source_details",None)
    if not isinstance(details,dict):
        raise ErroAgroBRSafras("MetaInfo.source_details obrigatório")
    publication=details.get("publicacao")
    if not isinstance(publication,dict) or publication.get("origem") == "serie_historica":
        raise ErroAgroBRSafras("metadado não identifica boletim de levantamento")
    numero=publication.get("levantamento")
    safra=publication.get("safra")
    if (type(numero) is not int or numero!=target_levantamento or
            safra!=target_safra):
        raise ErroAgroBRSafras("AgroBR devolveu edição diferente da solicitada")
    url=_url_fonte(publication.get("url") or getattr(meta,"source_url",None))
    pub=_date(publication.get("data_publicacao"))
    if not pub:
        raise ErroAgroBRSafras("metadado da data de publicação ausente")
    return {"url":url,"data_publicacao_declarada":pub}


def normalizar_safras_agrobr(
    *, frame, meta, produto: str, safra: str, levantamento: int,
    uf: str | None, coletado_em: str,
) -> dict:
    """Rejeita fallback, edições implícitas, nulidades mal convertidas e mix de UFs."""
    _safra(safra)
    if produto not in ("soja","milho"):
        raise ErroAgroBRSafras("somente soja e milho nesta integração")
    if type(levantamento) is not int or not 1<=levantamento<=12:
        raise ErroAgroBRSafras("levantamento explícito 1..12")
    if uf is not None and uf not in _UFS:
        raise ErroAgroBRSafras("UF inválida")
    instante=_coleta(coletado_em)
    prov=_proveniencia(meta,safra,levantamento)
    if prov["data_publicacao_declarada"]>instante[:10]:
        raise ErroAgroBRSafras("publicação declarada posterior à captura")
    rows=_records(frame)
    seen=set()
    normalized=[]
    for row in rows:
        p=row["produto"]
        u=row["uf"]
        if (p!=produto or row["safra"]!=safra or
                not isinstance(u,str) or u not in _UFS or
                (uf is not None and u!=uf) or
                type(row["levantamento"]) is not int or
                row["levantamento"]!=levantamento):
            raise ErroAgroBRSafras("linha não pertence a produto/UF/edição explícitos")
        if u in seen:
            raise ErroAgroBRSafras("UF duplicada na edição")
        seen.add(u)
        pub=_date(row["data_publicacao"])
        if pub!=prov["data_publicacao_declarada"]:
            raise ErroAgroBRSafras("publicação da linha diverge do MetaInfo")
        if row["area_colhida"] is not None and _numero(row["area_colhida"],"area_colhida") is not None:
            raise ErroAgroBRSafras("CONAB não publicou área colhida distinta")
        values={name:_numero(row[name],name) for name,_ in _METRICS}
        if all(v is None for v in values.values()):
            raise ErroAgroBRSafras("linha sem indicadores")
        normalized.append({
            "uf":u,
            "produto":p,
            "safra":safra,
            "levantamento":levantamento,
            **values,
            "unidades":{"area_plantada":"MIL_HA",
                        "produtividade":"KG_HA","producao":"MIL_T"},
            "data_publicacao_declarada":pub,
            "data_disponibilidade_historica":None,
            "evidencia_bruta_sha256":None,
            "area_colhida_disponivel":False,
        })
    if uf is not None and len(normalized)!=1:
        raise ErroAgroBRSafras("UF solicitada não retornou exatamente uma linha")
    normalized.sort(key=lambda r:r["uf"])
    # Digest deste JSON NÃO é SHA da planilha oficial.
    canonical=json.dumps(normalized,sort_keys=True,ensure_ascii=False,
                         separators=(",",":"),allow_nan=False).encode()
    return {
        "status":_STATUS,
        "source_id":"CONAB_VIA_AGROBR",
        "transport_library":"agrobr==2.0.0",
        "produto":produto,"safra":safra,"uf_filtro":uf,
        "levantamento":levantamento,
        "url_fonte_declarada":prov["url"],
        "data_publicacao_declarada":prov["data_publicacao_declarada"],
        "coletado_em":instante,
        "sha256_json_normalizado_nao_raw":sha256(canonical).hexdigest(),
        "raw_conab_sha256":None,
        "registros":normalized,"total":len(normalized),
        "fonte_primaria":"CONAB","canal_parser":"AGROBR",
        "consulta_de_edicao_explicita":True,
        "edicao_historica_autenticada":False,
        "disponibilidade_asof_comprovada":False,
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
    }


async def consultar_safras_agrobr(
    *, produto: str, safra: str, levantamento: int, uf: str | None = None,
    direitos_confirmados: bool = False, api=None, coletado_em: str | None = None,
) -> dict:
    """Conector fonte direta, SEM fallback para LSPA ou série histórica."""
    _safra(safra)
    if produto not in ("soja","milho") or type(levantamento) is not int or not 1<=levantamento<=12:
        raise ErroAgroBRSafras("cultura/levantamento inválidos")
    if uf is not None and uf not in _UFS:
        raise ErroAgroBRSafras("UF inválida")
    if direitos_confirmados is not True:
        raise PermissionError("uso/coleta de dados CONAB ainda requer autorização explícita no processo")
    if api is None:
        try:
            pkg=import_module("agrobr")
            api=pkg.conab
            version=getattr(pkg,"__version__","")
            if not isinstance(version,str) or version.split(".")[:2]!=["2","0"]:
                raise ErroAgroBRSafras("contrato agrobr 2.0.0 não verificado")
        except ImportError as exc:
            raise ErroAgroBRSafras("instalar NIVON[agro] no worker") from exc
    result=await api.safras(
        produto, safra=safra, uf=uf, levantamento=levantamento,
        return_meta=True,
    )
    if not isinstance(result,tuple) or len(result)!=2:
        raise ErroAgroBRSafras("agrobr deve retornar DataFrame e MetaInfo")
    return normalizar_safras_agrobr(
        frame=result[0],meta=result[1],produto=produto,safra=safra,
        levantamento=levantamento,uf=uf,
        coletado_em=coletado_em or datetime.now(timezone.utc).isoformat(),
    )


def consultar_lote_agrobr(*, safra: str, levantamento: int, uf: str = "MT",
                         direitos_confirmados: bool = False, apis=None) -> dict:
    """SOJA e MILHO serialmente, sem fallback cruzado ou gravação automática."""
    async def go():
        items=[]
        for p in ("soja","milho"):
            items.append(await consultar_safras_agrobr(
                produto=p,safra=safra,levantamento=levantamento,uf=uf,
                direitos_confirmados=direitos_confirmados,api=apis,
            ))
        return items
    products=asyncio.run(go())
    return {
        "status":"LOTE_AGROBR_CONAB_SEM_RAW_NEM_VINTAGE",
        "safra":safra,"levantamento":levantamento,"uf":uf,
        "culturas":products,"total_registros":sum(x["total"] for x in products),
        "raw_conab_comprovado":False,
        "edicao_historica_autenticada":False,
        "disponibilidade_asof_comprovada":False,
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
    }


def _guardar_staging_sqlite(path: str, document: dict) -> dict:
    if (document.get("status")!="LOTE_AGROBR_CONAB_SEM_RAW_NEM_VINTAGE" or
            document.get("habilita_publicacao") is not False or
            document.get("habilita_backtest") is not False or
            document.get("disponibilidade_asof_comprovada") is not False):
        raise ErroAgroBRSafras("lote tenta promover dados sem vintage")
    file=Path(path)
    if file.is_symlink() or not file.parent.is_dir() or file.stat().st_size>50_000_000 if file.exists() else file.is_symlink() or not file.parent.is_dir():
        raise ErroAgroBRSafras("SQLite inválido")
    rows=[]
    for d in document["culturas"]:
        if d.get("status")!=_STATUS or d.get("raw_conab_sha256") is not None or d.get("habilita_publicacao") is not False:
            raise ErroAgroBRSafras("cultura sem contrato de staging")
        for item in d["registros"]:
            rows.append((
                d["produto"],d["safra"],d["levantamento"],item["uf"],
                d["coletado_em"],d["url_fonte_declarada"],
                d["sha256_json_normalizado_nao_raw"],
                json.dumps(item,sort_keys=True,ensure_ascii=False,allow_nan=False),
            ))
    with sqlite3.connect(file,timeout=5) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS conab_agrobr_staging (
              id INTEGER PRIMARY KEY, produto TEXT NOT NULL,
              safra TEXT NOT NULL, levantamento INTEGER NOT NULL,
              uf TEXT NOT NULL, coletado_em TEXT NOT NULL,
              url_declarada TEXT NOT NULL, sha256_json_normalizado TEXT NOT NULL,
              linha_json TEXT NOT NULL,
              classe TEXT NOT NULL DEFAULT 'SEM_RAW_SEM_VINTAGE'
                CHECK(classe='SEM_RAW_SEM_VINTAGE'),
              UNIQUE(produto,safra,levantamento,uf,sha256_json_normalizado)
        )""")
        before=db.total_changes
        db.executemany(
            """INSERT OR IGNORE INTO conab_agrobr_staging
            (produto,safra,levantamento,uf,coletado_em,url_declarada,
             sha256_json_normalizado,linha_json) VALUES (?,?,?,?,?,?,?,?)""",rows
        )
        inserted=db.total_changes-before
    return {"gravados":inserted,"recebidos":len(rows),
            "duplicatas":len(rows)-inserted,
            "classe":"SEM_RAW_SEM_VINTAGE",
            "habilita_backtest":False,"habilita_publicacao":False}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="AgroBR→CONAB por edição; sem fallback/backtest")
    p.add_argument("--safra",required=True)
    p.add_argument("--levantamento",type=int,required=True)
    p.add_argument("--uf",default="MT")
    p.add_argument("--permitir-consulta",action="store_true")
    p.add_argument("--out",required=True)
    p.add_argument("--sqlite")
    a=p.parse_args(argv)
    try:
        if not a.permitir_consulta:
            raise ErroAgroBRSafras("consulta desativada: confirmar --permitir-consulta")
        out=Path(a.out)
        if out.is_symlink() or out.exists() or not out.parent.is_dir():
            raise ErroAgroBRSafras("saída já existe ou é insegura")
        result=consultar_lote_agrobr(
            safra=a.safra,levantamento=a.levantamento,uf=a.uf,
            direitos_confirmados=a.permitir_consulta,
        )
        if a.sqlite:
            result["staging_sqlite"]=_guardar_staging_sqlite(a.sqlite,result)
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.write("\n")
        print("REGISTROS="+str(result["total_registros"])+" ASOF=NAO")
        return 0
    except (ErroAgroBRSafras,PermissionError,OSError,sqlite3.Error,ValueError) as exc:
        print("CONAB AGROBR BLOQUEADO: "+str(exc),file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
