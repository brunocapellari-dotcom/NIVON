"""Reconciliação EXPLÍCITA de totais Comex Stat do mesmo ano e direção.

Compara totais do CSV integral contra números fornecidos pelo operador, sem
afirmar que a referência é oficial só porque o usuário forneceu uma URL.
NCM e SH4 são agregações distintas, não se reconciliam por município físico.
"""
from __future__ import annotations
import re

class ErroReconciliacaoMDIC(ValueError):
    pass

def _inteiro(x,nome):
    if type(x) is not int or x<0 or x>10**20:
        raise ErroReconciliacaoMDIC(nome+": inteiro não negativo obrigatório")
    return x

def reconciliar_totais_mdic(resumo:dict, *, referencias:list[dict],
                           fonte_referencia:str, tolerancia_kg:int=0,
                           tolerancia_usd:int=0)->dict:
    """Falha fechado em lacunas e divergências; nunca libera publicação."""
    if not isinstance(resumo,dict) or not isinstance(referencias,list) or not referencias:
        raise ErroReconciliacaoMDIC("resumo e referências necessárias")
    if resumo.get("dataset_id") not in ("MDIC_COMEX_NCM","MDIC_COMEX_MUNICIPIO_SH4"):
        raise ErroReconciliacaoMDIC("dataset inválido")
    ano=resumo.get("ano")
    if type(ano) is not int or not 1997<=ano<=2100:
        raise ErroReconciliacaoMDIC("ano inválido")
    if not isinstance(fonte_referencia,str) or not (
         fonte_referencia.startswith("https://www.gov.br/mdic/pt-br/") or
         fonte_referencia.startswith("https://balanca.mdic.gov.br/")):
        raise ErroReconciliacaoMDIC("fonte referência não é MDIC oficial")
    tol_kg=_inteiro(tolerancia_kg,"tolerancia_kg")
    tol_usd=_inteiro(tolerancia_usd,"tolerancia_usd")
    if tol_kg>1000 or tol_usd>1000:
        raise ErroReconciliacaoMDIC("tolerância excessiva; requer revisão metodológica")
    datas=resumo.get("totais_arquivo_por_mes")
    if not isinstance(datas,list) or not datas:
        raise ErroReconciliacaoMDIC("arquivo sem totais mensais")
    interno={}
    somakg=somausd=somalinha=0
    for x in datas:
        if not isinstance(x,dict):
            raise ErroReconciliacaoMDIC("total mensal inválido")
        mes=x.get("competencia")
        if not isinstance(mes,str) or not re.fullmatch(rf"{ano}-(0[1-9]|1[0-2])",mes) or mes in interno:
            raise ErroReconciliacaoMDIC("competência ausente, duplicada ou de ano diferente")
        kg=_inteiro(x.get("kg"),"kg")
        usd=_inteiro(x.get("fob_usd"),"fob_usd")
        n=_inteiro(x.get("linhas"),"linhas")
        if not n:raise ErroReconciliacaoMDIC("mês sem linhas")
        interno[mes]=(kg,usd)
        somakg+=kg;somausd+=usd;somalinha+=n
    if somalinha!=resumo.get("linhas_total"):
        raise ErroReconciliacaoMDIC("soma de linhas mensais diverge do arquivo")
    if type(resumo.get("linhas_filtradas")) is not int or not 0<resumo["linhas_filtradas"]<=somalinha:
        raise ErroReconciliacaoMDIC("linhas filtradas inconsistentes")
    reference={}
    for x in referencias:
        if not isinstance(x,dict) or set(x)!={"competencia","kg","fob_usd"}:
            raise ErroReconciliacaoMDIC("referência fora do esquema")
        m=x["competencia"]
        if not isinstance(m,str) or not re.fullmatch(rf"{ano}-(0[1-9]|1[0-2])",m) or m in reference:
            raise ErroReconciliacaoMDIC("referência duplicada ou de outro período")
        reference[m]=(_inteiro(x["kg"],"kg_ref"),_inteiro(x["fob_usd"],"fob_ref"))
    if set(interno)!=set(reference):
        raise ErroReconciliacaoMDIC("lacuna ou mês adicional: não fabricar zeros")
    divergencias=[]
    for mes in sorted(interno):
        kg,usd=interno[mes]
        kgref,usdref=reference[mes]
        if abs(kg-kgref)>tol_kg or abs(usd-usdref)>tol_usd:
            divergencias.append({"competencia":mes,"diferenca_kg":kg-kgref,
                                 "diferenca_fob_usd":usd-usdref})
    if divergencias:
        raise ErroReconciliacaoMDIC("totais divergentes: "+",".join(x["competencia"] for x in divergencias))
    return {"dataset_id":resumo["dataset_id"],"ano":ano,
            "direcao":resumo.get("direcao"),"meses_conferidos":len(interno),
            "peso_total_kg":somakg,"fob_total_usd":somausd,
            "arquivo_sha256":resumo.get("sha256_original"),
            "fonte_referencia_declarada":fonte_referencia,
            "resultado":"TOTAIS_CONFERIDOS_ARITMETICAMENTE",
            "fonte_referencia_comprovada_por_terceiro":False,
            "base_historica_homologada":False,
            "publicacao_comercial_autorizada":False}
