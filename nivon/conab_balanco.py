"""Contratos de validação CONAB: balanço oferta/demanda, mil toneladas."""
from decimal import Decimal,InvalidOperation

CAMPOS=("estoque_inicial","producao","importacao","suprimento",
        "consumo","exportacao","demanda_total","estoque_final")

def decimal_opcional(v):
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return None
    if isinstance(v,bool):
        raise ValueError("Booleano no balanço")
    try:
        n=Decimal(str(v))
    except (InvalidOperation,TypeError) as exc:
        raise ValueError("Número inválido") from exc
    if not n.is_finite():
        raise ValueError("Número não finito")
    return n

def normalizar_balanco(linhas, fonte, publicacao):
    if str(fonte).lower()!="conab":
        raise ValueError("Balanço não vem da CONAB")
    if not isinstance(publicacao,dict) or not publicacao.get("url"):
        raise ValueError("Metadados da publicação ausentes")
    saida=[]
    for row in linhas:
        if row.get("produto") not in ("soja","milho"):
            raise ValueError("Produto não homologado")
        if row.get("unidade")!="mil_ton":
            raise ValueError("Unidade de balanço inesperada")
        serie={k:decimal_opcional(row.get(k)) for k in CAMPOS}
        def erro(a,b,tol=Decimal("0.20")):
            return abs(a-b)>tol
        inicio,prod,imp,supr,cons,exp,dem,final=(serie[k] for k in CAMPOS)
        inconsistencias=[]
        if all(x is not None for x in (inicio,prod,imp,supr)) and erro(inicio+prod+imp,supr):
            inconsistencias.append("SUPRIMENTO")
        if all(x is not None for x in (cons,exp,dem)) and erro(cons+exp,dem):
            inconsistencias.append("DEMANDA")
        if all(x is not None for x in (supr,cons,exp,final)) and erro(supr-cons-exp,final):
            inconsistencias.append("ESTOQUE_FINAL")
        saida.append({"produto":row["produto"],"safra":str(row.get("safra")),
                       "unidade":"mil_ton","fonte":"CONAB","edicao":publicacao,
                       "metricas":{k:str(v) if v is not None else None for k,v in serie.items()},
                       "alertas":inconsistencias,"armazenado":False})
    return saida
