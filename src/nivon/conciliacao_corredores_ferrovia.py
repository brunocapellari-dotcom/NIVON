"""NIVON: estações de embarque ferroviário ANTT/SIADE × polos rodoviários.

Cruzamento indicativo por município/UF e competência, sem imputar transbordo.
Entrada ferroviária via montar_lote() valida CSV bruto + hash + manifesto.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .antt_bigquery import montar_lote
from .inteligencia_corredores import POLOS, consultar_corredores, ErroCorredor


class ErroConciliacao(ValueError):
    pass


def _nome(valor):
    t=unicodedata.normalize("NFKD",str(valor or "")).encode("ascii","ignore").decode().casefold()
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",t)).strip()


# Correspondências exatas de denominações, sem fuzzy match.
# NÃO identificar estação pelo nome da cidade para provar terminal utilizado.
CROSSWALK_MERCADORIAS = {
    "soja":"SOJA_EM_GRAO",
    "soja em graos":"SOJA_EM_GRAO",
    "soja em grao":"SOJA_EM_GRAO",
    "milho":"MILHO_EM_GRAO",
    "graos milho":"MILHO_EM_GRAO",
    "graos soja":"SOJA_EM_GRAO",
    "milho em graos":"MILHO_EM_GRAO",
    "milho em grao":"MILHO_EM_GRAO",
    "farelo de soja":"FARELO_SOJA",
    "farelo soja":"FARELO_SOJA",
    "oleo de soja":"OLEO_SOJA",
    "oleo soja":"OLEO_SOJA",
    "acucar":"ACUCAR",
    "oleo diesel":"DERIVADOS_PETROLEO",
}
# Não mapear automaticamente "fertilizantes" a uma NCM específica.


def _produto(nome):
    return CROSSWALK_MERCADORIAS.get(_nome(nome))


def _decimal(raw):
    try:
        x=Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ErroConciliacao("toneladas úteis ferroviárias inválidas") from exc
    if not x.is_finite() or x<0:
        raise ErroConciliacao("toneladas úteis negativas ou não finitas")
    return x


def _polo_estacao(estacao, uf):
    """Convergência do nome geográfico exato, nunca geofencing de terminal."""
    s=_nome(estacao)
    return [
        {"id":p["id"],"nome":p["nome"],"municipio":p["municipio"],"uf":p["uf"],
         "modal_destino":p["modal_destino"],
         "evidencia":"ESTACAO_NOME_IGUAL_A_MUNICIPIO_NAO_TERMINAL_VERIFICADO"}
        for p in POLOS
        if p["uf"]==uf and p["modal_destino"]=="FERROVIARIO"
        and s==_nome(p["municipio"])
    ]


def analisar_estacoes(linhas, *, competencia, uf_origem=None, limite=100, sha256=None):
    """Ranking de estações de ORIGEM / destinos SIADE.

    Linhas vindas de montar_lote ou parser oficial; NÃO são viagens únicas.
    """
    if not isinstance(competencia,str) or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])",competencia):
        raise ErroConciliacao("competência inválida")
    if uf_origem is not None and (not isinstance(uf_origem,str) or not re.fullmatch(r"[A-Z]{2}",uf_origem)):
        raise ErroConciliacao("UF inválida")
    if type(limite) is not int or not 1<=limite<=1000:
        raise ErroConciliacao("limite inválido")
    if not isinstance(linhas,list) or len(linhas)>250000:
        raise ErroConciliacao("linhas ausentes/excessivas")
    seen=set()
    grouped={}
    for row in linhas:
        if not isinstance(row,dict):
            raise ErroConciliacao("registro não é objeto")
        if row.get("competencia")!=competencia or (uf_origem and row.get("uf_origem")!=uf_origem):
            continue
        for k in ("linha_id","ferrovia","mercadoria","estacao_origem","uf_origem","estacao_destino",
                  "uf_destino","toneladas_uteis","natureza_tu","arquivo_sha256"):
            if row.get(k) is None:
                raise ErroConciliacao("campo ferroviário ausente: "+k)
        if row["natureza_tu"]!="OBSERVADO_DECLARADO":
            raise ErroConciliacao("fonte não observada no contrato")
        ident=str(row["linha_id"])
        if ident in seen:
            raise ErroConciliacao("mesma linha ferroviária repetida")
        seen.add(ident)
        if sha256 is not None and row["arquivo_sha256"]!=sha256:
            raise ErroConciliacao("hash de arquivo ferrovia divergente")
        if not re.fullmatch(r"[A-Z]{2}",str(row["uf_origem"])) or not re.fullmatch(r"[A-Z]{2}",str(row["uf_destino"])):
            raise ErroConciliacao("UF ferroviária malformada")
        t=_decimal(row["toneladas_uteis"])
        key=(row["estacao_origem"],row["uf_origem"],row["ferrovia"],
             row["mercadoria"],row["estacao_destino"],row["uf_destino"])
        if key not in grouped:
            grouped[key]={"estacao_origem":key[0],"uf_origem":key[1],"ferrovia":key[2],
                          "mercadoria_fonte":key[3],"produto_normalizado":_produto(key[3]),
                          "estacao_destino":key[4],"uf_destino":key[5],
                          "tu":Decimal(0),"linhas_od":0}
        grouped[key]["tu"]+=t
        grouped[key]["linhas_od"]+=1

    # Totais por polo candidato exclusivamente de ORIGEM ferroviária.
    by_polo={}
    for row in grouped.values():
        for polo in _polo_estacao(row["estacao_origem"],row["uf_origem"]):
            key=polo["id"]
            if key not in by_polo:
                by_polo[key]={"polo":polo,"toneladas_ferroviarias":Decimal(0),
                              "produtos":defaultdict(lambda:Decimal(0)),
                              "estacoes_origem":set()}
            x=by_polo[key]
            x["toneladas_ferroviarias"]+=row["tu"]
            x["produtos"][row["mercadoria_fonte"]]+=row["tu"]
            x["estacoes_origem"].add(row["estacao_origem"])

    polos=[]
    for v in by_polo.values():
        polos.append({
            "polo":v["polo"],
            "toneladas_ferroviarias":format(v["toneladas_ferroviarias"],"f"),
            "estacoes_origem":sorted(v["estacoes_origem"]),
            "mercadorias":[{
                "mercadoria_fonte":k,"toneladas_ferroviarias":format(t,"f"),
                "produto_normalizado":_produto(k),
            } for k,t in sorted(v["produtos"].items(),key=lambda a:(-a[1],a[0]))],
            "status":"POLO_POTENCIAL_POR_NOME_DE_ESTACAO",
            "terminal_comprovado":False,
        })
    polos.sort(key=lambda x:(-Decimal(x["toneladas_ferroviarias"]),x["polo"]["id"]))
    ordenados=sorted(grouped.values(),key=lambda x:(-x["tu"],x["estacao_origem"],x["estacao_destino"],x["mercadoria_fonte"]))
    rankings=[]
    for row in ordenados[:limite]:
        rankings.append({k:v for k,v in row.items() if k!="tu"} | {
            "toneladas_ferroviarias":format(row["tu"],"f"),
            "polo_candidato_origem":_polo_estacao(row["estacao_origem"],row["uf_origem"]),
        })
    return {
        "fonte":"ANTT_SIADE_ORIGEM_DESTINO","competencia":competencia,
        "uf_origem":uf_origem,"qualidade":"TU_DECLARADA_FONTE_PRIMARIA_REQUER_CONCILIACAO",
        "total_de_linhas_no_periodo":len(seen),"linhas_agrupadas":len(grouped),
        "sha256_fonte":sha256,"ranking":rankings,
        "total_ranking_sem_limite":len(ordenados),"ranking_truncado":len(ordenados)>limite,
        "polos_ferroviarios":polos,
        "regra":"TU ferroviária não equivale a toneladas rodoviárias distintas ou transbordo comprovado",
    }


def analisar_staging(pasta, *, ano, competencia, uf_origem="MT", limite=100):
    """Carrega CSV oficial revalidando SHA, origem e quantidade pelo manifest."""
    if type(ano) is not int or not 2006<=ano<=2100 or not competencia.startswith(str(ano)+"-"):
        raise ErroConciliacao("ano divergente da competência")
    rows,meta=montar_lote(pasta,ano)
    if meta["registros"]!=len(rows):
        raise ErroConciliacao("manifesto SIADE divergente")
    return analisar_estacoes(rows,competencia=competencia,uf_origem=uf_origem,
                           limite=limite,sha256=meta["sha256"])


def quadro_intermodal(ferrovia, rodovia):
    """Pareamento lateral por ID de polo, nunca soma ou estima repasse."""
    if ferrovia.get("competencia")!=rodovia.get("competencia"):
        raise ErroConciliacao("competências incompatíveis")
    ferro_polos={x["polo"]["id"]:x for x in ferrovia.get("polos_ferroviarios",[])}
    rodo_polos={x["polo"]["id"]:x for x in rodovia.get("resumo_polos",[])
                if x["sentido"]=="DESTINO" and x["polo"]["modal_destino"]=="FERROVIARIO"}
    saida=[]
    for polo_id in sorted(set(ferro_polos)|set(rodo_polos)):
        rail=ferro_polos.get(polo_id)
        road=rodo_polos.get(polo_id)
        saida.append({
            "polo_id":polo_id,
            "toneladas_rodoviarias_destino_geografico":road["toneladas_no_recorte"] if road else None,
            "toneladas_ferroviarias_estacao_origem":rail["toneladas_ferroviarias"] if rail else None,
            "mercadorias_ferroviarias":rail["mercadorias"] if rail else [],
            "principais_origens_rodoviarias":road["principais_origens"] if road else [],
            "status":"DADOS_LADO_A_LADO_SEM_CONCILIACAO_FISICA",
            "transbordo_confirmado":False,
            "soma_entre_modais_permitida":False,
            "razao_rodo_ferro_permitida":False,
            "comparacao_semantica":"IGUALDADE_NOMINAL_MUNICIPIO_ESTACAO_APENAS",
        })
    return {
        "estado":"COMPARACAO_EXPLORATORIA_NAO_BALANCO",
        "competencia":ferrovia["competencia"],
        "rodoviario_estado":rodovia.get("estado"),
        "ferroviario_qualidade":ferrovia.get("qualidade"),
        "dados":saida,
        "sem_dados_nao_equivale_a_zero":True,
        "nota":"MDF-e amostral/sem destino terminal; SIADE estação de origem não prova transferência direta",
    }


def quadro_staging(pasta_ferro, banco_rodo, *, ano, competencia, recorte, limite=100):
    f=analisar_staging(pasta_ferro,ano=ano,competencia=competencia,limite=limite)
    r=consultar_corredores(banco_rodo,recorte=recorte,competencia=competencia,limite=limite)
    return quadro_intermodal(f,r)


def comparar_mes_contra_ano_anterior(anterior, atual):
    """Mudança de TU embarcada por nome exato de polo, mesmo mês em anos adjacentes.

    Sem volumes de rodovia e sem extrapolar se um polo não aparece na fonte.
    """
    a=anterior.get("competencia")
    b=atual.get("competencia")
    if (not isinstance(a,str) or not isinstance(b,str) or
        not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])",a) or
        not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])",b) or
        a[5:]!=b[5:] or int(b[:4])-int(a[:4])!=1):
        raise ErroConciliacao("comparação exige mesmo mês em anos consecutivos")
    if anterior.get("uf_origem")!=atual.get("uf_origem"):
        raise ErroConciliacao("UF de origem distinta")
    def indexar(d):
        x={}
        for p in d.get("polos_ferroviarios",[]):
            polo=p["polo"]["id"]
            if polo in x:
                raise ErroConciliacao("polo ferroviário repetido")
            x[polo]=p
        return x
    x=indexar(anterior)
    y=indexar(atual)
    saida=[]
    for id in sorted(set(x)|set(y)):
        velho=x.get(id)
        novo=y.get(id)
        valor_a=_decimal(velho["toneladas_ferroviarias"]) if velho else None
        valor_b=_decimal(novo["toneladas_ferroviarias"]) if novo else None
        delta=valor_b-valor_a if valor_a is not None and valor_b is not None else None
        pct=delta/valor_a*100 if valor_a is not None and valor_a>0 and valor_b is not None else None
        saida.append({
            "polo_id":id,
            "tu_mes_anterior_ano":str(valor_a) if valor_a is not None else None,
            "tu_mes_atual":str(valor_b) if valor_b is not None else None,
            "variacao_absoluta_tu":str(delta) if delta is not None else None,
            "variacao_percentual":format(pct.quantize(Decimal("0.01")),"f") if pct is not None else None,
            "comparavel":delta is not None,
            "estado":"COMPARAVEL_MESMO_MES_ESTACAO_NOME_EXATO" if delta is not None else "LACUNA_FONTE_NAO_ZERO",
        })
    return {
        "estado":"COMPARACAO_ANUAL_FERROVIARIA_NAO_E_TRANSBORDO",
        "anterior_competencia":a,"atual_competencia":b,
        "uf_origem":atual["uf_origem"],
        "polos":saida,
        "nota":"Mesmo mês de anos consecutivos; diferenças podem incluir mudanças de estação/cadastro/revisão.",
    }
