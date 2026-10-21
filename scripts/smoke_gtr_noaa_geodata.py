"""Consulta UMA fonte pública do lote GTR/NOAA/Pink Sheet/ESA/JRC.

Nenhuma consulta sem --executar; não salva valores, arquivos ou imagens.
"""
from __future__ import annotations

import argparse
import json

from nivon.planilhas_publicas_xlsx import consultar_planilha
from nivon.noaa_mei_v2 import consultar_mei_v2
from nivon.georaster_catalogos import consultar_esa_tile, consultar_jrc_wmts


PLANILHAS = {
    "gtr_frete": "USDA_AMS_GTR_FRETE_MULTIMODAL",
    "gtr_precos": "USDA_AMS_GTR_PRECO_BASIS_EXPORT",
    "pinksheet": "WB_PINK_SHEET_COMMODITIES",
}


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: smoke real pontual (sem persistência)")
    p.add_argument("--fonte", choices=(*PLANILHAS, "mei", "esa", "jrc"), required=True)
    p.add_argument("--executar", action="store_true")
    p.add_argument("--latitude", type=float)
    p.add_argument("--longitude", type=float)
    a = p.parse_args(argv)
    if not a.executar:
        print(json.dumps({"estado": "NAO_EXECUTADO_SEM_FLAG"}))
        return 2
    try:
        if a.fonte in PLANILHAS:
            dado = consultar_planilha(dataset_id=PLANILHAS[a.fonte], executar=True)["dados"]
            quantidade = sum(s["n_linhas"] for s in dado["abas"])
        elif a.fonte == "mei":
            dado = consultar_mei_v2(executar=True)["dados"]
            quantidade = dado["quantidade"]
        elif a.fonte == "jrc":
            dado = consultar_jrc_wmts(executar=True)["dados"]
            quantidade = dado["quantidade_camadas"]
        else:
            if a.latitude is None or a.longitude is None:
                p.error("--latitude e --longitude são necessárias para ESA")
            dado = consultar_esa_tile(latitude=a.latitude, longitude=a.longitude,
                                      executar=True)
            quantidade = 1
    except Exception as exc:
        print(json.dumps({"estado": "FALHA_HOMOLOGACAO",
                          "fonte": a.fonte, "classe_erro": type(exc).__name__}))
        return 1
    print(json.dumps({
        "estado": "CONSULTA_PONTUAL_SEM_PERSISTENCIA",
        "fonte": a.fonte, "dataset": dado["dataset_id"],
        "quantidade_itens_estrutura": quantidade,
        "publicacao_autorizada": False, "coleta_continua_ativa": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
