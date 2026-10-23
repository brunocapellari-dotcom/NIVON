"""Ensaio HTTP controlado IBGE PAM + World Bank WDI. Sem Cloud ou secrets.

Uma requisição por fonte/ano, dados armazenados apenas no diretório efêmero.
O ensaio não estabelece licença comercial ou ativação na produção.
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from datetime import datetime,timezone

from nivon.coletores_agro_ibge_wdi import coletar_ibge_pam, coletar_wdi

def main():
    resultados=[]
    with tempfile.TemporaryDirectory(prefix="nivon-agro-ibge-wdi-") as tmp:
        base=Path(tmp)
        queries=[
           ("IBGE_PAM_MT_2024",lambda:coletar_ibge_pam(ano=2024,uf="MT",
              banco=base/"data.sqlite",raw_dir=base/"raw",executar=True)),
           ("WDI_BRA_CEREAIS_2020_2024",lambda:coletar_wdi(
              pais="BRA",indicador="AG.YLD.CREL.KG",inicio=2020,fim=2024,
              banco=base/"data.sqlite",raw_dir=base/"raw",executar=True))
        ]
        for name,fn in queries:
            try:
                r=fn()
                resultados.append({"fonte":name,"http":"SUCESSO",
                   "estado":r["estado"],"linhas":r["novas_observacoes"],
                   "sha256":r["sha256"],"dados_armazenados":"CI_TEMPORARIO"})
            except Exception as exc:
                resultados.append({"fonte":name,"http":"FALHOU",
                  "erro":type(exc).__name__,"resumo":str(exc)[:240]})
    print(json.dumps({"ensaios":resultados,"homologacao_cloud":False,
                      "persistencia_cloud":False},ensure_ascii=False,indent=2))
    return 0 if all(x["http"]=="SUCESSO" for x in resultados) else 2

if __name__=="__main__":
    raise SystemExit(main())
