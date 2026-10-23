"""Diagnóstico SEM payload para dois endpoints públicos de INMET e BrasilAPI.

Somente duas URLs HTTPS fixas, uma consulta a cada execução --live.
Nunca inclui raw JSON, URL de token ou dados de sensor nos logs.
"""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener


URLS={
    "inmet":"https://apitempo.inmet.gov.br/estacoes/T",
    "cptec":"https://brasilapi.com.br/api/cptec/v1/clima/previsao/244/3",
}
MAX_BYTES=2_500_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def diagnosticar(fonte, *, habilitar_rede=False, transporte=None):
    if fonte not in URLS:
        raise ValueError("fonte não permitida")
    if not habilitar_rede:
        return {"fonte":fonte,"estado":"REDE_DESATIVADA"}
    opener=transporte or build_opener(_NoRedirect)
    req=Request(URLS[fonte],method="GET",headers={"Accept":"application/json"})
    try:
        with opener.open(req,timeout=12) as res:
            status=res.status
            content_type=res.headers.get("Content-Type","") if hasattr(res,"headers") else ""
            data=res.read(MAX_BYTES+1)
    except HTTPError as e:
        return {"fonte":fonte,"estado":"HTTP_NAO_VALIDADO","codigo_http":int(e.code)}
    except (URLError,OSError):
        return {"fonte":fonte,"estado":"TRANSPORTE_NAO_VALIDADO"}
    if len(data)>MAX_BYTES:
        return {"fonte":fonte,"estado":"RESPOSTA_GRANDE_DEMAIS","limite_bytes":MAX_BYTES}
    try:
        parsed=json.loads(data.decode("utf-8-sig"))
    except (ValueError,UnicodeError):
        return {"fonte":fonte,"estado":"RESPOSTA_NAO_JSON","codigo_http":status,
                "tipo_conteudo":content_type.split(";")[0][:60]}
    result={"fonte":fonte,"estado":"JSON_RETORNADO","codigo_http":status,
            "bytes_resposta":len(data),"tipo_raiz":type(parsed).__name__}
    if isinstance(parsed,dict):
        result["chaves_raiz"]=sorted(str(k) for k in parsed.keys())[:14]
        c=parsed.get("clima")
        if isinstance(c,list):
            result["numero_dias"]=len(c)
            result["chaves_primeiro_dia"]=sorted(str(k) for k in c[0].keys())[:14] if c and isinstance(c[0],dict) else []
    elif isinstance(parsed,list):
        result["registros"]=len(parsed)
        if parsed and isinstance(parsed[0],dict):
            result["chaves_primeiro_registro"]=sorted(str(k) for k in parsed[0].keys())[:24]
    return result


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--fonte",choices=tuple(URLS),required=True)
    p.add_argument("--live",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(diagnosticar(args.fonte,habilitar_rede=args.live),ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
