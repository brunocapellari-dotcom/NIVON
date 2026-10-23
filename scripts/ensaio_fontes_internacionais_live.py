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
from nivon.coletores_dados_reais import CCEE_PACKAGE, _get, _parse_ckan
from urllib.parse import urlsplit
from nivon.coletores_dados_reais import CANADA_CSV
import io, csv

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
                diagnostico={}
                if fonte == "CAN_GRAINS_WEEKLY":
                    try:
                        raw, _mime = _get(CANADA_CSV.format(safra="2026-27"),
                            tipos={"text/csv","text/plain","application/octet-stream","application/csv"})
                        leitor=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
                        vistos=[]
                        for n, item in enumerate(leitor):
                            valor=str(item.get("Week Ending Date",""))[:40]
                            if valor not in vistos: vistos.append(valor)
                            if n >= 50 or len(vistos)>=6: break
                        diagnostico={"datas_amostra":vistos}
                    except Exception as sub_exc:
                        diagnostico={"diagnostico":type(sub_exc).__name__}
                resultado.append({"fonte":fonte,"http":"FALHOU",
                  "tipo_erro":type(exc).__name__,"mensagem":str(exc)[:150],
                  "diagnostico":diagnostico})
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
            dado_csv=Path(out["arquivo_raw"]).read_bytes()[:5000]
            csv_txt=dado_csv.decode("utf-8-sig",errors="replace").splitlines()
            resultado.append({"fonte":"BR_CCEE_PLD_CSV_2026","http":"SUCESSO",
                 "estado":out.get("estado"),"observacoes":out.get("novas_observacoes"),
                 "bytes_raw":out.get("arquivo_raw") is not None,
                 "cabecalho_amostra":csv_txt[0][:600] if csv_txt else None,
                 "linha_dados_amostra":csv_txt[1][:400] if len(csv_txt)>1 else None})
        except Exception as exc:
            diagnostico={}
            try:
                payload, _ = _get(CCEE_PACKAGE,max_bytes=1_500_000,
                                tipos={"application/json","text/json"})
                _, recursos = _parse_ckan(payload)
                alvo=next((v for v in recursos if v.get("id")=="3f279d6b-1069-42f7-9b0a-217b084729c4"),{})
                uri=urlsplit(str(alvo.get("url","")))
                diagnostico={"host":uri.hostname,"path_prefix":uri.path[:120],
                    "has_query":bool(uri.query),"format":alvo.get("format")}
            except Exception as sub_exc:
                diagnostico={"erro_inspecao":type(sub_exc).__name__}
            resultado.append({"fonte":"BR_CCEE_PLD_CSV_2026","http":"FALHOU",
                 "tipo_erro":type(exc).__name__,"mensagem":str(exc)[:150],
                 "locator":diagnostico})
    print(json.dumps({"ensaios":resultado,"homologacao":"NAO","dados_fora_do_banco":True},
          ensure_ascii=False,indent=2))
    return 0 if all(x["http"]=="SUCESSO" for x in resultado) else 2

if __name__=="__main__":
    raise SystemExit(main())
