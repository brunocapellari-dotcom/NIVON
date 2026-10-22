"""Teste em memória de série histórica CONAB (MT, soja e milho)."""
import asyncio
import json
from agrobr import conab
from nivon.conab_safras import checar_meta

async def main():
    output=[]
    for product in ("soja","milho"):
        df,meta=await conab.serie_historica(
            product,ano_inicio=2022,ano_fim=2025,uf="MT",return_meta=True)
        origem=checar_meta(meta)
        if df.empty or "safra" not in df.columns:
            raise ValueError("Serie CONAB sem safras")
        if "uf" in df.columns and not all(df["uf"].astype(str)=="MT"):
            raise ValueError("Filtro MT nao respeitado")
        output.append({"produto":product,"linhas":len(df),
                       "colunas":list(map(str,df.columns)),"fonte":origem["fonte"],
                       "historico_gravado":False})
    print(json.dumps(output,ensure_ascii=False))
if __name__=="__main__":
    asyncio.run(main())
