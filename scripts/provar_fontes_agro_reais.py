"""Prova real e temporária das fontes agrícolas, sem GCS/BigQuery/Neon.

Usa os coletores versionados, confere as linhas persistidas no ledger efêmero,
registra somente contagens, datas e status (nunca preços ou RAW público).
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import tempfile
from datetime import datetime, date, timezone
from pathlib import Path
from nivon.agro_origem_gcp import FONTES, executar as coletar

DATASETS={
    "CEPEA_SOJA":"CEPEA_PRECOS_FISICOS",
    "CEPEA_MILHO":"CEPEA_PRECOS_FISICOS",
    "IMEA":"IMEA_PUBLICACOES_STAGING",
    "CONAB":"CONAB_SAFRAS_STAGING",
}
SHA=re.compile(r"^[0-9a-f]{64}$")


def conferir(fonte,retorno,banco,agora=None):
    """Verificação independente do recibo do coletor no SQLite somente leitura."""
    if fonte not in DATASETS or retorno.get("dataset")!=DATASETS[fonte]:
        raise ValueError("fonte/dataset divergentes")
    if retorno.get("estado")!="QUARANTINED":
        raise ValueError("prova sem promoção canônica exige QUARANTINED")
    lotes=(retorno["cadeias"] if fonte=="IMEA" else
           retorno["edicoes"] if fonte=="CONAB" else [retorno])
    ids=[item.get("snapshot_id") for item in lotes]
    quantidade=sum(item.get("quantidade",0) for item in lotes)
    if (not 1<=len(ids)<=20 or len(set(ids))!=len(ids)
            or any(not isinstance(i,str) or not SHA.fullmatch(i) for i in ids)
            or type(quantidade) is not int or quantidade<1):
        raise ValueError("IDs/quantidades invalidos")
    caminho=Path(banco)
    if caminho.is_symlink() or not caminho.is_file():
        raise ValueError("ledger temporário ausente")
    markers=",".join("?" for _ in ids)
    with sqlite3.connect(f"file:{caminho.resolve().as_posix()}?mode=ro",uri=True) as db:
        linhas=db.execute(
            "SELECT o.referencia,o.campos_json FROM observacoes o "
            "JOIN snapshots s USING(snapshot_id) WHERE o.dataset_id=? "
            "AND s.estado='QUARANTINED' AND o.snapshot_id IN ("+markers+")",
            [DATASETS[fonte],*ids]).fetchall()
        n_snapshots=db.execute(
            "SELECT COUNT(*) FROM snapshots WHERE dataset_id=? "
            "AND snapshot_id IN ("+markers+")",
            [DATASETS[fonte],*ids]).fetchone()[0]
    if len(linhas)!=quantidade or n_snapshots!=len(ids):
        raise ValueError("contagens das fontes nao conciliadas")
    if fonte in ("IMEA","CONAB"):
        for _,payload in linhas:
            campos=json.loads(payload)
            if (campos.get("data_referencia") is not None or
                campos.get("tipo_referencia")!="PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"):
                raise ValueError("data de referência inventada")
    ultima=max(ref for ref,_ in linhas)
    ref=date.fromisoformat(ultima)
    today=(agora or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    if ref>today:
        raise ValueError("data futura")
    return {"fonte":fonte,"estado":"COLETA_REAL_CONCILIADA_EM_RUNNER",
            "registros":len(linhas),"snapshots":len(ids),
            "ultima_data":ultima,"dias_desde_ultima_data":(today-ref).days,
            "tipo_data":("REFERENCIA_VERIFICADA" if fonte.startswith("CEPEA_")
                         else "PUBLICACAO_COM_REFERENCIA_AUSENTE"),
            "storage":"TEMPORARIO_APAGADO_AO_FINAL",
            "gcs_escritas":0,"bigquery_jobs":0,"neon_escritas":0,
            "valores_publicados":False,"producao_ativada":False}


def provar(fonte,cliente=None,agora=None):
    if fonte not in FONTES:
        raise ValueError("fonte invalida")
    with tempfile.TemporaryDirectory(prefix="nivon-prova-agro-") as tmp:
        pasta=Path(tmp)
        retorno=coletar(fonte=fonte,base=pasta,cliente=cliente,agora=agora,
                        homologacao_referencia=False)
        return conferir(fonte,retorno,pasta/"fontes_reais.sqlite",agora)


def main(argv=None):
    parser=argparse.ArgumentParser(description="NIVON prova agro sem escrita Cloud")
    parser.add_argument("--fonte",choices=FONTES,required=True)
    parser.add_argument("--executar",action="store_true")
    opts=parser.parse_args(argv)
    resultado=(provar(opts.fonte) if opts.executar else
               {"fonte":opts.fonte,"estado":"PLANO_SEM_REDE",
                "gcs_escritas":0,"bigquery_jobs":0})
    print(json.dumps(resultado,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
