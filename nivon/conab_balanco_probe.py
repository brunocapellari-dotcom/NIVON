"""Diagnostico isolado do balanco CONAB, sem banco ou extracao macica."""
import asyncio
import json
from agrobr import conab
from nivon.conab_safras import checar_meta
from nivon.conab_balanco import normalizar_balanco

async def main():
    resumo=[]
    for produto in ("soja","milho"):
        df,meta=await conab.balanco(produto,safra="2026/27",
                                   levantamento=1,return_meta=True)
        origem=checar_meta(meta)
        release=(origem.get("source_details") or {}).get("publicacao")
        registros=df.to_dict(orient="records")
        print(json.dumps({"produto_solicitado":produto,
                          "rótulos_de_produto":sorted({str(r.get("produto")) for r in registros}),
                          "colunas":sorted(df.columns)},ensure_ascii=False))
        validos=normalizar_balanco(registros,"conab",release)
        resumo.append({"produto":produto,"linhas":len(validos),
                       "alertas":sum(len(v["alertas"]) for v in validos),
                       "fonte":origem["fonte"],"armazenado":False})
    print(json.dumps(resumo,ensure_ascii=False))
if __name__=="__main__":
    asyncio.run(main())
