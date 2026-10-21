"""Executor único de consulta pontual NIVON; por padrão SEM rede.

Exemplos (somente após habilitação e revisão de termos):
 python -m nivon.hidromet_pontual_cli --fonte nasa_power --latitude -12.5 --longitude -55.7 --inicio 2026-10-01 --fim 2026-10-02 --live
 python -m nivon.hidromet_pontual_cli --fonte glofas --latitude -12.5 --longitude -55.7 --dias 3 --live
Só imprime agregados sanitizados, jamais payload original nem token.
"""
from __future__ import annotations

import argparse
import json
from .hidromet_publico_global import (
    ErroHidrometPublico, consultar_nasa_power, consultar_openmeteo, consultar_glofas,
)
from .inmet_estacoes_publicas import ErroCatalogoINMET, consultar_catalogo
from .cptec_previsao_brasilapi import ErroPrevisaoCPTEC, consultar_previsao
from .cemaden_ped import ErroCemaden, consultar_acumulados

_FONTES=("inmet_estacoes","cptec_brasilapi","nasa_power","openmeteo","glofas","cemaden")


def executar(argv=None, *, transportes=None):
    parser=argparse.ArgumentParser(description="NIVON — hidrometeorologia pontual, sem rede por padrão")
    parser.add_argument("--fonte",choices=_FONTES,required=True)
    parser.add_argument("--latitude",type=float)
    parser.add_argument("--longitude",type=float)
    parser.add_argument("--inicio")
    parser.add_argument("--fim")
    parser.add_argument("--dias",type=int,default=3)
    parser.add_argument("--modo",choices=("previsao","historico"),default="previsao")
    parser.add_argument("--tipo",choices=("T","M"),default="T")
    parser.add_argument("--codigo-cptec",type=int)
    parser.add_argument("--codigo-ibge")
    parser.add_argument("--live",action="store_true",help="autorizar 1 GET (CEMADEN requer JWT)")
    args=parser.parse_args(argv)
    if not args.live:
        return {"fonte":args.fonte,"estado":"REDE_DESATIVADA",
                "homologado":False,"publicavel":False,"coleta_agendada":False}
    transportes=transportes or {}
    transporte=transportes.get(args.fonte)
    if args.fonte=="inmet_estacoes":
        result=consultar_catalogo(tipo=args.tipo,habilitar_rede=True,transporte=transporte)
    elif args.fonte=="cptec_brasilapi":
        result=consultar_previsao(codigo_cptec=args.codigo_cptec,dias=args.dias,
                                  habilitar_rede=True,transporte=transporte)
    elif args.fonte=="nasa_power":
        result=consultar_nasa_power(latitude=args.latitude,longitude=args.longitude,
                                    inicio=args.inicio,fim=args.fim,habilitar_rede=True,
                                    transporte=transporte)
    elif args.fonte=="openmeteo":
        result=consultar_openmeteo(latitude=args.latitude,longitude=args.longitude,
                                   modo=args.modo,dias=args.dias,inicio=args.inicio,
                                   fim=args.fim,habilitar_rede=True,transporte=transporte)
    elif args.fonte=="glofas":
        result=consultar_glofas(latitude=args.latitude,longitude=args.longitude,
                                dias=args.dias,habilitar_rede=True,transporte=transporte)
    else:
        result=consultar_acumulados(codigo_ibge=args.codigo_ibge,
                                    habilitar_rede=True,transporte=transporte)
    rows = result if isinstance(result,list) else result.get("registros",result.get("previsoes",[]))
    if not isinstance(rows,list):
        raise ValueError("formato de resultado interno inválido")
    return {"fonte":args.fonte, "estado":"RESPOSTA_RECEBIDA_SEM_HOMOLOGACAO" if rows else "SEM_REGISTROS",
            "quantidade_registros":len(rows), "homologado":False,
            "publicavel":False,"coleta_agendada":False}


def main(argv=None):
    try:
        result=executar(argv)
    except (ErroHidrometPublico, ErroCatalogoINMET, ErroPrevisaoCPTEC, ErroCemaden,
            TypeError, ValueError, PermissionError):
        result={"estado":"CONSULTA_NAO_VALIDADA","homologado":False,
                "publicavel":False,"coleta_agendada":False}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["estado"] in ("REDE_DESATIVADA","RESPOSTA_RECEBIDA_SEM_HOMOLOGACAO","SEM_REGISTROS") else 2


if __name__=="__main__":
    raise SystemExit(main())
