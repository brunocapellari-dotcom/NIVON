"""Anos análogos com cutoff temporal verificável.

Método adaptado a partir de models/analog_years.py do AgroLogMT (mesmo titular):
distância euclidiana padronizada com checagens explícitas para leakage, features
constantes e série incompleta. Similaridade não é probabilidade nem previsão.
"""
from __future__ import annotations
from math import sqrt
from .qualidade_cientifica import ErroCientifico,numero,_instante


def encontrar_anos_analogos(*, ano_alvo:int, emitido_em:str,
                           variaveis_atuais:dict, historico:dict,
                           fonte_id:str, top_n:int=3) -> dict:
    if type(ano_alvo) is not int or not 1800<ano_alvo<2200:
        raise ErroCientifico("ano alvo inválido")
    if type(top_n) is not int or not 1<=top_n<=10:
        raise ErroCientifico("top_n inválido")
    corte=_instante(emitido_em,"emitido_em")
    if not fonte_id or not isinstance(fonte_id,str):
        raise ErroCientifico("fonte explícita obrigatória")
    if not isinstance(variaveis_atuais,dict) or not isinstance(historico,dict):
        raise ErroCientifico("features atuais e histórico obrigatórios")
    features=sorted(variaveis_atuais)
    if len(features)<3:
        raise ErroCientifico("mínimo de três fatores antes de procurar anos análogos")
    current={k:numero(variaveis_atuais[k],k,nao_negativo=False) for k in features}
    anteriores=[]
    for ano,row in historico.items():
        if type(ano) is not int or ano>=ano_alvo or not isinstance(row,dict):
            raise ErroCientifico("histórico com ano futuro, atual ou inválido")
        if set(row)!={"disponivel_em","variaveis"}:
            raise ErroCientifico("cada ano precisa de disponibilidade e variáveis explícitas")
        if _instante(row["disponivel_em"],"disponivel_em")>corte:
            continue
        vs=row["variaveis"]
        if not isinstance(vs,dict) or any(k not in vs for k in features):
            raise ErroCientifico("fator ausente em série histórica, não imputar sem método")
        valores={k:numero(vs[k],k,nao_negativo=False) for k in features}
        anteriores.append((ano,valores))
    if len(anteriores)<5:
        return {"estado":"REPROVADO","motivo":"HISTORICO_ASOF_INSUFICIENTE",
                "anos_comprovados":len(anteriores),"analogos":[]}
    means={k:sum(v[k] for _,v in anteriores)/len(anteriores) for k in features}
    sigma={k:sqrt(sum((v[k]-means[k])**2 for _,v in anteriores)/len(anteriores)) for k in features}
    usaveis=[k for k in features if sigma[k]>1e-12]
    if len(usaveis)<3:
        return {"estado":"REPROVADO","motivo":"FATORES_SEM_VARIABILIDADE",
                "anos_comprovados":len(anteriores),"analogos":[]}
    resultados=[]
    for ano,vs in anteriores:
        distancia=sqrt(sum(((current[k]-vs[k])/sigma[k])**2 for k in usaveis)/len(usaveis))
        resultados.append({"ano":ano,"distancia_padronizada":distancia})
    resultados.sort(key=lambda x:(x["distancia_padronizada"],x["ano"]))
    return {"estado":"ANALOGOS_DESCRITIVOS_NAO_PREDITIVOS",
            "metodo":"AGROLOG_STANDARDIZED_EUCLIDEAN_ADAPTADO_PIT",
            "fonte":fonte_id,"cutoff":emitido_em,
            "features_usadas":usaveis,"features_constantes_descartadas":sorted(set(features)-set(usaveis)),
            "anos_comprovados":len(anteriores),"analogos":resultados[:top_n],
            "limitacao":"Não inferir probabilidade, produtividade ou clima futuro apenas por similaridade histórica"}
