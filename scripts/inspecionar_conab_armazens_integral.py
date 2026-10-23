"""Inspeção única do TXT completo de armazéns CONAB em runner efêmero.

Não escreve no repositório, não anexa arquivo, não publica linhas ou CNPJ.
Usa diretório temporário e limita bytes e tempo. Não faz retry/redirect.
"""
from __future__ import annotations
import argparse
import json
import tempfile
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import URLError, HTTPError

from nivon.conab_armazens import (
    LAYOUT_CONAB_SICARM_HEADER_V1, agregar_capacidade_local, ErroArmazens,
)
from nivon.qualidade_conab_armazens import verificar_consistencia_armazens

URL="https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt"
LIMITE=120_000_000

class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def executar():
    req=Request(URL,headers={"User-Agent":"NIVON/0.2 schema-audit-only",
                             "Accept":"text/plain,application/octet-stream"})
    try:
        with tempfile.TemporaryDirectory(prefix="nivon-conab-audit-") as d:
            arquivo=Path(d)/"ArmazensCadastrados.txt"
            with build_opener(_SemRedirect()).open(req,timeout=35) as res:
                if res.status!=200 or res.geturl()!=URL:
                    return {"estado":"STATUS_OU_REDIRECT_INESPERADO"}
                mime=res.headers.get("Content-Type","").split(";",1)[0].strip().lower()
                if mime not in ("text/plain","application/octet-stream","text/csv"):
                    return {"estado":"MIME_INCOMPATIVEL","mime":mime[:40]}
                size=int(res.headers.get("Content-Length","0") or "0")
                if size>LIMITE:return {"estado":"ARQUIVO_MAIOR_QUE_LIMITE"}
                soma=0
                with arquivo.open("xb") as out:
                    while True:
                        buf=res.read(min(262144,LIMITE+1-soma))
                        if not buf:break
                        soma+=len(buf)
                        if soma>LIMITE:return {"estado":"LIMITE_DE_BYTES_ATINGIDO"}
                        out.write(buf)
            try:
                dados=agregar_capacidade_local(arquivo,LAYOUT_CONAB_SICARM_HEADER_V1,
                    coletado_em="2026-10-19T20:00:00Z")
                ver=verificar_consistencia_armazens(dados)
            except (ErroArmazens,ValueError) as exc:
                # Erros genéricos do parser, sem qualquer valor original.
                return {"estado":"FALHA_CONTRATO_REAL","classe":type(exc).__name__,
                        "motivo":str(exc)[:120],"arquivo_bytes":soma}
            return {"estado":"ESTRUTURA_COMPLETA_CONSISTENTE_NAO_HOMOLOGADA",
                    "sha256_original":dados["sha256_original"],
                    "arquivo_bytes":soma,
                    "linhas":dados["linhas_validas"],
                    "municipios_agrupados":dados["municipios"],
                    "capacidade_total_t":dados["capacidade_total_t"],
                    "direitos_publicacao_autorizados":False,
                    "dataset_homologado":False}
    except (OSError,HTTPError,URLError,TimeoutError) as exc:
        return {"estado":"INDISPONIBILIDADE_DE_FONTE","classe":type(exc).__name__}

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--explicit-yes",action="store_true")
    a=ap.parse_args(argv)
    if not a.explicit_yes:
        print(json.dumps({"estado":"DESABILITADO_POR_PADRAO"}))
        return 2
    print(json.dumps(executar(),ensure_ascii=False))
    return 0  # Resultado diagnóstico não é homologação.

if __name__=="__main__":
    raise SystemExit(main())
