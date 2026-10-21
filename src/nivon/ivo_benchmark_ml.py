"""IVO: benchmark walk-forward de candidato ML versus baseline sazonal.

Reexecuta o ajuste a cada corte. Não usa a observação do mês alvo antes
da previsão. Nenhum backend é carregado quando não chamado explicitamente.
"""
from __future__ import annotations

from datetime import date,datetime,timedelta,timezone
from math import isfinite

from .ivo_lab_temporal import ErroLab, _base, _mes, _avancar, _snapshot
from .ivo_mlforecast_adapter import prever_mlforecast_asof


def _dt(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroLab("corte de avaliação exige datetime com timezone")
    return v.astimezone(timezone.utc)


def benchmark_ml_asof(
    observacoes, *, fonte, variavel, produto, regiao, unidade,
    inicio, fim, corte_avaliacao:datetime, dados_autorizados:bool=False,
    minimo_meses:int=36, backend=None,
)->dict:
    """Avalia 3–24 competências mensais e baseline para idêntico horizonte.

    O campo real só é acessado depois de obter a previsão no instante as-of.
    """
    if dados_autorizados is not True:
        raise PermissionError("treino sem autorização expressa de dados")
    first,last=_mes(inicio),_mes(fim)
    dif=(last.year-first.year)*12+last.month-first.month
    if not 2<=dif<=23:
        raise ErroLab("benchmark exige 3 a 24 meses")
    corte=_dt(corte_avaliacao)
    registros=_base(observacoes,fonte=fonte,variavel=variavel,
                    produto=produto,regiao=regiao,unidade=unidade)
    # Apenas rótulos já publicados até o instante declarado de avaliação.
    conhecidos=_snapshot(registros,corte)
    resultados=[]
    ignorados=[]
    for i in range(dif+1):
        periodo=_avancar(first,i).strftime("%Y-%m")
        try:
            pred=prever_mlforecast_asof(
                registros,periodo_alvo=periodo,fonte=fonte,
                variavel=variavel,produto=produto,regiao=regiao,unidade=unidade,
                dados_autorizados=True,minimo_meses=minimo_meses,backend=backend,
            )
        except ErroLab as exc:
            ignorados.append({"periodo":periodo,"motivo":str(exc)})
            continue
        observado=conhecidos.get(periodo)
        if observado is None or observado.publicacao>corte.date() or observado.coleta>corte:
            ignorados.append({"periodo":periodo,"motivo":"resultado ainda indisponível no corte"})
            continue
        p=pred["estimativa"]
        b=pred["baseline_sazonal"]
        y=float(observado.valor)
        resultados.append({
            "periodo":periodo,"previsao":p,"baseline_sazonal":b,"observado":y,
            "erro_modelo":abs(p-y),"erro_baseline":abs(b-y),
            "hash_treino_asof":pred["hash_treino_asof"],
            "emitida_em":pred["emitida_em"],
            "publicada_em":observado.publicacao.isoformat(),
            "coletada_em":observado.coleta.astimezone(timezone.utc).isoformat(),
            "horizonte_meses_desde_ultima_observacao":pred["horizonte_meses_desde_ultima_observacao"],
        })
    n=len(resultados)
    e=sum(r["erro_modelo"] for r in resultados)
    b=sum(r["erro_baseline"] for r in resultados)
    obs_sum=sum(r["observado"] for r in resultados)
    return {
        "estado":"BENCHMARK_ML_ASOF_NAO_HOMOLOGADO",
        "identidade":{"fonte":fonte,"variavel":variavel,"produto":produto,
                       "regiao":regiao,"unidade":unidade},
        "corte_avaliacao":corte.isoformat(),
        "folds_validos":n,"folds_ignorados":ignorados,"folds":resultados,
        "mae_modelo":e/n if n else None,
        "mae_baseline":b/n if n else None,
        "wape_modelo":e/obs_sum if obs_sum else None,
        "melhoria_relativa":(b-e)/b if b else None,
        "superou_baseline":(e<b) if n else None,
        "modelo_homologado":False,"promocao_automatica":False,
        "aviso":"Resultado retrospectivo, sem garantia de acurácia futura ou direitos verificados neste módulo.",
    }
