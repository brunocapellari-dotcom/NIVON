"""Diagnóstico HEAD mínimo do tamanho ZARC oficial. Sem download."""
import argparse
import json
from urllib.request import Request, build_opener

from nivon.zarc_stream_mt import URL, MAX_DOWNLOAD, _NoRedirect
from nivon.fontes_abertas_lote import consultar as consultar_catalogo

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado":"REDE_OFF","bytes_transferidos":0}))
        return 2
    try:
        with build_opener(_NoRedirect()).open(
            Request(URL,method="HEAD",headers={"User-Agent":"NIVON/0.1 pesquisa-nao-comercial"}),
            timeout=15) as resp:
            mime=str(resp.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
            length=resp.headers.get("Content-Length")
            size=int(length) if length and length.isdecimal() else None
            valid = int(resp.status)==200 and resp.geturl()==URL
            info={"status_http":resp.status,"mime":mime,"tamanho_declarado_bytes":size,
                  "max_download_definido_bytes":MAX_DOWNLOAD,
                  "maior_que_limite":size is not None and size>MAX_DOWNLOAD,
                  "respondeu_origem_exata":valid,
                  "bytes_corpo_baixados":0}
            cat = consultar_catalogo('MAPA_ZARC', executar=True)
            item = next((r for r in cat['recursos'] if r['id'].lower()=='139e5a60-1f43-4cc8-aeab-a35dbbf816c0'), None)
            info['tamanho_catalogo_bytes'] = item.get('tamanho_declarado_bytes') if item else None
            info['recurso_encontrado_no_catalogo'] = item is not None
            print(json.dumps(info,sort_keys=True))
            return 0 if valid else 1
    except Exception as exc:
        print(json.dumps({"estado":"HEAD_NAO_VALIDADO","tipo":type(exc).__name__}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
