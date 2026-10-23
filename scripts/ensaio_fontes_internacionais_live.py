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
from nivon.coletor_granos_ar import coletar_granos_ar

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
                   "licenca":dado.get("licenca"),
                   "recurso_csv_amostra":dado.get("csv_resources",[])[:15],
                   "notas":dado.get("notas")})
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
        for endpoint in ("status","pizarra"):
            try:
                out=coletar_granos_ar(endpoint=endpoint,
                    banco=base/"smoke.sqlite",raw_dir=base/"raw",executar=True)
                resultado.append({"fonte":"ARG_GRANOS_AR/"+endpoint,"http":"SUCESSO",
                   "estado":out.get("estado"),"observacoes":out.get("novas_observacoes")})
            except Exception as exc:
                resultado.append({"fonte":"ARG_GRANOS_AR/"+endpoint,"http":"FALHOU",
                   "tipo_erro":type(exc).__name__,"mensagem":str(exc)[:150]})
        try:
            out=executar_coleta(fonte="BR_CCEE_PLD",executar=True,
               recurso_id="3f279d6b-1069-42f7-9b0a-217b084729c4",
               banco=base/"smoke.sqlite",raw_dir=base/"raw")
            resultado.append({"fonte":"BR_CCEE_PLD_CSV_2026","http":"SUCESSO",
                 "estado":out.get("estado"),"observacoes":out.get("novas_observacoes"),
                 "bytes_raw":out.get("arquivo_raw") is not None})
        except Exception as exc:
            resultado.append({"fonte":"BR_CCEE_PLD_CSV_2026","http":"FALHOU",
                 "tipo_erro":type(exc).__name__,"mensagem":str(exc)[:150]})
    print(json.dumps({"ensaios":resultado,"homologacao":"NAO","dados_fora_do_banco":True},
          ensure_ascii=False,indent=2))
    return 0 if all(x["http"]=="SUCESSO" for x in resultado) else 2

if __name__=="__main__":
    raise SystemExit(main())
