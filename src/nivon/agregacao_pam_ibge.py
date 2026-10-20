"""Agregação municipal IBGE PAM: área e produção somadas, yield ponderado.

Não equivale a série completa da UF nem reconciliação automática com CONAB.
Milho PAM = total em grão (não separa safrinha); algodão em caroço != pluma.
Gergerlim incluído no escopo da PAM em 2025, não extrapolar séries anteriores.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation,localcontext
import re


class ErroAgregacaoIBGE(ValueError):
    pass


_UFS=frozenset({11,12,13,14,15,16,17,21,22,23,24,25,26,27,28,29,
                31,32,33,35,41,42,43,50,51,52,53})
_PRODUTOS={
    "SOJA":"SOJA_GRAO",
    "MILHO":"MILHO_GRAO_TOTAL",
    "TRIGO":"TRIGO_GRAO",
    "ALGODAO":"ALGODAO_HERBACEO_EM_CAROCO",
    "CANA":"CANA_DE_ACUCAR",
    "SORGO":"SORGO_GRAO",
    "GERGELIM":"GERGELIM_SEMENTE",
}
_LIMITES_KG_HA={"SOJA":12000,"MILHO":25000,"TRIGO":14000,"ALGODAO":20000,
                "CANA":250000,"SORGO":20000,"GERGELIM":10000}
_HASH=re.compile(r"[a-f0-9]{64}\Z")


def _dec(value,n):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)):
        raise ErroAgregacaoIBGE(n+": decimal obrigatório")
    try:d=Decimal(str(value))
    except InvalidOperation as ex:raise ErroAgregacaoIBGE(n+": valor não numérico") from ex
    if not d.is_finite() or d<0 or len(d.as_tuple().digits)>28:
        raise ErroAgregacaoIBGE(n+": número negativo, não finito ou excessivamente preciso")
    return d


def _dados_referencia(r):
    year=r.get("ano")
    crop=r.get("cultura")
    if type(year) is not int or not 1974<=year<=2100 or crop not in _PRODUTOS:
        raise ErroAgregacaoIBGE("ano/cultura inválido")
    if crop=="GERGELIM" and year<2025:
        raise ErroAgregacaoIBGE("PAM gergelim não foi incluído antes de 2025")
    if r.get("produto_ibge")!=_PRODUTOS[crop]:
        raise ErroAgregacaoIBGE("produto IBGE incompatível: separar milho safras e algodão caroço/pluma")
    municipality=r.get("municipio_ibge")
    if not isinstance(municipality,str) or not re.fullmatch(r"[1-9][0-9]{6}",municipality):
        raise ErroAgregacaoIBGE("código municipal IBGE 7 dígitos obrigatório")
    uf=int(municipality[:2])
    if uf not in _UFS:
        raise ErroAgregacaoIBGE("UF fora da tabela oficial IBGE")
    edition=r.get("edicao_id")
    if not isinstance(edition,str) or not 3<=len(edition)<=120:
        raise ErroAgregacaoIBGE("edição de divulgação não documentada")
    digest=r.get("raw_sha256")
    if not isinstance(digest,str) or not _HASH.fullmatch(digest):
        raise ErroAgregacaoIBGE("SHA do bruto ausente")
    return year,crop,municipality,uf,edition,digest


def agregar_municipios_pam(*,registros:list[dict],uf_ibge:int,
                           cultura:str,ano:int)->dict:
    if type(uf_ibge) is not int or uf_ibge not in _UFS:
        raise ErroAgregacaoIBGE("UF desconhecida")
    if cultura not in _PRODUTOS or type(ano) is not int:
        raise ErroAgregacaoIBGE("cultura/ano obrigatórios")
    if not isinstance(registros,list) or not 2<=len(registros)<=9000:
        raise ErroAgregacaoIBGE("2 a 9000 registros municipais exigidos")
    vistos=set();filas=[];vintage=None
    for r in registros:
        if not isinstance(r,dict):raise ErroAgregacaoIBGE("registro inválido")
        y,c,municipio,uf,edition,hash_=_dados_referencia(r)
        if (y,c,uf)!=(ano,cultura,uf_ibge):
            raise ErroAgregacaoIBGE("proibido misturar UF, produto ou competência")
        if municipio in vistos:
            raise ErroAgregacaoIBGE("município duplicado na edição")
        vistos.add(municipio)
        meta=(edition,hash_)
        if vintage is not None and vintage!=meta:
            raise ErroAgregacaoIBGE("série com edições/hashes diferentes")
        vintage=meta
        area=_dec(r.get("area_colhida_ha"),"área colhida")
        prod=_dec(r.get("quantidade_produzida_t"),"produção t")
        if area==0 and prod>0:
            raise ErroAgregacaoIBGE("produção positiva sem área colhida")
        rendimento=Decimal(0) if area==0 else prod*Decimal(1000)/area
        if rendimento>_LIMITES_KG_HA[cultura]:
            raise ErroAgregacaoIBGE("produtividade municipal muito acima do limite de plausibilidade: revisão manual")
        declarado=r.get("rendimento_reportado_kg_ha")
        qualidade="SEM_RENDIMENTO_REPORTADO"
        if declarado is not None:
            valor=_dec(declarado,"rendimento reportado")
            prec_area=_dec(r.get("resolucao_area_ha"),"resolução área")
            prec_prod=_dec(r.get("resolucao_producao_t"),"resolução produção")
            prec_yield=_dec(r.get("resolucao_rendimento_kg_ha"),"resolução yield")
            if min(prec_area,prec_prod,prec_yield)<=0:
                raise ErroAgregacaoIBGE("resoluções de arredondamento devem ser positivas")
            if area==0:
                consistente=(prod==0 and valor==0)
            elif area<=prec_area/2:
                consistente=False
            else:
                max_y=(prod+prec_prod/2)*Decimal(1000)/(area-prec_area/2)
                min_y=max(Decimal(0),prod-prec_prod/2)*Decimal(1000)/(area+prec_area/2)
                consistente=(valor+prec_yield/2>=min_y and
                              max(Decimal(0),valor-prec_yield/2)<=max_y)
            qualidade="ARREDONDAMENTO_CONSISTENTE" if consistente else "REPROVADO_ROUNDING"
        filas.append({"municipio_ibge":municipio,"area_ha":area,"producao_t":prod,
                      "produtividade_kg_ha":rendimento,"estado":qualidade})
    with localcontext() as ctx:
        ctx.prec=40
        area=sum((x["area_ha"] for x in filas),Decimal(0))
        production=sum((x["producao_t"] for x in filas),Decimal(0))
        avg=None if area==0 else production*Decimal(1000)/area
    reproves=[x["municipio_ibge"] for x in filas if x["estado"]=="REPROVADO_ROUNDING"]
    return {
        "dataset_id":"IBGE_PAM","ano":ano,"cultura":cultura,
        "produto_ibge":_PRODUTOS[cultura],"uf_ibge":uf_ibge,
        "edicao_id":vintage[0],"raw_sha256":vintage[1],
        "municipios_no_lote":len(filas),
        "area_colhida_ha":str(area),"producao_total_t":str(production),
        "rendimento_ponderado_kg_ha":None if avg is None else str(avg),
        "municipios_reprovados_arredondamento":reproves,
        "status":"AGREGACAO_PARCIAL_SEM_PROVA_COBERTURA",
        "cobertura_uf_completa_confirmada":False,
        "nota":"Nunca calcular produtividade UF por média aritmética. IBGE PAM não distingue safrinha e algodão caroço não é pluma. Revisar edição e unidades.",
        "habilita_modelo":False,
    }


def comparar_total_oficial_uf(*,agregado:dict,
                            area_oficial_ha,producao_oficial_t,
                            tolerancia_area_ha,tolerancia_producao_t,
                            cobertura_integral_auditada:bool=False)->dict:
    if not isinstance(agregado,dict) or agregado.get("status")!="AGREGACAO_PARCIAL_SEM_PROVA_COBERTURA":
        raise ErroAgregacaoIBGE("agregado não reconhecido")
    if type(cobertura_integral_auditada) is not bool:
        raise ErroAgregacaoIBGE("prova de universo deve ser declaração explícita")
    if not cobertura_integral_auditada:
        return {"status":"NAO_COMPARAVEL_UNIVERSO_NAO_COMPROVADO",
                "residuo_area_ha":None,"residuo_producao_t":None,
                "habilita_publicacao":False}
    if agregado["municipios_reprovados_arredondamento"]:
        raise ErroAgregacaoIBGE("não reconciliar com dados municipais fisicamente rejeitados")
    a=_dec(area_oficial_ha,"área UF");p=_dec(producao_oficial_t,"produção UF")
    ta=_dec(tolerancia_area_ha,"tolerância área");tp=_dec(tolerancia_producao_t,"tolerância produção")
    res_a=Decimal(agregado["area_colhida_ha"])-a
    res_p=Decimal(agregado["producao_total_t"])-p
    return {"status":"BALANCO_UF_DECLARADO_SEM_HOMOLOGACAO",
            "residuo_area_ha":str(res_a),"residuo_producao_t":str(res_p),
            "tolerancia_area_ha":str(ta),"tolerancia_producao_t":str(tp),
            "conservacao_consistente":abs(res_a)<=ta and abs(res_p)<=tp,
            "habilita_publicacao":False}
