"""Diagnóstico de uma única consulta oficial Eurostat / FAOSTAT (sem persistência)."""
import argparse
import json
from nivon.eurostat_faostat_agro import consultar_eurostat, consultar_faostat


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: produção internacional, smoke pontual")
    p.add_argument("--fonte",required=True,choices=("eurostat","faostat"))
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado":"BLOQUEADO_SEM_EXECUTAR"}))
        return 2
    try:
        if args.fonte=="eurostat":
            d=consultar_eurostat(pais="FR",ano=2024,executar=True)
        else:
            d=consultar_faostat(pais="BRA",cultura="SOJA",ano=2023,executar=True)
        print(json.dumps({"estado":"CONSULTA_REAL_PONTUAL_SEM_PERSISTENCIA",
                          "fonte":args.fonte,"dataset":d["dataset_id"],
                          "n_registros":d["numero_observacoes"],
                          "hash":d["sha256_original"],
                          "publicacao_automatica":False},ensure_ascii=False))
        return 0
    except Exception as e:
        from nivon.eurostat_faostat_agro import ErroEstatisticasAgro
        print(json.dumps({"estado":"FALHA_VERIFICACAO","fonte":args.fonte,
                          "classe":type(e).__name__,
                          "motivo_sem_dados":str(e)[:150] if isinstance(e,ErroEstatisticasAgro) else "ERRO_REDE_OU_DESCONHECIDO"},
                         ensure_ascii=False))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
