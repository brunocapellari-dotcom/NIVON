"""Motores intersetoriais NIVON: armazenagem, fretes, portos, comex e macro.

São cálculos determinísticos com insumos declarados, não medições em tempo
real. Sem coletor de rede, sem estimar volumes de terceiros e sem preços
negociados inferidos a partir de anúncios.
"""
from __future__ import annotations
from datetime import datetime
from math import isfinite
from .motores import DadoInvalido, numero_positivo


def _n(x,n,zero=False):
    return numero_positivo(x,n,aceita_zero=zero)


def _fonte(x):
    if not isinstance(x,str) or not x.strip():
        raise DadoInvalido("proveniência obrigatória")
    return x


def _assum(x):
    if type(x) not in (int,float) or not isfinite(x):
        raise DadoInvalido("coeficiente de sensibilidade explícito e finito")
    return float(x)


def pressao_armazenagem(*,producao_pico_t,capacidade_estatica_t,
                       estoque_observado_t=None,fonte):
    """Razão estrutural NÃO equivale a déficit real: giro e fluxos importam."""
    producao=_n(producao_pico_t,"producao_pico_t",True)
    cap=_n(capacidade_estatica_t,"capacidade_estatica_t")
    ocupacao=None
    if estoque_observado_t is not None:
        stock=_n(estoque_observado_t,"estoque_observado_t",True)
        ocupacao=stock/cap
    return {"razao_producao_capacidade":producao/cap,
            "ocupacao_real_calculada":ocupacao,
            "fonte":_fonte(fonte),"classificacao":"INDICADOR_ESTRUTURAL_ARMAZENAGEM",
            "limitacao":"Razão produção/capacidade não mede déficit, estoque disponível ou armazenagem privada acessível."}


def demanda_fertilizante_cenario(*,area_ha,dose_kg_ha,fracao_area_atendida,
                                fonte_recomendacao):
    area=_n(area_ha,"area_ha")
    dose=_n(dose_kg_ha,"dose_kg_ha",True)
    frac=_n(fracao_area_atendida,"fracao_area_atendida",True)
    if frac>1:raise DadoInvalido("fração de área acima de 100%")
    return {"demanda_formulada_estimativa_t":area*dose*frac/1000,
            "fonte_recomendacao":_fonte(fonte_recomendacao),
            "classificacao":"CENARIO_DEMANDA_FERTILIZANTE",
            "limitacao":"A dose deve ser validada para cultura, solo, formulação e safra; não é entrega/consumo observado."}


def custo_frete_rodoviario(*,distancia_km,custo_variavel_rs_km,
                          custos_fixos_viagem_rs,pedagios_rs,
                          carga_util_t,frete_anunciado_rs_t,fonte):
    """Receita anunciada não prova aceitação ou execução do transporte."""
    km=_n(distancia_km,"distancia_km")
    variavel=_n(custo_variavel_rs_km,"custo_variavel_rs_km",True)
    fixo=_n(custos_fixos_viagem_rs,"custo_fixo",True)
    ped=_n(pedagios_rs,"pedagio",True)
    carga=_n(carga_util_t,"carga_util_t")
    anuncio=_n(frete_anunciado_rs_t,"frete_anunciado_rs_t",True)
    custo=km*variavel+fixo+ped
    receita=anuncio*carga
    return {"custo_viagem_rs":custo,"custo_unitario_rs_t":custo/carga,
            "receita_potencial_anunciada_rs":receita,
            "saldo_teorico_rs":receita-custo,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_CUSTO_E_DIVULGACAO_DE_FRETE",
            "limitacao":"Frete anunciado não é cotação negociada ou contrato realizado; custo não inclui rubricas não informadas."}


def comparacao_intermodal(*,rodoviario_rs_t,ferroviario_rs_t,
                          transbordos_rs_t,trecho_complementar_rs_t,
                          restricoes_verificadas,fonte):
    """Custo técnico. Não alega disponibilidade de capacidade ferroviária."""
    rod=_n(rodoviario_rs_t,"rodoviario_rs_t",True)
    via=(_n(ferroviario_rs_t,"ferroviario_rs_t",True)
         +_n(transbordos_rs_t,"transbordos_rs_t",True)
         +_n(trecho_complementar_rs_t,"trecho_complementar_rs_t",True))
    if not isinstance(restricoes_verificadas,bool) or not restricoes_verificadas:
        raise DadoInvalido("alternativa ferroviária requer restrições de capacidade/rota verificadas")
    return {"rodoviario_rs_t":rod,"intermodal_rs_t":via,
            "diferenca_intermodal_menos_rodoviario_rs_t":via-rod,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_COMPARACAO_MODAL",
            "limitacao":"Somente custo nas hipóteses; não comprova contrato, capacidade ou SLA."}


def pressao_portuaria(*,volume_programado_t,capacidade_diaria_t,
                      toneladas_embarcadas_confirmadas_t,fonte):
    """Programação e realização têm naturezas distintas."""
    prog=_n(volume_programado_t,"volume_programado_t",True)
    cap=_n(capacidade_diaria_t,"capacidade_diaria_t")
    real=_n(toneladas_embarcadas_confirmadas_t,"embarcadas",True)
    return {"dias_teoricos_para_programacao":prog/cap,
            "volume_programado_t":prog,
            "volume_confirmado_embarcado_t":real,
            "fonte":_fonte(fonte),"classificacao":"PRESSAO_PROGRAMACAO_NAO_FILA_REAL",
            "limitacao":"Capacidade nominal não é throughput disponível; não derivar chegada, fundeio, espera ou exportação realizada do lineup."}


def comercio_exterior_recorte(*,exportacao_kg,exportacao_fob_usd,
                             importacao_kg,importacao_cif_usd,
                             periodo_ncm_uf_verificado,fonte):
    """FOB exportação e CIF importação são INCOTERMS e preços diferentes."""
    e=_n(exportacao_kg,"exportacao_kg",True)
    i=_n(importacao_kg,"importacao_kg",True)
    ef=_n(exportacao_fob_usd,"exportacao_fob_usd",True)
    ic=_n(importacao_cif_usd,"importacao_cif_usd",True)
    if not isinstance(periodo_ncm_uf_verificado,bool) or not periodo_ncm_uf_verificado:
        raise DadoInvalido("NCM, período e UF precisam ser compatíveis")
    return {"exportacao_t":e/1000,"importacao_t":i/1000,
            "saldo_fisico_t":(e-i)/1000,
            "valor_unitario_fob_exportacao_usd_t":ef*1000/e if e else None,
            "valor_unitario_cif_importacao_usd_t":ic*1000/i if i else None,
            "fonte":_fonte(fonte),"classificacao":"INDICADORES_COMEX_RECORTE",
            "limitacao":"Não comparar valor FOB com CIF como margem, nem inferir saldo de oferta e demanda municipal."}


def sensibilidade_macro(*,preco_base_rs_t,choque_cambio_fracao,
                        choque_preco_internacional_fracao,
                        elasticidade_cambio,elasticidade_preco,
                        fonte_calibracao):
    """Cenário de sensibilidade calibrado EXTERNAMENTE, sem afirmar causalidade."""
    p=_n(preco_base_rs_t,"preco_base_rs_t")
    fx=_assum(choque_cambio_fracao)
    choque=_assum(choque_preco_internacional_fracao)
    bfx=_assum(elasticidade_cambio)
    bp=_assum(elasticidade_preco)
    if fx<=-1 or choque<=-1:
        raise DadoInvalido("choque torna preço internacional/câmbio não positivo")
    final=p*(1+bfx*fx+bp*choque)
    if final<0:
        raise DadoInvalido("elasticidade gera preço negativo")
    return {"preco_cenario_rs_t":final,"variacao_rs_t":final-p,
            "elasticidade_cambio":bfx,"elasticidade_commodity":bp,
            "fonte_calibracao":_fonte(fonte_calibracao),
            "classificacao":"CENARIO_LINEAR_SENSIBILIDADE",
            "limitacao":"Elasticidade deve ser estimada/validada externamente; o cenário não atribui causalidade observada."}


def evento_geopolitico(*,evento_id,fator,cadeias_afetadas,
                     tipo_evidencia,fonte_id,publicacao,impactos_hipoteticos):
    fatores={"SANCAO","GUERRA","OPEP","CAMBIO","TARIFA","SECA","GREVE","RESTRICAO_COMERCIAL","DOENCA_ANIMAL"}
    if fator not in fatores or tipo_evidencia not in ("CONFIRMADO","RELATO","HIPOTESE"):
        raise DadoInvalido("fator/evidência sem classe controlada")
    if not isinstance(cadeias_afetadas,(list,tuple)) or not cadeias_afetadas or not all(isinstance(x,str) and x.strip() for x in cadeias_afetadas):
        raise DadoInvalido("cadeias explícitas obrigatórias")
    if not isinstance(impactos_hipoteticos,(list,tuple)) or not all(isinstance(x,str) and x.strip() for x in impactos_hipoteticos):
        raise DadoInvalido("mecanismos econômicos devem ser textos explícitos")
    try:d=datetime.fromisoformat(publicacao.replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:raise DadoInvalido("publicação inválida") from exc
    if d.tzinfo is None:raise DadoInvalido("fuso de publicação obrigatório")
    return {"evento_id":_fonte(evento_id),"fator":fator,
            "cadeias_afetadas":list(cadeias_afetadas),"evidencia":tipo_evidencia,
            "mecanismos_hipoteticos":list(impactos_hipoteticos),
            "fonte_id":_fonte(fonte_id),"publicacao":publicacao,
            "probabilidade":None,"impacto_preco_estimado":None,
            "classificacao":"GRAFO_DE_HIPOTESES_SEM_INFERENCIA_CAUSAL",
            "limitacao":"Notícia não confirma impacto no mercado; exige evidência posterior e backtest."}


def margem_processamento(*,materia_prima_t,
                        custo_materia_prima_rs_t,
                        produtos_saida,receita_precos_rs_t,
                        rendimentos_t_por_t,despesas_outros_rs,
                        fonte_parametros):
    """Balanço físico conservativo de insumo e coprods com unidades todas em t.

    Ex.: soja→farelo/óleo, mas não etanol litros e açúcar toneladas juntos.
    """
    materia=_n(materia_prima_t,"materia_prima_t")
    if not isinstance(produtos_saida,(list,tuple)) or not produtos_saida or len(set(produtos_saida))!=len(produtos_saida):
        raise DadoInvalido("produtos de saída ausentes/duplicados")
    if not isinstance(receita_precos_rs_t,dict) or not isinstance(rendimentos_t_por_t,dict) or (
        set(produtos_saida)!=set(receita_precos_rs_t) or set(produtos_saida)!=set(rendimentos_t_por_t)
    ):
        raise DadoInvalido("produtos, preços e rendimentos incompatíveis")
    soma=0.;receita=0.;volumes={}
    for produto in produtos_saida:
        frac=_n(rendimentos_t_por_t[produto],"rendimento",True)
        soma+=frac
        volumes[produto]=materia*frac
        receita+=volumes[produto]*_n(receita_precos_rs_t[produto],"preco",True)
    if soma>1+1e-9:
        raise DadoInvalido("produtos excedem a massa da matéria-prima")
    custo=materia*_n(custo_materia_prima_rs_t,"custo_materia_prima")+_n(despesas_outros_rs,"despesas",True)
    return {"saida_produto_t":volumes,"residuo_perdas_t":max(0,materia*(1-soma)),
            "receita_sintetica_rs":receita,"margem_contribuicao_rs":receita-custo,
            "fonte":_fonte(fonte_parametros),"classificacao":"CENARIO_MARGEM_PROCESSAMENTO",
            "limitacao":"Não é DRE, capacidade efetiva, lucro contábil ou balanço de produtos em litros."}
