"""IVO — adaptador opcional MLForecast para série mensal com evidência as-of.

O backend real roda somente por chamada explícita e com extra instalado.
Não faz download, ingestão, deploy, ajuste de LLM nem promoção operacional.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from math import isfinite

from .historico import Observacao
from .ivo_lab_temporal import ErroLab, _base, _snapshot, _mes, _corte, _avancar


def _default_backend(serie: list[tuple[str, float]], horizonte: int) -> float:
    """MLForecast + Ridge com características APENAS de lags conhecidos."""
    try:
        import pandas as pd
        from mlforecast import MLForecast
        from sklearn.linear_model import Ridge
    except ImportError as exc:
        raise RuntimeError("Backend opcional ausente: instale o extra ivo-ml explicitamente") from exc
    dataframe = pd.DataFrame({
        "unique_id": ["NIVON_IVO"] * len(serie),
        "ds": pd.to_datetime([p + "-01" for p, _ in serie]),
        "y": [float(v) for _, v in serie],
    })
    forecaster = MLForecast(
        models={"Ridge": Ridge(alpha=1.0)}, freq="MS",
        lags=[1, 2, 3, 12], num_threads=1,
    )
    forecaster.fit(dataframe, id_col="unique_id", time_col="ds", target_col="y")
    saida = forecaster.predict(horizonte)
    if len(saida) != horizonte or "Ridge" not in saida.columns:
        raise ErroLab("MLForecast devolveu formato ou horizonte inválido")
    return float(saida["Ridge"].iloc[-1])


def prever_mlforecast_asof(
    observacoes: list[Observacao], *, periodo_alvo: str, fonte: str,
    variavel: str, produto: str, regiao: str, unidade: str,
    dados_autorizados: bool = False, minimo_meses: int = 36,
    backend=None,
) -> dict:
    """Faz previsão supervisonada somente com dados capturados antes do alvo.

    Flag exige autorização contratual upstream; não é prova de direito.
    O backend injetável serve para testes offline, nunca substitui avaliação real.
    """
    if dados_autorizados is not True:
        raise PermissionError("Dados de treino sem autorização expressa validada a montante")
    if type(minimo_meses) is not int or not 36 <= minimo_meses <= 600:
        raise ErroLab("mínimo de meses deve estar entre 36 e 600")
    if backend is not None and not callable(backend):
        raise ErroLab("executor precisa ser callable")
    alvo = _mes(periodo_alvo)
    corte = _corte(alvo)
    registros = _base(
        observacoes, fonte=fonte, variavel=variavel, produto=produto,
        regiao=regiao, unidade=unidade,
    )
    snapshot = _snapshot(registros, corte)
    anteriores = {p: o for p, o in snapshot.items() if _mes(p) < alvo}
    if not anteriores:
        raise ErroLab("sem observações anteriores disponíveis")
    ultimo = max(_mes(p) for p in anteriores)
    horizonte = (alvo.year-ultimo.year)*12+alvo.month-ultimo.month
    if not 1 <= horizonte <= 3:
        raise ErroLab("última observação publicada está distante mais de três meses")
    meses = []
    inicio = _avancar(ultimo, -(minimo_meses-1))
    for i in range(minimo_meses):
        periodo = _avancar(inicio, i).strftime("%Y-%m")
        o = anteriores.get(periodo)
        if o is None:
            raise ErroLab("janela de treino contém mês sem observação publicada as-of")
        meses.append((periodo, float(o.valor), o.publicacao.isoformat(),
                      o.coleta.astimezone(timezone.utc).isoformat()))
    amostra = [(p,v) for p,v,_,_ in meses]
    origem_sazonal = anteriores.get(_avancar(alvo,-12).strftime("%Y-%m"))
    if origem_sazonal is None:
        raise ErroLab("baseline sazonal indisponível as-of")
    executor = backend or _default_backend
    valor = executor(amostra, horizonte)
    if isinstance(valor, bool) or not isinstance(valor,(float,int)) or not isfinite(valor) or valor < 0:
        raise ErroLab("previsão de ML não finita ou negativa")
    digest = sha256(repr((periodo_alvo, fonte, variavel, produto, regiao,
                          unidade, meses, horizonte)).encode("utf-8")).hexdigest()
    return {
        "estado": "CANDIDATO_ML_NAO_HOMOLOGADO",
        "modelo":"MLFORECAST_RIDGE_LAGS_1_2_3_12",
        "periodo":periodo_alvo, "fonte":fonte,
        "indicador":variavel,"produto":produto,"geografia":regiao,"unidade":unidade,
        "horizonte_meses_desde_ultima_observacao": horizonte,
        "emitida_em":corte.isoformat(), "observacao_final":ultimo.strftime("%Y-%m"),
        "treino_inicio":meses[0][0],"treino_fim":meses[-1][0],
        "treino_meses":len(meses),"hash_treino_asof":digest,
        "estimativa":float(valor),"baseline_sazonal":float(origem_sazonal.valor),
        "backend_de_teste_injetado":backend is not None,
        "direitos_confirmados_pelo_motor":False,
        "modelo_homologado":False,
        "aviso":"A flag de autorização exige verificação externa; dados e resultado não são homologados.",
    }
