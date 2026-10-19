"""Motores meteorológicos, agrometeorológicos e hidrológicos NIVON.

Dados de entrada explícitos; nenhum acesso a rede, inferência de chuva ou
declaração automática de navegabilidade. Um modelo não é observação.
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from .motores import DadoInvalido, numero_positivo


def _n(valor,nome,zero=False):
    return numero_positivo(valor,nome,aceita_zero=zero)


def _texto(x,nome):
    if not isinstance(x,str) or not x.strip():
        raise DadoInvalido(nome+": identificador/referência obrigatório")
    return x


def _fra(x,nome):
    a=_n(x,nome,True)
    if a>1:
        raise DadoInvalido(nome+": percentual deve ser fração [0,1]")
    return a


def chuva_anomalia(*,chuva_observada_mm,normal_periodo_mm,
                   periodo,estacao_fonte):
    """Anomalia simples contra climatologia do MESMO período; não é SPI."""
    obs=_n(chuva_observada_mm,"chuva_observada_mm",True)
    normal=_n(normal_periodo_mm,"normal_periodo_mm")
    return {"periodo":_texto(periodo,"periodo"),
            "desvio_mm":obs-normal,"anomalia_percentual":100*(obs/normal-1),
            "fonte_normal_climatologica":_texto(estacao_fonte,"estacao_fonte"),
            "classificacao":"DESVIO_DE_CHUVA_NAO_SPI",
            "limitacao":"Não é probabilidade de seca nem índice padronizado SPI; exige mesmo calendário, período, estação e climatologia."}


def graus_dia(*,temperaturas_diarias,temperatura_base_c,
              temperatura_teto_c=None,fonte=None):
    """Graus-dia sobre média diária; datas distintas e intervalos coerentes."""
    if not isinstance(temperaturas_diarias,(list,tuple)) or not temperaturas_diarias or len(temperaturas_diarias)>366:
        raise DadoInvalido("temperaturas de 1–366 dias")
    from math import isfinite
    if type(temperatura_base_c) not in (int,float) or not isfinite(temperatura_base_c):
        raise DadoInvalido("temperatura base inválida")
    if temperatura_teto_c is not None and (
        type(temperatura_teto_c) not in (int,float) or
        not isfinite(temperatura_teto_c) or temperatura_teto_c<=temperatura_base_c
    ):
        raise DadoInvalido("teto térmico inválido")
    visto=set();soma=0.;dias=0
    for item in temperaturas_diarias:
        if not isinstance(item,dict):
            raise DadoInvalido("item diário inválido")
        try:
            dia=date.fromisoformat(item["data"])
        except (KeyError,ValueError,TypeError) as exc:
            raise DadoInvalido("data meteorológica inválida") from exc
        if dia in visto:
            raise DadoInvalido("data duplicada")
        visto.add(dia)
        lo=item.get("tmin_c");hi=item.get("tmax_c")
        if any(type(v) not in (int,float) or not isfinite(v) for v in (lo,hi)) or lo>hi:
            raise DadoInvalido("Tmin/Tmax inválidos")
        media=(lo+hi)/2
        if temperatura_teto_c is not None:
            media=min(media,temperatura_teto_c)
        soma+=max(0,media-temperatura_base_c)
        dias+=1
    return {"graus_dia_acumulados_c_dia":soma,"dias":dias,
            "fonte":_texto(fonte,"fonte"),"classificacao":"SOMA_TERMICA_MODELO_SIMPLES",
            "limitacao":"Não determina produtividade nem fase fenológica sem parâmetros da cultivar e data de plantio."}


def balanco_hidrico_solo(*,dias,capacidade_agua_mm,
                        agua_inicial_mm,fonte_eto,fonte_precipitacao):
    """Balde diário conservativo. ETo e Kc fornecidos, NÃO calculados.

    Chuva entra; evapotranspiração real limitada pela água disponível;
    excesso percola/escoa (sem separar processos), déficit não vira zero.
    """
    cap=_n(capacidade_agua_mm,"capacidade_agua_mm")
    agua=_n(agua_inicial_mm,"agua_inicial_mm",True)
    if agua>cap or not isinstance(dias,(list,tuple)) or not 1<=len(dias)<=366:
        raise DadoInvalido("capacidade, água inicial ou janela inválidas")
    vistos=set();registros=[];prev=None
    for d in dias:
        if not isinstance(d,dict):
            raise DadoInvalido("dia inválido")
        try: stamp=date.fromisoformat(d["data"])
        except (KeyError,ValueError,TypeError) as exc: raise DadoInvalido("data inválida") from exc
        if stamp in vistos or (prev is not None and (stamp-prev).days!=1):
            raise DadoInvalido("datas repetidas, fora de ordem ou com lacunas")
        vistos.add(stamp);prev=stamp
        chuva=_n(d.get("chuva_mm"),"chuva_mm",True)
        eto=_n(d.get("eto_mm"),"eto_mm",True)
        kc=_n(d.get("kc"),"kc",True)
        if kc>3:
            raise DadoInvalido("Kc fora do intervalo de proteção do motor")
        etc=eto*kc
        oferta=agua+chuva
        eta=min(etc,oferta)
        residual=oferta-eta
        excedente=max(0,residual-cap)
        agua=min(cap,residual)
        registros.append({"data":d["data"],"et_cultura_potencial_mm":etc,
                          "et_atendida_mm":eta,"deficit_et_mm":etc-eta,
                          "excedente_hidrico_mm":excedente,"agua_fim_mm":agua})
    return {"agua_final_mm":agua,"deficit_acumulado_mm":sum(x["deficit_et_mm"] for x in registros),
            "excedente_acumulado_mm":sum(x["excedente_hidrico_mm"] for x in registros),
            "dias":registros,"fonte_eto":_texto(fonte_eto,"fonte_eto"),
            "fonte_chuva":_texto(fonte_precipitacao,"fonte_precipitacao"),
            "classificacao":"CENARIO_BALANCO_HIDRICO_BALDE",
            "limitacao":"Não é previsão de produtividade, vazão, erosão nem irrigação recomendada; requer Kc/ET0 e solo locais."}


def janela_chuva_operacao(*,previsoes_mm_por_dia,limiar_diario_mm,
                         fonte_previsao,emitida_em):
    """Conta gatilhos definidos pelo operador; não estima risco de trânsito."""
    if not isinstance(previsoes_mm_por_dia,(list,tuple)) or not 1<=len(previsoes_mm_por_dia)<=16:
        raise DadoInvalido("janela de previsão entre 1 e 16 dias")
    limiar=_n(limiar_diario_mm,"limiar_diario_mm")
    valores=[_n(v,"chuva_prevista_mm",True) for v in previsoes_mm_por_dia]
    return {"dias_acima_do_limiar":sum(v>=limiar for v in valores),
            "chuva_prevista_acumulada_mm":sum(valores),
            "limiar_informado_mm":limiar,"fonte":_texto(fonte_previsao,"fonte"),
            "emissao":_texto(emitida_em,"emissao"),
            "classificacao":"SINAL_PREVISTO_OPERACIONAL",
            "limitacao":"Chuva prevista não é chuva observada nem prova condição da rodovia ou janela de colheita."}


def anomalia_nivel_rio(*,estacao_id,cota_atual_cm,
                      cota_referencia_mesma_epoca_cm,fonte_cota,
                      mes_referencia):
    """Cota pode ser negativa em referencial de régua; valores explícitos."""
    if any(type(x) not in (int,float) or not isfinite(x) for x in
           (cota_atual_cm,cota_referencia_mesma_epoca_cm)):
        raise DadoInvalido("cota/referência da régua inválidas")
    return {"estacao_id":_texto(estacao_id,"estacao_id"),
            "diferenca_cota_cm":cota_atual_cm-cota_referencia_mesma_epoca_cm,
            "cota_observada_cm":cota_atual_cm,
            "referencia_mes":_texto(mes_referencia,"mes_referencia"),
            "fonte":_texto(fonte_cota,"fonte"),
            "classificacao":"ANOMALIA_COTA_ESTACAO",
            "limitacao":"Cota de régua não é profundidade do canal, vazão ou navegabilidade."}


def anomalia_vazao(*,vazao_observada_m3_s,normal_mes_m3_s,
                   estacao_id,fonte):
    v=_n(vazao_observada_m3_s,"vazao_observada_m3_s",True)
    n=_n(normal_mes_m3_s,"normal_mes_m3_s")
    return {"estacao_id":_texto(estacao_id,"estacao_id"),
            "desvio_vazao_m3_s":v-n,"anomalia_percentual":100*(v/n-1),
            "fonte":_texto(fonte,"fonte"),"classificacao":"ANOMALIA_VAZAO",
            "limitacao":"Vazão e nível têm relações locais não lineares; não converter em calado."}


def folga_calado_hipotetica(*,profundidade_canal_m,calado_embarcacao_m,
                           folga_minima_abaixo_quilha_m,
                           fonte_sondagem,referencia_vertical):
    """Triagem geométrica, não liberação de navegação (correntes/talvegues não modelados)."""
    p=_n(profundidade_canal_m,"profundidade_canal_m")
    c=_n(calado_embarcacao_m,"calado_embarcacao_m")
    f=_n(folga_minima_abaixo_quilha_m,"folga_minima_abaixo_quilha_m",True)
    livre=p-c-f
    return {"margem_geometrica_m":livre,"profundidade_insuficiente_na_hipotese":livre<0,
            "fonte_sondagem":_texto(fonte_sondagem,"fonte_sondagem"),
            "datum":_texto(referencia_vertical,"referencia_vertical"),
            "classificacao":"TRIAGEM_GEOMETRICA_SEM_AUTORIZACAO_DE_NAVEGACAO",
            "limitacao":"Sem batimetria atual, datum consistente, maré, corrente, manobras e autoridade hidroviária, não declarar navegabilidade."}
