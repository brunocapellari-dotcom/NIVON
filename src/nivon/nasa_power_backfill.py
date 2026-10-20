"""Backfill histórico NASA POWER por ano civil, sem HTTP.

Planejador deduplica consulta anual idêntica pelo hash da URL e verifica
cobertura local. Banco versionado é o cache: não se repete um download
para o mesmo ponto/período sem justificativa de nova revisão.
"""
from __future__ import annotations
import hashlib
from datetime import date
from .nasa_power_diario import planejar_power, ErroPower

class ErroBackfillPower(ValueError):
    pass

def planejar_backfill(*,latitude,longitude,desde,ate,
                     parametros=("PRECTOTCORR","T2M_MIN","T2M_MAX")):
    try:
        start=date.fromisoformat(desde);end=date.fromisoformat(ate)
    except (ValueError,TypeError) as exc:
        raise ErroBackfillPower("datas de backfill inválidas") from exc
    if start.year<1981 or end>date.today() or start>end:
        raise ErroBackfillPower("NASA POWER diário: histórico desde 1981 e até hoje")
    if end.year-start.year>60:
        raise ErroBackfillPower("horizonte de recuperação excessivo")
    jobs=[]
    for ano in range(start.year,end.year+1):
        left=max(start,date(ano,1,1))
        right=min(end,date(ano,12,31))
        try:
            p=planejar_power(latitude=latitude,longitude=longitude,
                inicio=left.isoformat(),fim=right.isoformat(),
                parametros=parametros)
        except ErroPower as exc:
            raise ErroBackfillPower("janela NASA inválida: "+str(ano)) from exc
        p["consulta_sha256"]=hashlib.sha256(p["url"].encode()).hexdigest()
        p["ordem_anual"]=len(jobs)+1
        p["estado"]="AGUARDA_CONSULTA_MANUAL_OU_CACHE"
        jobs.append(p)
    return {"dataset_id":"NASA_POWER_AG","anos_incluidos":len(jobs),
            "dias_planejados":sum(j["intervalo_dias"] for j in jobs),
            "planos":jobs,"executar":False,
            "aviso":"NASA limita frequência/consultas repetidas por célula; "
                     "não agendar todos os pontos municipais sem deduplicação geoespacial."}

def diagnosticar_cache_backfill(db,*,planejamento):
    if not isinstance(planejamento,dict) or planejamento.get("dataset_id")!="NASA_POWER_AG" or planejamento.get("executar") is not False:
        raise ErroBackfillPower("planejamento inválido")
    rows=[]
    planos=planejamento.get("planos")
    if not isinstance(planos,list) or not 1<=len(planos)<=61:
        raise ErroBackfillPower("janela de planejamento inválida")
    seen=set()
    for job in planos:
        sha=job.get("consulta_sha256")
        if not isinstance(sha,str) or len(sha)!=64 or sha in seen:
            raise ErroBackfillPower("SHA da consulta ausente/repetido")
        seen.add(sha)
        old=db.execute("""SELECT e.conteudo_sha256,e.publicado_utc,COUNT(v.parametro) AS n
            FROM grade_edicao e LEFT JOIN grade_valor v
            ON v.dataset_id=e.dataset_id AND v.consulta_sha256=e.consulta_sha256
            AND v.conteudo_sha256=e.conteudo_sha256
            WHERE e.dataset_id='NASA_POWER_AG' AND e.consulta_sha256=?
            GROUP BY e.conteudo_sha256,e.publicado_utc
            ORDER BY e.publicado_utc DESC LIMIT 1""",(sha,)).fetchone()
        expected=job["intervalo_dias"]*len(job["parametros"])
        if old is None:
            status="PENDENTE_CAPTURA"
        elif old["n"]!=expected:
            status="INCONSISTENCIA_COBERTURA"
        elif old["publicado_utc"] is None:
            status="CAPTURADO_PUBLICACAO_DESCONHECIDA"
        else:
            status="CAPTURADO_VERSIONADO"
        rows.append({"ordem":job["ordem_anual"],"inicio":job["inicio"],
                     "fim":job["fim"],"consulta_sha256":sha,
                     "esperados":expected,"armazenados":old["n"] if old else 0,
                     "estado":status})
    return {"datasets":1,"janelas":len(rows),"pendentes":sum(r["estado"]=="PENDENTE_CAPTURA" for r in rows),
            "capturadas":sum(r["estado"].startswith("CAPTURADO") for r in rows),
            "inconsistencias":sum(r["estado"]=="INCONSISTENCIA_COBERTURA" for r in rows),
            "janelas_detalhadas":rows,"coleta_automatica":False}
