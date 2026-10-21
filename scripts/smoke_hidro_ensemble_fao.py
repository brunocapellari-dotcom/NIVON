"""Verificação manual de quatro bases públicas sem guardar dados/séries."""
import argparse
import json
from nivon.open_meteo_hidro_ensemble import consultar_vazao, consultar_ensemble
from nivon.fao_fpma_publica import consultar_catalogo, consultar_precos


def main(argv=None):
    ap=argparse.ArgumentParser(description="NIVON: uma consulta grátis sem banco")
    ap.add_argument("--fonte",choices=("flood","ensemble","fao_catalogo","fao_precos"),required=True)
    ap.add_argument("--executar",action="store_true")
    ap.add_argument("--uuid",help="UUID série FAO, sem chave privada")
    args=ap.parse_args(argv)
    if not args.executar:
        print(json.dumps({"status":"BLOQUEADO_SEM_FLAG"}))
        return 2
    try:
        if args.fonte=="flood":
            o=consultar_vazao(latitude=-8.76,longitude=-63.9,dias=3,executar=True)["dados"]
        elif args.fonte=="ensemble":
            o=consultar_ensemble(latitude=-13.0,longitude=-56.0,dias=1,executar=True)["dados"]
        elif args.fonte=="fao_catalogo":
            o=consultar_catalogo(pais="BRA",executar=True)["dados"]
        else:
            if args.uuid is None:
                ap.error("--uuid FAO obrigatório")
            o=consultar_precos(serie_uuid=args.uuid,executar=True)["dados"]
    except Exception as exc:
        # Não expor URLs externas nem valores de preços no log público.
        from nivon.open_meteo_hidro_ensemble import ErroAgroClimaAberto
        motivo=str(exc)[:120] if isinstance(exc,ErroAgroClimaAberto) else "OUTRO_ERRO"
        if args.fonte=="ensemble" and isinstance(exc,ErroAgroClimaAberto):
            try:
                from nivon.open_meteo_hidro_ensemble import planejar_ensemble
                from nivon.apis_gratuitas_execucao import _obter_json
                import json as _json
                u=planejar_ensemble(latitude=-13.0,longitude=-56.0,dias=1)
                o=_json.loads(_obter_json(u,recurso="open_ensemble",executar=True)["bytes"])
                print(_json.dumps({"schema_hourly":sorted(o.get("hourly",{})),
                                   "schema_units":sorted(o.get("hourly_units",{}))},ensure_ascii=False))
            except Exception:
                print("SCHEMA_NOT_AVAILABLE")
        print(json.dumps({"status":"FALHA","fonte":args.fonte,
                          "tipo_erro":type(exc).__name__,"motivo":motivo}))
        return 1
    resumo={"status":"CONSULTA_REAL_PONTUAL_SEM_PERSISTENCIA",
            "fonte":args.fonte,"dataset":o["dataset_id"],
            "quantidade":o.get("quantidade",o.get("numero_membros",0)),
            "sha256":o["sha256_original"],
            "liberada_publicacao":False}
    print(json.dumps(resumo,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
