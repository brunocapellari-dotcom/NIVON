"""CLI sem segredos para GET Range de 1 byte, uma consulta manual."""
import argparse
import json
from nivon.zarc_range_size import consultar_tamanho

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if args.executar is not True:
        print(json.dumps({"estado":"REDE_OFF","bytes_transferidos":0}))
        return 2
    try:
        result=consultar_tamanho(executar=True)
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"estado":"HTTP_OU_CONTRATO_NAO_VALIDADO",
                          "erro_tipo":type(exc).__name__}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
