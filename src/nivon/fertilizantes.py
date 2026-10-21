"""Motor de importações de fertilizantes baseado em observações MDIC licenciadas.

Valor unitário FOB da importação NÃO é cotação CFR, preço entregue, preço futuro
CME nem valor de compra negociado por produtor.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation


class ErroFertilizantes(ValueError):
    pass


NCM_GRUPOS = {
    "31021010": "UREIA", "31021090": "UREIA",
    "31042010": "KCL", "31042090": "KCL",
    "31054000": "MAP", "31053010": "DAP", "31053090": "DAP",
    "31022100": "SULFATO_AMONIO",
}


def classificar_ncm(ncm: str) -> str:
    if not isinstance(ncm,str) or len(ncm) != 8 or not ncm.isdigit():
        raise ErroFertilizantes("NCM deve ter 8 dígitos")
    return NCM_GRUPOS.get(ncm, "OUTROS_FERTILIZANTES" if ncm.startswith("31") else "NAO_FERTILIZANTE")


def consolidar_importacoes(rows: list[dict]) -> list[dict]:
    """Soma quantidade kg e valor FOB USD por mês/produto/UF, sem falsa cotação."""
    grupos = defaultdict(lambda: [Decimal(0), Decimal(0), 0])
    for r in rows:
        if not isinstance(r,dict):
            raise ErroFertilizantes("registro inválido")
        ncm=r.get("ncm")
        categoria=classificar_ncm(ncm)
        if categoria=="NAO_FERTILIZANTE":
            raise ErroFertilizantes("NCM fora do capítulo fertilizantes")
        mes=r.get("mes")
        uf=r.get("uf")
        if not isinstance(mes,str) or len(mes)!=7 or mes[4]!="-":
            raise ErroFertilizantes("competência YYYY-MM obrigatória")
        if not isinstance(uf,str) or len(uf)!=2 or not uf.isalpha():
            raise ErroFertilizantes("UF inválida")
        if r.get("valor_moeda")!="USD_FOB" or r.get("unidade_peso")!="KG":
            raise ErroFertilizantes("base FOB/USD e peso KG da origem exigidos")
        try:
            kg=Decimal(str(r["peso_liquido_kg"]))
            usd=Decimal(str(r["valor_fob_usd"]))
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise ErroFertilizantes("valor numérico inválido") from exc
        if not kg.is_finite() or not usd.is_finite() or kg<0 or usd<0:
            raise ErroFertilizantes("kg ou FOB não finitos/negativos")
        item=grupos[(mes,uf.upper(),categoria)]
        item[0]+=kg;item[1]+=usd;item[2]+=1
    saida=[]
    for (mes,uf,cat),(kg,usd,n) in sorted(grupos.items()):
        tons=kg/Decimal(1000)
        saida.append({"competencia":mes,"uf":uf,"fertilizante":cat,
                      "volume_t":float(tons),"valor_fob_usd":float(usd),
                      "valor_unitario_fob_usd_t":float(usd/tons) if tons else None,
                      "linhas_origem":n,"tipo_preco":"VALOR_UNITARIO_COMERCIO_EXTERIOR_FOB_NAO_CFR",
                      "fonte_exigida":"MDIC_COMEX_STAT_NCM"})
    return saida
