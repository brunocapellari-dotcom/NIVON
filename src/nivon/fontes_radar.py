"""Radar puro de metadados existentes: não coleta, consulta BQ ou promove dados."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from .maritime.maritime_source_health import assess_source_health

FONTES=("ANTT","CEPEA","IMEA","CONAB")


def _tempo(value, *, dia=False):
    if not isinstance(value,str):raise ValueError("TEMPO_AUSENTE")
    if dia and re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):value+="T00:00:00+00:00"
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.utcoffset() is None:raise ValueError("FUSO_AUSENTE")
    return parsed.astimezone(timezone.utc)


def radar(eventos, politicas, *, agora):
    """Estados operacionais não concedem homologação ou redistribuição."""
    now=_tempo(agora)
    if not isinstance(eventos,list) or len(eventos)>10000 or not isinstance(politicas,dict):
        raise ValueError("ENTRADA_INVALIDA")
    if any(not isinstance(x,dict) or x.get("fonte") not in FONTES for x in eventos):
        raise ValueError("FONTE_FORA_DO_CATALOGO")
    result=[]
    for fonte in FONTES:
        row={"fonte":fonte,"estado":"unavailable","causa":"SEM_METADADOS",
             "data_referencia":None,"data_publicacao":None,"data_coleta":None,
             "competencia":None,"eventos_distintos":None,"revisao_detectada":False,
             "promocao_autorizada":False}
        items=[x for x in eventos if x["fonte"]==fonte]
        policy=politicas.get(fonte,{})
        if not items:
            result.append(row);continue
        try:
            if not isinstance(policy,dict):raise ValueError("POLITICA_INVALIDA")
            distinct={}
            for item in items:
                key=item.get("evento_id")
                if not isinstance(key,str) or not 1<=len(key)<=100:raise ValueError("ID_INVALIDO")
                if key in distinct and distinct[key]!=item:raise ValueError("EVENTO_DUPLICADO_DIVERGENTE")
                distinct[key]=item
            items=list(distinct.values())
            for item in items:
                coleta=_tempo(item.get("data_coleta"))
                if coleta>now:raise ValueError("COLETA_FUTURA")
            last=max(items,key=lambda x:_tempo(x["data_coleta"]))
            row["data_coleta"]=last["data_coleta"]
            row["eventos_distintos"]=len(items)
            if policy.get("homologada") is not True or any(x.get("estado")=="QUARANTINED" for x in items):
                row.update(estado="quarantined",causa="FONTE_OU_EVENTO_NAO_HOMOLOGADO")
            elif last.get("estado")=="UNAVAILABLE":
                row["causa"]="FALHA_DA_FONTE"
            else:
                if any(x.get("estado") not in ("NORMALIZED","UNAVAILABLE") for x in items):raise ValueError("ESTADO_NAO_VALIDADO")
                items=[x for x in items if x.get("estado")=="NORMALIZED"]
                for item in items:
                    ref=_tempo(item.get("data_referencia"),dia=True)
                    collected=_tempo(item["data_coleta"])
                    if ref>collected:raise ValueError("REFERENCIA_APOS_COLETA")
                    comp=item.get("competencia")
                    if comp is not None and comp!=ref.strftime("%Y-%m"):raise ValueError("COMPETENCIA_DIVERGENTE")
                    if item.get("data_publicacao") is not None:
                        pub=_tempo(item["data_publicacao"],dia=True)
                        if pub>collected:raise ValueError("PUBLICACAO_APOS_COLETA")
                latest=max(items,key=lambda x:(_tempo(x["data_referencia"],dia=True),_tempo(x["data_coleta"])))
                row.update({key:latest.get(key) for key in ("data_referencia","data_publicacao","competencia")})
                row["ultima_coleta_fonte"]=last["data_coleta"]
                row["data_coleta"]=latest["data_coleta"]
                limit=float(policy["limite_defasagem_dias"])
                interval=float(policy["intervalo_coleta_minutos"])
                if not math.isfinite(limit) or limit<=0 or not math.isfinite(interval) or interval<=0:
                    raise ValueError("POLITICA_INVALIDA")
                health=assess_source_health(source_id=fonte,now=now,expected_interval_minutes=interval,
                    last_success_at=last["data_coleta"],last_record_at=_tempo(latest["data_referencia"],dia=True))
                row["transport_status"]=health.transport_status
                lag=(now-_tempo(latest["data_referencia"],dia=True)).total_seconds()>limit*86400
                if health.transport_status!="HEALTHY":row.update(estado="unavailable",causa="COLETOR_SEM_ATUALIZACAO")
                else:row.update(estado="lagged" if lag else "fresh",causa="REFERENCIA_DEFASADA" if lag else "METADADOS_NA_JANELA")
                refs=[x["data_referencia"] for x in items]
                row["revisao_detectada"]=len(refs)!=len(set(refs))
        except (ValueError,TypeError,KeyError,OverflowError):
            row.update(estado="unavailable",causa="METADADOS_OU_POLITICA_INVALIDOS")
        result.append(row)
    return {"schema":"nivon.fontes.radar.v1","avaliado_em":now.isoformat(),
            "fontes":result,"consultas_sql":0,"coletas":0,"go_live":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada",required=True,type=Path)
    parser.add_argument("--agora",required=True)
    args=parser.parse_args(argv)
    try:
        if args.entrada.is_symlink() or not 0<args.entrada.stat().st_size<=2_000_000:raise ValueError()
        data=json.loads(args.entrada.read_text())
        result=radar(data["eventos"],data["politicas"],agora=args.agora)
    except (OSError,ValueError,KeyError,TypeError):
        print(json.dumps({"estado":"ENTRADA_INVALIDA","go_live":False}));return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":raise SystemExit(main())
