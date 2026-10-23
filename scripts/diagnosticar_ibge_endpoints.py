"""Diagnostico estritamente contido de duas APIs oficiais IBGE.

Acesso read-only, 2 GETs no maximo, sem salvar payload nem expor dados.
"""
from __future__ import annotations
import json
import time

from nivon.coletores_dados_reais import _get
from nivon.coletores_agro_ibge_wdi import plano_ibge_pam


def main():
    urls=[
        ("IBGE_AGREGADOS",plano_ibge_pam(ano=2024,uf="MT")),
        ("IBGE_SIDRA","https://apisidra.ibge.gov.br/values/t/1612/n3/51/p/2024/v/214/c81/all"),
    ]
    out=[]
    for label,url in urls:
        start=time.monotonic()
        try:
            b,_=_get(url,max_bytes=900000,tipos={"application/json","text/json"})
            doc=json.loads(b)
            first=doc[0] if isinstance(doc,list) and doc else {}
            out.append({"endpoint":label,"http":"SUCESSO","bytes":len(b),
                "tipo_raiz":type(doc).__name__,
                "chaves_primeira_linha":list(first)[:20] if isinstance(first,dict) else [],
                "indicacao_fonte_valida":True})
        except Exception as exc:
            out.append({"endpoint":label,"http":"FALHOU",
                "erro":type(exc).__name__,"resumo":str(exc)[:140]})
        out[-1]["segundos_aproximados"]=round(time.monotonic()-start,1)
    print(json.dumps({"diagnostico":out,"homologacao":False},ensure_ascii=False,indent=2))
    return 0 if any(x["http"]=="SUCESSO" for x in out) else 2

if __name__=="__main__":
    raise SystemExit(main())
