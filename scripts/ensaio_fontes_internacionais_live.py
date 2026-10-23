"""Diagnóstico HTTP real e contido das três fontes. Não agenda/publica nada.

Executar em runner CI sob opção explícita. Nunca descobre links terceiros.
"""
from __future__ import annotations
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from nivon.coletores_dados_reais import executar_coleta
from nivon.coletor_bcra_v4 import coletar_bcra

def main():
    # Data antiga e delimitada, sem depender de uma cotação no dia corrente.
    inicio="2026-09-01"
    fim="2026-09-05"
    testes=[
      ("ARG_SERIES_CAMBIO",{"inicio":inicio,"fim":fim}),
      ("CAN_GRAINS_WEEKLY",{"safra":"2026-27"}),
      ("BR_CCEE_PLD",{}),
    ]
    resultado=[]
    with tempfile.TemporaryDirectory(prefix="nivon-smoke-") as tmp:
        base=Path(tmp)
        for fonte,params in testes:
            try:
                dado=executar_coleta(fonte=fonte,executar=True,banco=base/"smoke.sqlite",
                        raw_dir=base/"raw",**params)
                resultado.append({"fonte":fonte,"http":"SUCESSO",
                   "estado":dado.get("estado"),
                   "observacoes":dado.get("novas_observacoes"),
                   "licenca":dado.get("licenca")})
            except Exception as exc:
                resultado.append({"fonte":fonte,"http":"FALHOU",
                  "tipo_erro":type(exc).__name__,"mensagem":str(exc)[:150]})
        try:
            resp=coletar_bcra(inicio="2026-09-01",fim="2026-09-05",
                        banco=base/"smoke.sqlite",raw_dir=base/"raw",executar=True)
            resultado.append({"fonte":"ARG_BCRA","http":"SUCESSO",
                "estado":resp.get("estado"),"observacoes":resp.get("novas_observacoes")})
        except Exception as exc:
            resultado.append({"fonte":"ARG_BCRA","http":"FALHOU",
                "tipo_erro":type(exc).__name__,"mensagem":str(exc)[:150]})
    print(json.dumps({"ensaios":resultado,"homologacao":"NAO","dados_fora_do_banco":True},
          ensure_ascii=False,indent=2))
    return 0 if all(x["http"]=="SUCESSO" for x in resultado) else 2

if __name__=="__main__":
    raise SystemExit(main())
