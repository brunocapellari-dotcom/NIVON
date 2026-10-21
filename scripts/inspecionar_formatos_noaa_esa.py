"""Somente diagnóstico estrutural de dois formatos públicos sem salvar dados."""
import json
from urllib.request import Request, urlopen

url_noaa = "https://psl.noaa.gov/data/correlation/meiv2.csv"
url_esa = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_S15W057_Map.tif"
for fonte, url, metodo in (("NOAA", url_noaa, "GET"), ("ESA", url_esa, "HEAD")):
    try:
        req = Request(url, method=metodo, headers={"User-Agent": "NIVON/0.1"})
        with urlopen(req, timeout=15) as r:
            obj = {"fonte": fonte, "http": r.status,
                   "mime": r.headers.get("Content-Type"),
                   "tamanho_http": r.headers.get("Content-Length")}
            if fonte == "NOAA":
                body = r.read(1_000_000)
                lines = body.decode("utf-8-sig", "replace").splitlines()
                obj.update(linhas=len(lines), cabecalho=lines[0][:200] if lines else "",
                           linhas_nao_vazias=sum(bool(x.strip()) for x in lines),
                           separadores_ponto_virgula=lines[0].count(";") if lines else 0,
                           separadores_virgula=lines[0].count(",") if lines else 0)
            print(json.dumps(obj, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"fonte": fonte, "falha_tipo": type(e).__name__}))
