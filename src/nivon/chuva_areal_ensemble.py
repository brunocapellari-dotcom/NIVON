"""Convert gridded numerical weather forecast members into BAsin-AREA rainfall.

GIS weights are EXTERNAL intersection fractions of a declared catchment.
They must be non-negative and sum to one; no implicit re-normalisation,
interpolation or missing-cell imputation is permitted. Only genuine
forecast products can supply the downstream forecast ensemble.
"""
from __future__ import annotations

import re
from datetime import datetime,timezone
from math import fsum,isfinite

class ErroChuvaAreal(ValueError):
    pass

_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _time(value,label):
    if not isinstance(value,str) or "T" not in value:
        raise ErroChuvaAreal(label+": timestamp com fuso obrigatório")
    try: d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise ErroChuvaAreal(label+": timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroChuvaAreal(label+": fuso obrigatório")
    return d.astimezone(timezone.utc)


def _n(v,label,lo=None,hi=None):
    if type(v) not in (float,int) or not isfinite(v):
        raise ErroChuvaAreal(label+": número finito obrigatório")
    x=float(v)
    if lo is not None and x<lo or hi is not None and x>hi:
        raise ErroChuvaAreal(label+": valor fora da faixa")
    return x


def agregar_ensemble_chuva_areal(
    *, bacia_id, area_bacia_km2, pesos_celulas, pesos_sha256,
    metodo_geoespacial, produto_previsao, versao_previsao,
    emitido_em, dados_publicados_ate, passo_horas, membros_grade,
):
    """Output directly fits ensemble_hidrologico_bacia.cenario_ensemble_bacia.

    Inputs are depths in millimetres PER INTERVAL, not precipitation rates
    in mm/hour. Satellite analysis/reanalysis is not an NWP forecast.
    Cell geometry and weights must be independently verified upstream.
    """
    for label,v in (("bacia",bacia_id),("interseção GIS",metodo_geoespacial),
                    ("produto NWP",produto_previsao),("versão NWP",versao_previsao)):
        if not isinstance(v,str) or not 8<=len(v.strip())<=240:
            raise ErroChuvaAreal(label+": informação de proveniência obrigatória")
    if not isinstance(pesos_sha256,str) or not _SHA.fullmatch(pesos_sha256):
        raise ErroChuvaAreal("hash dos pesos GIS ausente")
    area=_n(area_bacia_km2,"área bacia km²",0.000001,10_000_000)
    step=_n(passo_horas,"passo_horas",1/60,24)
    issued=_time(emitido_em,"emissão")
    latest=_time(dados_publicados_ate,"dados disponíveis")
    if latest>issued:
        raise ErroChuvaAreal("previsão usa dados publicados no futuro")
    if not isinstance(pesos_celulas,(list,tuple)) or not 2<=len(pesos_celulas)<=100:
        raise ErroChuvaAreal("pesos de 2 a 100 células exigidos")
    weights={};ids=set()
    for row in pesos_celulas:
        if not isinstance(row,dict) or set(row)!={"celula_id","peso_area"}:
            raise ErroChuvaAreal("pesos fora do contrato")
        cell=row["celula_id"]
        if not isinstance(cell,str) or not 1<=len(cell)<=100 or cell in ids:
            raise ErroChuvaAreal("célula repetida/não identificada")
        ids.add(cell)
        w=_n(row["peso_area"],"fração da bacia",0,1)
        if w<=0:
            raise ErroChuvaAreal("interseção com área nula deve ser descartada no GIS")
        weights[cell]=w
    if abs(fsum(weights.values())-1)>1e-8:
        raise ErroChuvaAreal("pesos GIS não cobrem exatamente a bacia")
    if not isinstance(membros_grade,(list,tuple)) or not 3<=len(membros_grade)<=100:
        raise ErroChuvaAreal("3 a 100 membros NWP exigidos")
    ref_times=None;memberids=set();out=[]
    if len(membros_grade)*len(weights)>25000:
        raise ErroChuvaAreal("produto espacial muito grande para o motor leve")
    for member in membros_grade:
        if not isinstance(member,dict) or set(member)!={"membro_id","celulas"}:
            raise ErroChuvaAreal("contrato do membro de grade inválido")
        mid=member["membro_id"]
        if not isinstance(mid,str) or not 1<=len(mid)<=80 or mid in memberids:
            raise ErroChuvaAreal("membro duplicado/inválido")
        memberids.add(mid)
        cells=member["celulas"]
        if not isinstance(cells,(list,tuple)) or len(cells)!=len(weights):
            raise ErroChuvaAreal("faltam células da bacia")
        per_cell={};local_times=None
        for cell in cells:
            if not isinstance(cell,dict) or set(cell)!={"celula_id","serie"}:
                raise ErroChuvaAreal("célula fora do schema")
            cid=cell["celula_id"]
            if cid not in weights or cid in per_cell:
                raise ErroChuvaAreal("célula desconhecida/duplicada")
            series=cell["serie"]
            if not isinstance(series,(list,tuple)) or not 2<=len(series)<=1000:
                raise ErroChuvaAreal("série por célula incompleta/excessiva")
            if len(membros_grade)*len(weights)*len(series)>250000:
                raise ErroChuvaAreal("volume de registros fora do orçamento")
            values=[];times=[]
            for point in series:
                if not isinstance(point,dict) or set(point)!={"data_hora","chuva_mm"}:
                    raise ErroChuvaAreal("valor horário fora do contrato")
                t=_time(point["data_hora"],"passo de chuva")
                if t<=issued:
                    raise ErroChuvaAreal("série não representa previsão futura")
                val=_n(point["chuva_mm"],"chuva de intervalo em mm",0,2000)
                if times:
                    dt=(t-times[-1]).total_seconds()/3600
                    if abs(dt-step)>1e-8:
                        raise ErroChuvaAreal("intervalos com lacuna ou duplicados")
                times.append(t);values.append(val)
            tup=tuple(times)
            if local_times is None:local_times=tup
            elif tup!=local_times:
                raise ErroChuvaAreal("células com períodos diferentes")
            per_cell[cid]=values
        if set(per_cell)!=set(weights):
            raise ErroChuvaAreal("cobertura GIS insuficiente")
        if ref_times is None:ref_times=local_times
        elif ref_times!=local_times:
            raise ErroChuvaAreal("membros com períodos diferentes")
        rain=[]
        for i,t in enumerate(ref_times):
            depth=fsum(weights[cid]*per_cell[cid][i] for cid in sorted(weights))
            rain.append({"data_hora":t.isoformat(),"chuva_area_mm":depth})
        out.append({"membro_id":mid,"chuva_intervalos":rain})
    return {
        "bacia_id":bacia_id,"area_bacia_km2":area,
        "pesos_sha256":pesos_sha256,"metodo_geoespacial":metodo_geoespacial,
        "produto_previsao":produto_previsao,"versao_previsao":versao_previsao,
        "emitido_em_utc":issued.isoformat(),"dados_publicados_ate_utc":latest.isoformat(),
        "passo_horas":step,"membros":len(out),"celulas_por_membro":len(weights),
        "membros_chuva":out,
        "natureza":"PREVISAO_GRADE_CONDICIONAL_AGREGADA_POR_AREA",
        "intersecao_gis_auditada_externamente":False,
        "calibracao_validada":False,
        "limite":"Pesos GIS e cobertura espacial são declarações fornecidas por "
                 "pipeline externo; requer validação de CRS, interseção, "
                 "altitude, fonte NWP/vintage e desempenho no território. "
                 "Usar apenas modelos de previsão, não observações CHIRPS/IMERG "
                 "indevidamente reclassificadas como chuva futura.",
    }
