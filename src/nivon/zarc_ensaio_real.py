"""Ensaio ponta-a-ponta com ARQUIVO REAL MAPA ZARC em runner descartável.

Duas consultas oficiais autorizadas: CKAN catálogo (licença CC-BY) + CSV.
Contratos de direitos: staging manual licenciado exclusivamente ZARC, versão
SHA completa e RAW local. NÃO acessa Neon nem altera catálogo ou agendas.
Arquivos locais são descartados após a prova, jamais publicar linhas.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener

from .catalogo_fontes import carregar_catalogo
from .fontes_abertas_lote import consultar
from .zarc_licenca_manual import emitir_licenca_manual
from .zarc_sinais_ckan import normalizar_sinal
from .zarc_raw_vault import guardar_raw_zarc, verificar_raw_zarc
from .zarc_staging import abrir_zarc_staging, importar_zarc_local
from .zarc_stream_mt import URL, MAX_DOWNLOAD, _NoRedirect

class ErroZarcEnsaio(ValueError):
    pass

def obter_csv_temporario(*,destino,executar=False,abridor=None):
    if executar is not True:
        raise PermissionError("DOWNLOAD_CSV_OFF")
    p=Path(destino)
    if p.exists() or not p.parent.is_dir():
        raise ErroZarcEnsaio("DESTINO_NAO_VAZIO")
    req=Request(URL,headers={
       "Accept":"text/csv,application/csv",
       "User-Agent":"NIVON/1.0 verificacao-publica-zarc-noncommercial",
       "Accept-Encoding":"identity",
    })
    op=abridor if abridor is not None else build_opener(_NoRedirect())
    h=hashlib.sha256()
    n=0
    try:
        with op.open(req,timeout=120) as response:
            if int(response.status)!=200 or response.geturl()!=URL:
                raise ErroZarcEnsaio("HTTP_OU_REDIRECT_INVALIDO")
            mime=str(response.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
            if mime not in ("text/csv","text/plain","application/octet-stream","application/csv"):
                raise ErroZarcEnsaio("MIME_CSV_INCORRETO")
            announced=response.headers.get("Content-Length")
            if announced is not None:
                if not announced.isdecimal() or int(announced)>MAX_DOWNLOAD:
                    raise ErroZarcEnsaio("TAMANHO_DECLARADO_NAO_PERMITIDO")
            with p.open("xb") as out:
                os.chmod(p,0o600)
                while True:
                    chunk=response.read(256*1024)
                    if not isinstance(chunk,bytes):
                        raise ErroZarcEnsaio("RESPOSTA_NAO_BINARIA")
                    if not chunk:
                        break
                    n+=len(chunk)
                    if n>MAX_DOWNLOAD:
                        raise ErroZarcEnsaio("DOWNLOAD_EXCEDE_LIMITE")
                    h.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
        if not n:
            raise ErroZarcEnsaio("CSV_VAZIO")
        return {"bytes":n,"sha256":h.hexdigest(),"mime":mime}
    except BaseException:
        p.unlink(missing_ok=True)
        raise


def ensaiar_zarc_real(*,executar=False,abridor_csv=None,consultor_ckan=None,
                      instante=None):
    if executar is not True:
        raise PermissionError("ENSAIO_REAL_OFF")
    now=instante or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None:
        raise ErroZarcEnsaio("COLETA_SEM_TZ")
    provider=consultor_ckan or (lambda:consultar("MAPA_ZARC",executar=True))
    metadata=provider()
    sinal=normalizar_sinal(metadata)
    rights=emitir_licenca_manual(sinal,consentimento_manual=True)
    with tempfile.TemporaryDirectory(prefix="nivon-zarc-real-quarentena-") as tmp:
        root=Path(tmp)
        raw=root/"entrada.csv"
        original=obter_csv_temporario(destino=raw,executar=True,abridor=abridor_csv)
        vault=root/"vault_0700"
        vault.mkdir(mode=0o700)
        with abrir_zarc_staging(":memory:") as db:
            with raw.open("rb") as data:
                result=importar_zarc_local(db,carregar_catalogo(),data,
                    coletado_em=now.astimezone(timezone.utc).isoformat(),
                    origem="REAL_AUTORIZADO",
                    autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                    evidencia_direitos=rights.evidence_id,
                    licenca_manual=rights)
            if result["sha256"]!=original["sha256"]:
                raise ErroZarcEnsaio("SHA_CSV_STAGE_NAO_CONFERE")
            with raw.open("rb") as data:
                vault_info=guardar_raw_zarc(db=db,arquivo=data,raiz=vault)
            integrity=verificar_raw_zarc(db=db,raiz=vault,sha256=original["sha256"])
            if (integrity["bytes"]!=original["bytes"]
                    or integrity["linhas_mt_ledger"]!=result["linhas_mt"]
                    or vault_info["sha256"]!=result["sha256"]):
                raise ErroZarcEnsaio("RAW_LEDGER_DIVERGENTE")
            saved=db.execute("SELECT COUNT(*) FROM zarc_linhas").fetchone()[0]
            if saved!=result["linhas_mt"]:
                raise ErroZarcEnsaio("CONTAGEM_QUARENTENA_DIVERGENTE")
            rows_ledger=db.execute("""SELECT COUNT(*) FROM nivon_snapshots
                                  WHERE tipo='REAL_AUTORIZADO'""").fetchone()[0]
            if rows_ledger!=1:
                raise ErroZarcEnsaio("ORIGEM_REAL_NAO_REGISTRADA")
            foreign=db.execute("PRAGMA foreign_key_check").fetchall()
            qc=db.execute("PRAGMA integrity_check").fetchone()[0]
            if foreign or qc!="ok":
                raise ErroZarcEnsaio("STAGING_SQLITE_CORROMPIDO")
            return {
                "estado":"ENSAIO_REAL_CSV_COMPLETO_EM_QUARENTENA_LOCAL",
                "dataset_id":"ZARC_JANELAS",
                "sha256_integral_csv":original["sha256"],
                "tamanho_csv_bytes":original["bytes"],
                "linhas_brasil":result["linhas_total"],
                "linhas_mt":saved,
                "municipios_mt":result["municipios_mt"],
                "coletado_em":now.astimezone(timezone.utc).isoformat(),
                "evidencia_ckan_sha":sinal["metadata_fingerprint"],
                "licenca":"cc-by",
                "autor_credito":"MAPA / Zoneamento Agricola de Risco Climatico",
                "revisao_ckan":sinal["recurso_revision_id"],
                "chaves_estrangeiras":"OK",
                "sqlite_integrity_check":qc,
                "raw_e_ledger_verificados":True,
                "publicavel":False,
                "apto_backtest":False,
                "agendamento_ativado":False,
                "arquivos_temporarios_descartados_ao_final":True,
                "nuvem_remota_gravada":False,
            }
