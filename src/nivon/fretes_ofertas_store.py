"""Store SQLite dos registros individuais de FRETES ANUNCIADOS R01.

Não autoriza coleta do WhatsApp nem presume direitos de uso, autenticidade do
RAW ou contratação. O adaptador externo deve verificar assinaturas e permissões
ANTES de fornecer OfertaFrete. Persistência local com hash encadeado.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import hmac
import json
import sqlite3
from typing import Mapping, Sequence

from .fretes_registros import ErroRegistroFrete, OfertaFrete
from .fretes_atestacoes import serializacao_canonica

GENESIS = "0"*64
PREFIXO = b"NIVON_FRETE_OFERTA_STORE_V1\x00"
VALORES_DECIMAIS = ("frete_base_brl_t", "pedagio_brl_t", "frete_cheio_brl_t")
CAMPOS = frozenset(x.name for x in fields(OfertaFrete))


class ErroStoreOfertaFrete(ErroRegistroFrete):
    pass


def _sha(valor: object, campo: str) -> str:
    if not isinstance(valor,str) or len(valor)!=64 or any(c not in "0123456789abcdef" for c in valor):
        raise ErroStoreOfertaFrete(f"{campo}: digest SHA256 inválido")
    return valor


def _object(o: OfertaFrete) -> dict:
    if not isinstance(o,OfertaFrete):
        raise ErroStoreOfertaFrete("OfertaFrete canônica obrigatória")
    saida={}
    for c in CAMPOS:
        v=getattr(o,c)
        if isinstance(v,Decimal):
            saida[c]=str(v)
        elif isinstance(v,(date,datetime)):
            saida[c]=v.isoformat()
        else:
            saida[c]=v
    return saida


def _reconstruir(obj: Mapping) -> OfertaFrete:
    if not isinstance(obj,dict) or set(obj)!=CAMPOS:
        raise ErroStoreOfertaFrete("payload de oferta incompatible")
    dados=dict(obj)
    try:
        for nome in VALORES_DECIMAIS:
            valor=dados[nome]
            if valor is not None and type(valor) is not str:
                raise ValueError("decimal sem texto")
            dados[nome]=Decimal(valor) if valor is not None else None
        if type(dados["data_referencia"]) is not str:
            raise ValueError("data não textual")
        dados["data_referencia"]=date.fromisoformat(dados["data_referencia"])
        for nome in ("data_publicacao","data_coleta"):
            if type(dados[nome]) is not str:
                raise ValueError("hora não textual")
            dados[nome]=datetime.fromisoformat(dados[nome].replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:
        raise ErroStoreOfertaFrete("valores da oferta arquivada inválidos") from exc
    return OfertaFrete(**dados)


def _comprovante(v: object) -> dict:
    if not isinstance(v,Mapping) or set(v)!={
            "raw_sha256", "direitos_sha256", "resolucao_sha256",
            "provedor", "tenant_pseudonimizado"}:
        raise ErroStoreOfertaFrete("proveniencia declarada incompleta")
    for c in ("raw_sha256","direitos_sha256","resolucao_sha256"):
        _sha(v[c],c)
    for c in ("provedor","tenant_pseudonimizado"):
        if not isinstance(v[c],str) or not 1<=len(v[c])<=120 or v[c].strip()!=v[c]:
            raise ErroStoreOfertaFrete("provedor/tenant não identificado")
    return dict(v)


def _digest(anterior: str, payload: Mapping) -> str:
    return sha256(PREFIXO+anterior.encode("ascii")+serializacao_canonica(payload)).hexdigest()


def inicializar_store_ofertas_frete(con: sqlite3.Connection) -> None:
    if not isinstance(con,sqlite3.Connection) or con.in_transaction:
        raise ErroStoreOfertaFrete("SQLite sem transação externa obrigatório")
    con.executescript("""
      CREATE TABLE IF NOT EXISTS nivon_frete_ofertas_v1 (
        sequencia INTEGER PRIMARY KEY AUTOINCREMENT,
        registro_id TEXT NOT NULL UNIQUE,
        fonte_id TEXT NOT NULL,
        referencia_dia TEXT NOT NULL,
        coleta_em TEXT NOT NULL,
        anterior_sha256 TEXT NOT NULL,
        registro_sha256 TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL
      );
      CREATE TRIGGER IF NOT EXISTS nivon_frete_ofertas_sem_update
      BEFORE UPDATE ON nivon_frete_ofertas_v1
      BEGIN SELECT RAISE(ABORT,'append_only_ofertas'); END;
      CREATE TRIGGER IF NOT EXISTS nivon_frete_ofertas_sem_delete
      BEFORE DELETE ON nivon_frete_ofertas_v1
      BEGIN SELECT RAISE(ABORT,'append_only_ofertas'); END;
    """)


def verificar_store_ofertas_frete(
    con: sqlite3.Connection, *, cabeca_esperada_sha256: str,
) -> dict:
    """Valida cadeia interna contra a cabeça OUTSIDE; não atesta documentos."""
    if not isinstance(con,sqlite3.Connection):
        raise ErroStoreOfertaFrete("SQLite obrigatório")
    _sha(cabeca_esperada_sha256,"cabeça externa de ofertas")
    rows=con.execute(
        "SELECT sequencia,registro_id,fonte_id,referencia_dia,coleta_em,"
        "anterior_sha256,registro_sha256,payload_json FROM nivon_frete_ofertas_v1 "
        "ORDER BY sequencia ASC"
    ).fetchall()
    anterior=GENESIS
    ofertas=[]
    evidencias=[]
    for n, row in enumerate(rows,1):
        seq,rid,fonte,dia,coleta,anterior_db,digest,raw=row
        if seq!=n or anterior_db!=anterior:
            raise ErroStoreOfertaFrete("sequência truncada ou cadeia rompida")
        try:
            payload=json.loads(raw)
        except (ValueError,TypeError) as exc:
            raise ErroStoreOfertaFrete("registro de oferta inválido") from exc
        if (not isinstance(payload,dict) or set(payload)!={"oferta","evidencia"}
                or serializacao_canonica(payload).decode("utf-8")!=raw):
            raise ErroStoreOfertaFrete("payload de origem alterado ou não canônico")
        oferta=_reconstruir(payload["oferta"])
        prova=_comprovante(payload["evidencia"])
        if (rid!=oferta.registro_id or fonte!=oferta.fonte_id
                or dia!=oferta.data_referencia.isoformat()
                or coleta!=oferta.data_coleta.astimezone(timezone.utc).isoformat()):
            raise ErroStoreOfertaFrete("metadados divergentes dos dados de oferta")
        if not hmac.compare_digest(_digest(anterior,payload),digest):
            raise ErroStoreOfertaFrete("registro SHA adulterado")
        anterior=digest
        ofertas.append(oferta)
        evidencias.append(prova)
    if anterior!=cabeca_esperada_sha256:
        raise ErroStoreOfertaFrete("cabeça de ofertas diverge da âncora fornecida")
    return {
        "status":"OFERTAS_PERSISTIDAS_OFFLINE_SHA_VALIDADO",
        "cabeca_sha256":anterior,"registros":len(ofertas),
        "ofertas":ofertas,
        "evidencias_declaradas":evidencias,
        "raw_autenticado_externamente":False,
        "direitos_comprovados_externamente":False,
        "ancora_temporal_independente":False,
        "publicavel":False,
    }


def anexar_lote_ofertas_frete(
    con: sqlite3.Connection, ofertas: Sequence[OfertaFrete], *,
    evidencias: Mapping[str,Mapping], cabeca_anterior_sha256: str,
) -> dict:
    """Insere até 500 ofertas em transação indivisível (não sobrescreve)."""
    if (not isinstance(con,sqlite3.Connection) or con.in_transaction
            or not isinstance(ofertas,(list,tuple)) or not 1<=len(ofertas)<=500
            or not isinstance(evidencias,Mapping)):
        raise ErroStoreOfertaFrete("lote de ofertas ou transação inválidos")
    _sha(cabeca_anterior_sha256,"cabeça anterior de ofertas")
    if set(evidencias)!={x.registro_id for x in ofertas if isinstance(x,OfertaFrete)}:
        raise ErroStoreOfertaFrete("evidência individual não corresponde aos registros")
    try:
        con.execute("BEGIN IMMEDIATE")
        estado=verificar_store_ofertas_frete(
            con,cabeca_esperada_sha256=cabeca_anterior_sha256
        )
        identificadores={x.registro_id for x in estado["ofertas"]}
        anterior=cabeca_anterior_sha256
        for oferta in ofertas:
            obj=_object(oferta)
            if oferta.registro_id in identificadores:
                raise ErroStoreOfertaFrete("registro_id reutilizado no histórico")
            prova=_comprovante(evidencias[oferta.registro_id])
            payload={"oferta":obj,"evidencia":prova}
            digest=_digest(anterior,payload)
            con.execute(
                "INSERT INTO nivon_frete_ofertas_v1 "
                "(registro_id,fonte_id,referencia_dia,coleta_em,anterior_sha256,"
                "registro_sha256,payload_json) VALUES(?,?,?,?,?,?,?)",
                (oferta.registro_id,oferta.fonte_id,
                 oferta.data_referencia.isoformat(),
                 oferta.data_coleta.astimezone(timezone.utc).isoformat(),
                 anterior,digest,serializacao_canonica(payload).decode("utf-8")),
            )
            identificadores.add(oferta.registro_id)
            anterior=digest
        con.commit()
        return {
            "status":"LOTE_OFERTAS_DECLARADAS_PERSISTIDO_SQLITE",
            "adicionados":len(ofertas),
            "total":estado["registros"]+len(ofertas),
            "cabeca_sha256":anterior,
            "raw_autenticado_externamente":False,
            "direitos_comprovados_externamente":False,
            "publicavel":False,
        }
    except (sqlite3.Error,ValueError,TypeError,KeyError) as exc:
        con.rollback()
        if isinstance(exc,ErroStoreOfertaFrete):
            raise
        raise ErroStoreOfertaFrete("lote de ofertas revertido sem persistência") from exc
