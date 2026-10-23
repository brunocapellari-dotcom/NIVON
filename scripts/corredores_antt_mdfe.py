"""CLI read-only: rankings por recorte de MDF-e e polo intermodal."""
from __future__ import annotations
import argparse
import json
import sys
from nivon.inteligencia_corredores import consultar_corredores, ErroCorredor

def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: corredores rodoviários candidatos a portos/terminais")
    p.add_argument("--db",required=True)
    p.add_argument("--recorte",required=True)
    p.add_argument("--competencia",required=True)
    p.add_argument("--limite",type=int,default=100)
    p.add_argument("--somente-destino",action="store_true")
    args=p.parse_args(argv)
    try:
        doc=consultar_corredores(args.db,recorte=args.recorte,
                                  competencia=args.competencia,limite=args.limite)
        if args.somente_destino:
            doc["corredores"]=[x for x in doc["corredores"] if x["sentido"]=="DESTINO"]
        print(json.dumps(doc,ensure_ascii=False,indent=2))
        return 0
    except (ErroCorredor,OSError) as exc:
        print(json.dumps({"estado":"ERRO_NO_RECORTE","tipo":type(exc).__name__},
                         ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
