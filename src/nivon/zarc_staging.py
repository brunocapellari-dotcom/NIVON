"""Staging SQLite offline/versionado para o CSV ZARC 2026/27.

NUNCA baixa dados ou ativa ingestão. Ingestão de arquivo REAL está bloqueada
pelo catálogo canônico via registrar_snapshot; SINTETICO exige fixture de teste.
O livro-razão nivon_snapshots é a fonte canônica de hashes/coletas. Grava-se
por linha física (número do CSV), não por uma chave de dimensões supostamente
única. Revisões são versões de SHA diferentes, não sobrescritas.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection

from .registro_snapshots import abrir_registro, registrar_snapshot
from .transacoes_sqlite import savepoint_atomico
from .zarc_dicionario_oficial import interpretar_metadados_linha, ErroDicionarioZarc
from .zarc_stream_mt import COLUNAS, FIXOS, URL, MAX_DOWNLOAD, MAX_LINHAS

DATASET = "ZARC_JANELAS"
SCHEMA = "ZARC_RAW_MT_V1"
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
LIMITE_CELULA = 500

class ErroStagingZarc(ValueError):
    pass


def _utc(texto):
    if not isinstance(texto, str):
        raise ErroStagingZarc("COLETA_INVALIDA")
    try:
        dt=datetime.fromisoformat(texto.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroStagingZarc("COLETA_INVALIDA") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroStagingZarc("COLETA_SEM_FUSO")
    return dt.astimezone(timezone.utc).isoformat()


def abrir_zarc_staging(caminho=":memory:") -> Connection:
    """Reutiliza ledger, mantendo índices ZARC estritamente locais."""
    db=abrir_registro(caminho)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS zarc_edicoes (
      sha256 TEXT PRIMARY KEY,
      dataset_id TEXT NOT NULL CHECK(dataset_id='ZARC_JANELAS'),
      competencia TEXT NOT NULL CHECK(competencia='2026/2027'),
      fonte_url TEXT NOT NULL,
      tamanho_bytes INTEGER NOT NULL CHECK(tamanho_bytes>0),
      linhas_total INTEGER NOT NULL CHECK(linhas_total>0),
      linhas_mt INTEGER NOT NULL CHECK(linhas_mt>0),
      municipios_mt INTEGER NOT NULL CHECK(municipios_mt>0),
      colunas_schema TEXT NOT NULL,
      publicado_em TEXT,
      FOREIGN KEY(dataset_id,sha256) REFERENCES
        nivon_snapshots(dataset_id,sha256)
    );
    CREATE TABLE IF NOT EXISTS zarc_linhas (
      sha256 TEXT NOT NULL REFERENCES zarc_edicoes(sha256)
        DEFERRABLE INITIALLY DEFERRED,
      linha_fisica INTEGER NOT NULL CHECK(linha_fisica>0),
      chave_logica_sha TEXT NOT NULL,
      conteudo_sha TEXT NOT NULL,
      municipio_ibge TEXT NOT NULL,
      municipio_sicor TEXT,
      cultura_original TEXT NOT NULL,
      cod_cultura TEXT NOT NULL,
      cod_ciclo TEXT NOT NULL,
      cod_solo TEXT NOT NULL,
      cod_clima TEXT NOT NULL,
      cod_manejo TEXT NOT NULL,
      cod_nm TEXT NOT NULL,
      portaria_original TEXT NOT NULL,
      dados_raw_json TEXT NOT NULL,
      PRIMARY KEY(sha256,linha_fisica)
    );
    CREATE INDEX IF NOT EXISTS idx_zarc_municipio_safra
      ON zarc_linhas(municipio_ibge,cultura_original,sha256);
    CREATE INDEX IF NOT EXISTS idx_zarc_logica
      ON zarc_linhas(chave_logica_sha,sha256);
    """)
    return db


def _hash_doc(o):
    return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,
                        separators=(",",":")).encode("utf-8")).hexdigest()


def _medir_arquivo(fh):
    if not hasattr(fh,"seek") or not hasattr(fh,"read"):
        raise ErroStagingZarc("ARQUIVO_DEVE_SER_SEEKABLE")
    try:
        fh.seek(0)
        h=hashlib.sha256()
        size=0
        while True:
            b=fh.read(128*1024)
            if not isinstance(b,bytes):
                raise ErroStagingZarc("ARQUIVO_PRECISA_SER_BINARIO")
            if not b:
                break
            size+=len(b)
            if size>MAX_DOWNLOAD:
                raise ErroStagingZarc("ARQUIVO_EXCEDE_TETO_ISOLADO")
            h.update(b)
        if size==0:
            raise ErroStagingZarc("ARQUIVO_VAZIO")
        fh.seek(0)
        return h.hexdigest(),size
    except (OSError,ValueError) as exc:
        raise ErroStagingZarc("ARQUIVO_SEM_ACESSO_SEGURO") from exc


def _linhas_csv(fh,max_linhas):
    """Retorna (linha física, raw row) sem inferir granularidade."""
    fh.seek(0)
    wrapper=io.TextIOWrapper(fh,encoding="utf-8-sig",newline="",errors="strict")
    try:
        leitor=csv.DictReader(wrapper,delimiter=";",restkey="_EXTRA",restval=None)
        if leitor.fieldnames != list(COLUNAS):
            raise ErroStagingZarc("SCHEMA_ZARC_DIVERGENTE")
        for numero,row in enumerate(leitor,start=1):
            if numero>max_linhas:
                raise ErroStagingZarc("MAX_LINHAS_EXCEDIDO")
            if ("_EXTRA" in row or len(row)!=len(COLUNAS)
                    or any(not isinstance(v,str) or len(v)>LIMITE_CELULA
                           for v in row.values())):
                raise ErroStagingZarc("LINHA_CSV_INVALIDA")
            yield numero,row
    except (UnicodeError,csv.Error) as exc:
        raise ErroStagingZarc("DECODIFICACAO_CSV_INVALIDA") from exc
    finally:
        wrapper.detach()


def _identificar_mt(row):
    if row["UF"].strip()!="MT":
        return None
    try:
        meta=interpretar_metadados_linha(row)
    except ErroDicionarioZarc as exc:
        raise ErroStagingZarc("DICIONARIO_MT_INVALIDO") from exc
    if (row["SafraIni"].strip(),row["SafraFin"].strip())!=("2026","2027"):
        raise ErroStagingZarc("SAFRA_MT_INCORRETA")
    if not row["Nome_cultura"].strip() or not row["Portaria"].strip():
        raise ErroStagingZarc("IDENTIDADE_MT_INCOMPLETA")
    return meta


def _registro(row,numero,sha,meta):
    # Comparação de edições: chave lógica é um CANDIDATO, não impõe UNIQUE.
    # Inclui TODOS os campos não decendiais, mesmo que uma dimensão difira.
    atributos={campo:row[campo] for campo in FIXOS}
    conteudo={campo:row[campo] for campo in COLUNAS}
    return (
        sha,numero,_hash_doc(atributos),_hash_doc(conteudo),
        meta["municipio_ibge"],meta["municipio_sicor"],
        row["Nome_cultura"],row["Cod_Cultura"],row["Cod_Ciclo"],
        row["Cod_Solo"],row["Cod_Clima"],row["Cod_Outros_Manejos"],
        row["Cod_NM"],row["Portaria"],
        json.dumps(conteudo,ensure_ascii=False,separators=(",",":")),
    )


def importar_zarc_local(db: Connection,catalogo: dict,arquivo, *,
                        coletado_em: str,origem="SINTETICO",
                        autorizacoes=frozenset(),evidencia_direitos=None,
                        publicacao=None,max_linhas=MAX_LINHAS):
    """Ingestão atômica, local, NÃO agendada; reais exigem gates do ledger.

    A função não abre rede e não envia dados para nuvem. Arquivos reais NÃO
    podem ser gravados enquanto enabled/collection_authorized forem false.
    Uso com fixtures SINTETICAS para construir/testar armazenamento.
    """
    if origem not in ("SINTETICO","REAL_AUTORIZADO"):
        raise ErroStagingZarc("ORIGEM_INVALIDA")
    if type(max_linhas) is not int or not 1<=max_linhas<=MAX_LINHAS:
        raise ErroStagingZarc("LIMITE_LINHAS_INVALIDO")
    if not isinstance(db,Connection):
        raise ErroStagingZarc("SQLITE_LOCAL_NECESSARIO")
    coleta=_utc(coletado_em)
    sha,size=_medir_arquivo(arquivo)
    contador=0
    mt=0
    municipios=set()
    em_batch=[]
    with savepoint_atomico(db):
        registro=registrar_snapshot(
            db,catalogo,dataset_id=DATASET,sha256=sha,tamanho=size,
            mime="text/csv",schema_versao=SCHEMA,coletado_em=coleta,
            competencia="2026/2027",referencia=None,publicacao=publicacao,
            tipo=origem,autorizacoes=autorizacoes,
            evidencia_direitos=evidencia_direitos)
        for numero,row in _linhas_csv(arquivo,max_linhas=max_linhas):
            contador+=1
            meta=_identificar_mt(row)
            if meta is None:
                continue
            mt+=1
            municipios.add(meta["municipio_ibge"])
            em_batch.append(_registro(row,numero,sha,meta))
            if len(em_batch)>=500:
                _inserir_lote(db,em_batch)
                em_batch.clear()
        if em_batch:
            _inserir_lote(db,em_batch)
        if contador==0 or mt==0:
            raise ErroStagingZarc("SEM_DADOS_MT_VALIDOS")
        if registro["nova_versao"]:
            db.execute("""INSERT INTO zarc_edicoes
              (sha256,dataset_id,competencia,fonte_url,tamanho_bytes,
               linhas_total,linhas_mt,municipios_mt,colunas_schema,publicado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
               (sha,DATASET,"2026/2027",URL,size,contador,mt,
                len(municipios),SCHEMA,publicacao))
        else:
            v=db.execute("""SELECT tamanho_bytes,linhas_total,linhas_mt,
                        municipios_mt,colunas_schema,publicado_em FROM zarc_edicoes
                        WHERE sha256=?""",(sha,)).fetchone()
            if (v is None or tuple(v)!=(size,contador,mt,len(municipios),
                                          SCHEMA,publicacao)):
                raise ErroStagingZarc("MESMO_SHA_METADADOS_CONFLITANTES")
        # Repetir arquivo idêntico não deve criar nova versão nem mais linhas.
        linha_db=db.execute("SELECT COUNT(*) FROM zarc_linhas WHERE sha256=?",
                           (sha,)).fetchone()[0]
        if linha_db!=mt:
            raise ErroStagingZarc("CONTAGEM_PERSISTIDA_DIVERGENTE")
    return {"dataset_id":DATASET,"sha256":sha,"bytes":size,
            "linhas_total":contador,"linhas_mt":mt,
            "municipios_mt":len(municipios),
            "nova_versao":registro["nova_versao"],
            "nova_coleta":registro["nova_coleta"],
            "origem":origem,"publicacao":publicacao,
            "publicavel":False,"homologado":False,
            "destino":"SQLITE_LOCAL_STAGE_SEM_NUVEM"}


def _inserir_lote(db,registros):
    # Evita trocar dados da mesma posição (se houve outro import conflituoso).
    db.executemany("""INSERT INTO zarc_linhas
        (sha256,linha_fisica,chave_logica_sha,conteudo_sha,
        municipio_ibge,municipio_sicor,cultura_original,cod_cultura,
        cod_ciclo,cod_solo,cod_clima,cod_manejo,cod_nm,portaria_original,
        dados_raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(sha256,linha_fisica) DO NOTHING""",registros)
    for r in registros:
        stored=db.execute("""SELECT conteudo_sha,chave_logica_sha
                              FROM zarc_linhas WHERE sha256=? AND linha_fisica=?""",
                          (r[0],r[1])).fetchone()
        if stored is None or tuple(stored)!=(r[3],r[2]):
            raise ErroStagingZarc("MESMA_POSICAO_CONTEUDO_DIVERGENTE")


def comparar_edicoes(db,sha_antigo,sha_novo):
    """Comparação estrutural sem interpretação de decêndios ou publicação.

    Duplicatas de chave candidata são AMBÍGUAS: não colapsar linhas.
    """
    for sha in (sha_antigo,sha_novo):
        if not isinstance(sha,str) or not SHA_RE.fullmatch(sha):
            raise ErroStagingZarc("SHA_INVALIDO")
        if db.execute("SELECT 1 FROM zarc_edicoes WHERE sha256=?",(sha,)).fetchone() is None:
            raise ErroStagingZarc("EDICAO_NAO_ENCONTRADA")
    def agrupar(sha):
        return {r["chave_logica_sha"]:(r["qtd"],r["conteudo_sha"])
                for r in db.execute("""SELECT chave_logica_sha,COUNT(*) qtd,
                 CASE WHEN COUNT(DISTINCT conteudo_sha)=1 THEN MIN(conteudo_sha)
                      ELSE NULL END conteudo_sha
                 FROM zarc_linhas WHERE sha256=? GROUP BY chave_logica_sha""",(sha,))}
    a,b=agrupar(sha_antigo),agrupar(sha_novo)
    ambas=set(a)&set(b)
    ambiguas=sum(1 for k in ambas if a[k][0]!=1 or b[k][0]!=1)
    alteradas=sum(1 for k in ambas if a[k][0]==b[k][0]==1 and
                  a[k][1]!=b[k][1])
    return {"sha_antigo":sha_antigo,"sha_novo":sha_novo,
            "chaves_adicionadas":len(set(b)-set(a)),
            "chaves_ausentes":len(set(a)-set(b)),
            "chaves_ambiguas":ambiguas,
            "chaves_com_decendios_ou_conteudo_alterados":alteradas,
            "natureza":"COMPARACAO_EXPLORATORIA_SEM_PUBLICACAO_VERIFICADA",
            "apto_backtest":False}
