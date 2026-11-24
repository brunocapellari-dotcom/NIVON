"""Smoke HTTP real do contêiner NIVON, sem GCP/BigQuery ou números falsos.

Usar depois de docker run local (127.0.0.1). Exercita portas, respostas,
bloqueio de POST, cabeçalhos, interface e indisponibilidade sanitizada.
Não simula dados reais e não habilita acesso público/IAM.
"""
from __future__ import annotations

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler


def _http(opener, url, *, method="GET"):
    request=Request(url,method=method)
    try:
        with opener.open(request, timeout=3) as response:
            return response.status, response.headers, response.read(1_000_000)
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read(1_000_000)


def executar(*, url: str, espera_segundos: int=40) -> dict:
    if not (url.startswith("http://127.0.0.1:")
            and not any(ch in url for ch in ("@", "?", "#"))):
        raise ValueError("smoke HTTP exige loopback IPv4 e porta explícita")
    url=url.rstrip("/")
    client=build_opener(ProxyHandler({}))
    deadline=time.monotonic()+espera_segundos
    while True:
        try:
            codigo,headers,body=_http(client,url+"/healthz")
            if codigo==200:
                break
        except (URLError,TimeoutError,OSError):
            pass
        if time.monotonic()>=deadline:
            raise AssertionError("servidor HTTP nao respondeu no prazo")
        time.sleep(.5)
    assert headers.get("Cache-Control")=="no-store"
    assert headers.get("X-Content-Type-Options")=="nosniff"
    assert headers.get("X-Frame-Options")=="DENY"
    assert "frame-ancestors 'none'" in headers.get("Content-Security-Policy","")
    assert json.loads(body)=={"estado":"PROCESSO_ATIVO"}

    code,h,web=_http(client,url+"/")
    assert code==200 and h.get_content_type()=="text/html"
    assert b"NIVON" in web and b"/api/v1/ferrovia" in web
    assert b"noindex,nofollow,noarchive" in web

    code,_,unavailable=_http(client,url+"/api/v1/ferrovia")
    assert code==503, f"sem credenciais nao deve devolver 200: {code}"
    assert json.loads(unavailable)=={
        "estado":"FONTE_TEMPORARIAMENTE_INDISPONIVEL",
    }
    for forbidden in (b"Traceback",b"permission_denied",b"serviceAccount",
                      b"google.auth",b"SELECT ",b"nivon_raw"):
        assert forbidden not in unavailable

    code,_,blocked=_http(client,url+"/api/v1/ferrovia",method="POST")
    assert code==405 and json.loads(blocked)=={"erro":"SOMENTE_LEITURA"}
    code,_,unknown=_http(client,url+"/rota-inexistente")
    assert code==404 and json.loads(unknown)=={"erro":"ROTA_INEXISTENTE"}
    return {
        "estado":"CONTAINER_TERMINAL_SMOKE_OK",
        "healthz":"HTTP_200_PROCESSO_ATIVO_NAO_FONTE",
        "interface":"HTTP_200_SEM_DADOS_EMBUTIDOS",
        "ferrovia_sem_identidade":"HTTP_503_SEM_VAZAMENTO",
        "post":"HTTP_405","rota_inexistente":"HTTP_404",
        "origem_restrita":"127.0.0.1",
        "dados_reais_consultados":False,"cloud_run_deploy":False,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="http://127.0.0.1:18765")
    args=parser.parse_args()
    print(json.dumps(executar(url=args.url),ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
