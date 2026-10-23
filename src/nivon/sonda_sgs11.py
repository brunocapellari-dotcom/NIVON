"""Sonda REAL e somente leitura SGS11 do BCB (sem Google Cloud ou persistência).

Usa a implementação de produção, mas NÃO grava RAW, cria jobs nem sinaliza
disponibilidade GCP. Imprime evidência de coleta pública para auditoria.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from .sgs11_gcp import DATASET, coletar_http, normalizar

def validar_sonda(*, agora=None, abridor=None, max_atraso_dias=14):
    instante=agora or datetime.now(timezone.utc)
    if not isinstance(instante,datetime) or instante.utcoffset() is None:
        raise ValueError("sonda exige relógio com timezone")
    if not isinstance(max_atraso_dias,int) or not 1 <= max_atraso_dias <= 31:
        raise ValueError("janela de atraso inválida")
    bruto=coletar_http(abridor=abridor)
    obs=normalizar(bruto,coletado_em=instante)
    ultima=obs[-1]
    from datetime import date
    idade=(instante.date()-date.fromisoformat(ultima["referencia"])).days
    return {
        "estado":"BCB_SGS11_ORIGEM_REAL_VERIFICADA" if idade<=max_atraso_dias
                 else "FONTE_RESPONDE_MAS_ATRASADA",
        "dataset_id":DATASET,
        "referencia":ultima["referencia"],"idade_dias":idade,
        "sha256_http":hashlib.sha256(bruto).hexdigest(),
        "quantidade":len(obs),"natureza":"INFORMADO",
        "unidade":"PERCENTUAL_AO_DIA","valor":ultima["valor"],
        "origem":"BCB_SGS11_ENDPOINT_OFICIAL",
        "gcs_executado":False,"bigquery_executado":False,
        "publicacao_comprovada":False,
        "fonte_nao_e_meta_selic_anual":True,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description="Verificar BCB SGS11 com HTTP real, sem armazenamento")
    p.add_argument("--executar",action="store_true")
    p.add_argument("--atraso-maximo-dias",type=int,default=14)
    args=p.parse_args(argv)
    if args.executar:
        result=validar_sonda(max_atraso_dias=args.atraso_maximo_dias)
    else:
        result={"estado":"PLANO_SEM_REDE","dataset_id":DATASET,"http_executado":False}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["estado"] not in ("FONTE_RESPONDE_MAS_ATRASADA",) else 2

if __name__=="__main__":
    raise SystemExit(main())
