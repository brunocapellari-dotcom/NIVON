"""Ponte de séries mensais MDIC -> cenários, a partir de vintages SQLite.

Nenhum dado sintético aparece na via padrão. Mesmo com dados reais, NÃO
qualifica publicação/backtest por data de publicação ou acurácia preditiva.
Zero observado explicitamente é distinto de mês/código ausente.
"""
from __future__ import annotations
import re
from datetime import datetime
from math import isfinite

from .ingestao_mdic import observar_mdic_asof_coleta
from .previsoes_bibliotecas import prever_mensal

class ErroSerieMDIC(ValueError):
    pass

_UFS=frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
_VARIAVEIS={"PESO_LIQUIDO_KG":("peso_liquido_kg","kg"),
             "VALOR_FOB_USD":("valor_fob_usd","USD")}

def montar_serie_mdic(
    db,*,ano_inicial:int,ano_final:int,direcao:str,
    granularidade:str,codigo_produto:str,uf:str,variavel:str,
    corte_coleta:str,incluir_sinteticos:bool=False
)->dict:
    """Exige anos civis completos; lacunas não são convertidas para 0."""
    if (type(ano_inicial) is not int or type(ano_final) is not int
            or not 1997<=ano_inicial<ano_final<=2100
            or not 2<=ano_final-ano_inicial+1<=10):
        raise ErroSerieMDIC("histórico exige de 2 a 10 anos completos")
    if direcao not in ("EXPORTACAO","IMPORTACAO"):
        raise ErroSerieMDIC("direção inválida")
    if granularidade not in ("NCM","MUNICIPIO_SH4"):
        raise ErroSerieMDIC("classificação inválida")
    digitos=8 if granularidade=="NCM" else 4
    if not isinstance(codigo_produto,str) or not re.fullmatch(rf"\d{{{digitos}}}",codigo_produto):
        raise ErroSerieMDIC("produto deve ser NCM8 ou SH4 explícito")
    if uf not in _UFS:
        raise ErroSerieMDIC("UF individual obrigatória; não inferir origem da carga")
    if variavel not in _VARIAVEIS:
        raise ErroSerieMDIC("variável/unidade inválida")
    if type(incluir_sinteticos) is not bool:
        raise ErroSerieMDIC("incluir_sinteticos exige bool")
    if not isinstance(corte_coleta,str) or "T" not in corte_coleta:
        raise ErroSerieMDIC("corte de coleta requer ISO com horário")
    try:
        corte=datetime.fromisoformat(corte_coleta.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroSerieMDIC("corte de coleta inválido") from exc
    if corte.tzinfo is None or corte.utcoffset() is None:
        raise ErroSerieMDIC("corte requer fuso")
    dataset_id="MDIC_COMEX_NCM" if granularidade=="NCM" else "MDIC_COMEX_MUNICIPIO_SH4"
    campo,unidade=_VARIAVEIS[variavel]
    serie=[]
    vintages=[]
    tipos=set()
    for ano in range(ano_inicial,ano_final+1):
        observado=observar_mdic_asof_coleta(
            db,dataset_id=dataset_id,ano=ano,direcao=direcao,
            corte_coleta=corte_coleta,incluir_sinteticos=incluir_sinteticos)
        if observado is None:
            raise ErroSerieMDIC(f"ano {ano} sem edição conhecida no corte")
        if (observado["dataset_id"]!=dataset_id or observado["direcao"]!=direcao
                or observado["ano"]!=ano):
            raise ErroSerieMDIC("proveniência do snapshot divergente")
        tipos.add(observado["tipo"])
        conteudo=observado["conteudo"]
        if not isinstance(conteudo,dict):
            raise ErroSerieMDIC("conteúdo histórico inválido")
        codigos=conteudo.get("codigos_solicitados")
        if not isinstance(codigos,list) or codigo_produto not in codigos:
            raise ErroSerieMDIC("edição foi filtrada sem o produto solicitado")
        controles=conteudo.get("totais_arquivo_por_mes")
        if not isinstance(controles,list) or len(controles)!=12:
            raise ErroSerieMDIC(f"ano {ano} sem 12 meses observados no CSV")
        meses_ctrl=set()
        for row in controles:
            if not isinstance(row,dict):raise ErroSerieMDIC("total de mês inválido")
            periodo=row.get("competencia")
            if not isinstance(periodo,str) or not re.fullmatch(rf"{ano}-(0[1-9]|1[0-2])",periodo):
                raise ErroSerieMDIC("controle mensal inválido")
            if periodo in meses_ctrl:
                raise ErroSerieMDIC("mês de controle duplicado")
            meses_ctrl.add(periodo)
            if type(row.get("linhas")) is not int or row["linhas"]<=0:
                raise ErroSerieMDIC("total mensal sem registros reais")
        por_mes={}
        recortes=conteudo.get("recortes")
        if not isinstance(recortes,list):raise ErroSerieMDIC("recortes inválidos")
        for x in recortes:
            if not isinstance(x,dict):raise ErroSerieMDIC("recorte malformado")
            if x.get("codigo_produto")!=codigo_produto or x.get("uf")!=uf:
                continue
            periodo=x.get("competencia")
            if periodo not in meses_ctrl:raise ErroSerieMDIC("recorte fora da competência do CSV")
            valor=x.get(campo)
            if (type(valor) not in (int,float) or not isfinite(valor)
                    or valor<0):
                raise ErroSerieMDIC("valor ausente, negativo ou não finito")
            por_mes[periodo]=por_mes.get(periodo,0.0)+float(valor)
        if set(por_mes)!=meses_ctrl:
            raise ErroSerieMDIC(f"ano {ano} tem mês sem produto/UF observado; não criar zero")
        for periodo in sorted(por_mes):
            serie.append((periodo,por_mes[periodo]))
        vintages.append({"ano":ano,"sha256":observado["sha256"],
                         "ultima_coleta_conhecida":observado["visto_utc"],
                         "tipo":observado["tipo"]})
    if len(serie)<24:
        raise ErroSerieMDIC("série mensal curta")
    for i,(periodo,_) in enumerate(serie):
        esperado_ano=ano_inicial+i//12
        esperado_mes=i%12+1
        if periodo!=f"{esperado_ano}-{esperado_mes:02d}":
            raise ErroSerieMDIC("série com lacuna ou mês fora de ordem")
    return {
        "serie":serie,"unidade":unidade,"variavel":variavel,
        "dataset_id":dataset_id,"codigo_produto":codigo_produto,
        "uf_fiscal_ou_ncm":uf,"direcao":direcao,
        "granularidade":granularidade,"corte_coleta":corte.isoformat(),
        "vintages":vintages,
        "contagem_meses":len(serie),
        "somente_dados_reais":tipos=={"REAL_AUTORIZADO"},
        "classe":"SERIE_EXPLORATORIA_SEM_HOMOLOGACAO",
        "qualidade_reconciliada_com_total_oficial":False,
        "apta_backtest_por_publicacao":False,
        "apta_publicacao_preditiva":False,
        "limite":"UF fiscal e NCM não identificam fluxo rodoviário, porto ou origem agrícola",
    }

def avaliar_cenario_mensal_mdic(serie_preparada:dict, *,
                               backend=None,horizonte:int=3,
                               permitir_sinteticos_para_teste:bool=False)->dict:
    """Proíbe promoção: integra previsão existente somente para cenário."""
    if not isinstance(serie_preparada,dict) or serie_preparada.get("classe")!="SERIE_EXPLORATORIA_SEM_HOMOLOGACAO":
        raise ErroSerieMDIC("série sem contrato de qualidade do NIVON")
    if (serie_preparada.get("apta_publicacao_preditiva") is not False
        or serie_preparada.get("apta_backtest_por_publicacao") is not False):
        raise ErroSerieMDIC("flags de governança foram adulteradas")
    if (not serie_preparada.get("somente_dados_reais",False)
        and permitir_sinteticos_para_teste is not True):
        raise PermissionError("cenário com série sintética exige opt-in de teste")
    vintages=serie_preparada.get("vintages")
    if (not isinstance(vintages,list) or len(vintages)<2 or
        len(serie_preparada.get("serie",[]))!=12*len(vintages)):
        raise ErroSerieMDIC("vintages ou cobertura mensal insuficientes")
    resultado=prever_mensal(serie_preparada["serie"],horizonte=horizonte,backend=backend)
    return {**resultado,"origem_dataset":serie_preparada["dataset_id"],
            "produto_codigo":serie_preparada["codigo_produto"],
            "uf":serie_preparada["uf_fiscal_ou_ncm"],
            "direcao":serie_preparada["direcao"],
            "variavel":serie_preparada["variavel"],
            "unidade":serie_preparada["unidade"],
            "vintages":vintages,
            "data_de_corte":serie_preparada["corte_coleta"],
            "publicavel":False,"modelo_promovido":False,
            "status_qualidade":"CENARIO_DE_TESTE_NAO_HOMOLOGADO"}
