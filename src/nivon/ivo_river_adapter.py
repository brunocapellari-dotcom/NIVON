"""IVO River: replay prequential sem look-ahead de rótulos publicados.

River é importado sob demanda. O adapter só testa candidatos, nunca persiste
modelo, treina LLM, altera parâmetros de produção ou aciona redes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite


class ErroOnline(ValueError):
    pass


def _dt(v, nome):
    if not isinstance(v,str):
        raise ErroOnline(f"{nome}: instante obrigatório")
    try:
        d=datetime.fromisoformat(v)
    except ValueError as exc:
        raise ErroOnline(f"{nome}: data inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroOnline(f"{nome}: timezone obrigatório")
    return d.astimezone(timezone.utc)


def _num(v,nome):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v):
        raise ErroOnline(f"{nome}: finito obrigatório")
    return float(v)


def _river_factory():
    try:
        from river import linear_model, optim, preprocessing
    except ImportError as exc:
        raise RuntimeError("River opcional ausente: instale ivo-online explicitamente") from exc
    return preprocessing.StandardScaler() | linear_model.LinearRegression(optimizer=optim.SGD(0.01))


def replay_river(
    avaliacao: dict, *, factory=None, max_linhas: int=2000
) -> dict:
    """Avalia atualização de correção residual quando o resultado ficou público.

    Entrada requer avaliação do ledger homogênea, com fonte PRIMEIRA_PUBLICACAO.
    Não usar este replay para alegar desempenho LIVE antes da implantação.
    """
    if not isinstance(avaliacao,dict) or avaliacao.get("status")!="AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA":
        raise ErroOnline("avaliação canônica inválida")
    if avaliacao.get("agregacao_comparavel") is not True or avaliacao.get("verdade")!="PRIMEIRA_PUBLICACAO":
        raise ErroOnline("modelo/horizonte/vintage incompatível")
    if avaliacao.get("modo") not in ("LIVE","BACKTEST"):
        raise ErroOnline("modo desconhecido")
    if type(max_linhas) is not int or not 2 <= max_linhas <= 5000:
        raise ErroOnline("limite de linhas inválido")
    rows=avaliacao.get("avaliacoes")
    if not isinstance(rows,list) or len(rows)<2 or len(rows)>max_linhas:
        raise ErroOnline("mínimo de duas previsões e limite obrigatório")
    esperado=None
    normalized=[]
    ids=set()
    for p in rows:
        if not isinstance(p,dict):
            raise ErroOnline("fold deve ser dicionário")
        chave=(p.get("modelo_id"),p.get("versao_modelo"),p.get("indicador"),
               p.get("geografia"),p.get("unidade"),p.get("fonte_verdade"),
               p.get("horizonte_meses"))
        if any(x is None or isinstance(x,str) and not x for x in chave):
            raise ErroOnline("dimensões canônicas ausentes")
        if esperado is None:
            esperado=chave
        elif esperado!=chave:
            raise ErroOnline("não misturar séries ou horizontes")
        pid=p.get("previsao_id")
        if not isinstance(pid,str) or not pid or pid in ids:
            raise ErroOnline("previsões duplicadas")
        ids.add(pid)
        issuance=_dt(p.get("previsao_emitida_em"),"emissão")
        registered=_dt(p.get("previsao_registrada_em"),"registro previsão")
        publication=_dt(p.get("vintage_publicada_em"),"publicação observação")
        obs_registered=_dt(p.get("observacao_registrada_em"),"registro observado")
        if not issuance <= registered < publication <= obs_registered:
            raise ErroOnline("ordem temporal inconsistente")
        yhat=_num(p.get("previsto"),"previsão")
        true=_num(p.get("observado"),"observado")
        baseline=_num(p.get("baseline"),"baseline")
        if min(yhat,true,baseline)<0:
            raise ErroOnline("grandeza negativa não aceita")
        normalized.append({
            "id":pid,"issuance":issuance,"publication":publication,
            "obs_registered":obs_registered,"pred":yhat,"true":true,
            "baseline":baseline,"periodo":p.get("periodo"),
        })
    normalized.sort(key=lambda x:(x["issuance"],x["id"]))
    # Folds retroativos são avaliacões offline; nunca usar para ativar agente.
    # A linha atual não pode ser usada para aprender antes da própria previsão.
    if factory is not None and not callable(factory):
        raise ErroOnline("fábrica de modelos inválida")
    model=(factory or _river_factory)()
    if not callable(getattr(model,"predict_one",None)) or not callable(getattr(model,"learn_one",None)):
        raise ErroOnline("backend online sem interface River predict_one/learn_one")
    pendentes=[]
    saidas=[]
    treinadas=set()
    for row in normalized:
        prontos=sorted(
            (v for v in pendentes if v["obs_registered"] < row["issuance"]),
            key=lambda x:(x["obs_registered"],x["id"]))
        for anterior in prontos:
            if anterior["id"] in treinadas:
                raise ErroOnline("rótulo aprendido duas vezes")
            model.learn_one(anterior["x"],anterior["residual"])
            treinadas.add(anterior["id"])
        pendentes=[v for v in pendentes if v["id"] not in treinadas]
        x={
            "proporcao_previsto_baseline":row["pred"]/max(1.,row["baseline"]),
            "diferenca_normalizada":(row["pred"]-row["baseline"])/max(1.,row["baseline"]),
        }
        correcao=model.predict_one(x)
        if correcao is None:
            correcao=0.
        correcao=_num(correcao,"correção incremental")
        # Nunca produzir previsão negativa; desvio bruto permanece auditável.
        corrigido=max(0.,row["pred"]+correcao)
        if not isfinite(corrigido):
            raise ErroOnline("previsão corrigida inválida")
        saidas.append({
            "previsao_id":row["id"],"periodo":row["periodo"],
            "emitida_em":row["issuance"].isoformat(),
            "resultado_conhecido_para_treino":len(treinadas),
            "original":row["pred"],"proposta_online":corrigido,
            "erro_original":abs(row["true"]-row["pred"]),
            "erro_proposta":abs(row["true"]-corrigido),
        })
        pendentes.append({
            **row, "x":x,"residual":row["true"]-row["pred"],
        })
    n=len(saidas)
    original=sum(r["erro_original"] for r in saidas)/n
    candidato=sum(r["erro_proposta"] for r in saidas)/n
    return {
        "estado":"REPLAY_INCREMENTAL_NAO_HOMOLOGADO",
        "modo":avaliacao["modo"],"primeira_publicacao":True,
        "serie":esperado,"avaliadas":n,"rotulos_aprendidos_antes_da_emissao_final":len(treinadas),
        "mae_original":original,"mae_proposta_online":candidato,
        "superou_original":candidato < original,
        "replay":saidas,"modelo_homologado":False,"autopromocao":False,
        "alerta":"Experimento offline; backtest não se converte em histórico LIVE.",
    }
