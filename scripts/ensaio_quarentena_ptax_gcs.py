"""Ensaio ponta a ponta: quarentena PTAX → manifestos → objetos GCS offline.

A execução NÃO faz requisições, NÃO instala Google SDK, NÃO envia arquivos
e NÃO habilita fontes reais. Todo RAW OData deste script é sintético.
"""
from __future__ import annotations

from hashlib import sha256
import json
import sqlite3

from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_quarentena_coleta import (
    receber_amostra_ptax, listar_amostras_ptax, ErroQuarentenaPTAX,
)
from nivon.ptax_google_cloud import (
    preparar_objetos_gcs_ptax, enviar_objetos_gcs_ptax,
)

RAW=(b'{"value":[{"cotacaoCompra":5.10000,"cotacaoVenda":5.12000,'
     b'"dataHoraCotacao":"2026-10-20 13:03:00"}]}')
PLANO=planejar_consultas_ptax(
    moeda="USD", inicio="2026-10-20", fim="2026-10-20"
)[0]


def manifesto():
    return {
        "moeda":"USD","consulta_url":PLANO["url"],
        "coletado_em":"2026-10-20T18:00:00+00:00",
        "status_http":200,
        "cabecalhos_http":{
            "content-type":"application/json",
            "content-length":str(len(RAW)),
        },
        "raw_sha256":sha256(RAW).hexdigest(),
        "fonte_declarada":"BCB_PTAX",
    }


def executar():
    with sqlite3.connect(":memory:") as db:
        db.execute("PRAGMA foreign_keys=ON")
        first=receber_amostra_ptax(db, raw=RAW, manifesto=manifesto())
        assert first["nova_versao"] is True
        assert first["status"]=="AMOSTRA_EXTERNA_NAO_HOMOLOGADA"
        assert first["aprovado_para_ledger_operacional"] is False
        second=receber_amostra_ptax(db, raw=RAW, manifesto=manifesto())
        assert second["nova_versao"] is False
        index=listar_amostras_ptax(db)
        assert len(index)==1 and index[0]["evento_sha256"]==first["evento_sha256"]
        pacote=preparar_objetos_gcs_ptax(
            db,evento_sha256=first["evento_sha256"],
            bucket="nivon-testes-sem-upload-001",
        )
        assert pacote["status"]=="EXPORTACAO_GCS_PREPARADA_SEM_ENVIO"
        assert len(pacote["objetos"])==2
        assert all(sha256(x["bytes"]).hexdigest()==x["sha256"]
                   for x in pacote["objetos"])
        assert pacote["objetos"][0]["bytes"]==RAW
        assert pacote["upload_executado"] is False
        assert pacote["publicavel"] is False
        try:
            enviar_objetos_gcs_ptax(pacote)
        except PermissionError:
            bloqueio_upload=True
        else:
            raise AssertionError("upload sem autorização foi aceito")
        metadata=dict(manifesto())
        metadata["raw_sha256"]="f"*64
        try:
            receber_amostra_ptax(db,raw=RAW,manifesto=metadata)
        except ErroQuarentenaPTAX:
            digest_bloqueado=True
        else:
            raise AssertionError("digest falso não foi bloqueado")
        try:
            db.execute(
                "UPDATE nivon_ptax_quarentena_raw SET raw=? WHERE raw_sha256=?",
                (b"ADULTERADO",first["raw_sha256"])
            )
        except sqlite3.DatabaseError:
            append_only_ok=True
        else:
            raise AssertionError("quarentena aceita UPDATE")
        assert len(listar_amostras_ptax(db))==1
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name='nivon_snapshots' AND type='table'"
        ).fetchone()[0]==0
        return {
            "status":"QUARENTENA_PTAX_GCS_OFFLINE_TESTADA",
            "etapas":[
                "manifesto_de_captura_declarado",
                "validacao_sha_do_raw",
                "persistencia_quarentena_sqlite",
                "idempotencia_evento",
                "consulta_revalidada_de_amostras",
                "preparacao_objetos_raw_e_manifesto_gcs",
                "conferencia_sha_de_cada_objeto",
                "bloqueio_upload_sem_autorizacao",
                "rejeicao_digesto_falso",
                "protecao_append_only",
                "sem_promocao_ao_ledger_operacional",
            ],
            "eventos_quarentena":len(index),
            "objetos_preparados":len(pacote["objetos"]),
            "total_bytes":pacote["total_bytes"],
            "upload_gcs_realizado":False,
            "fonte_real_coletada":False,
            "autenticidade_externa_comprovada":False,
            "publicavel":False,
        }


if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,sort_keys=True))
