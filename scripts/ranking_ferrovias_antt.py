"""Relatório de corredores ferroviários e comparação opcional com MDF-e.

Sem flags de escrita/Cloud. Staging SIADE deve ter bruto + manifesto SHA.
"""
from __future__ import annotations

import argparse
import json
import sys

from nivon.conciliacao_corredores_ferrovia import (
    ErroConciliacao, analisar_staging, quadro_staging,
)
from nivon.transporte_multimodal import ErroTransporte


def main(argv=None):
    p=argparse.ArgumentParser(description="Ranking ferroviário oficial ANTT por estação e mercadoria")
    p.add_argument("--staging",required=True)
    p.add_argument("--ano",type=int,required=True)
    p.add_argument("--competencia",required=True)
    p.add_argument("--uf-origem",default="MT")
    p.add_argument("--limite",type=int,default=30)
    p.add_argument("--banco-rodo",help="opcional, banco MDF-e importado não homologado")
    p.add_argument("--recorte-rodo",help="ID exato do universo da importação MDF-e")
    args=p.parse_args(argv)
    if bool(args.banco_rodo)!=bool(args.recorte_rodo):
        p.error("--banco-rodo e --recorte-rodo devem ser usados juntos")
    try:
        if args.banco_rodo:
            if args.uf_origem!="MT":
                p.error("quadro_staging usa UF de origem MT; filtrar outras UFs requer novo contrato")
            out=quadro_staging(args.staging,args.banco_rodo,ano=args.ano,
                               competencia=args.competencia,recorte=args.recorte_rodo,
                               limite=args.limite)
        else:
            out=analisar_staging(args.staging,ano=args.ano,competencia=args.competencia,
                                uf_origem=args.uf_origem,limite=args.limite)
        print(json.dumps(out,ensure_ascii=False,sort_keys=True))
        return 0
    except (ErroConciliacao,ErroTransporte,OSError,KeyError,ValueError) as exc:
        print(json.dumps({"estado":"FALHA_FONTE_OU_CONTRATO",
                          "tipo":type(exc).__name__},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
