"""Consolidacao auditavel de TU/TKU da ANTT a partir de staging local."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .transporte_multimodal import ErroTransporte


def consolidar_staging(diretorio: str | Path, anos: list[int]) -> dict:
    pasta = Path(diretorio)
    try:
        m = json.loads((pasta / "manifesto-antt.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ErroTransporte("manifesto ANTT ausente/invalido") from None
    if m.get("formato") != "nivon-antt-staging-v1":
        raise ErroTransporte("manifesto sem contrato")
    total = defaultdict(lambda: Decimal(0))
    meses = defaultdict(lambda: Decimal(0))
    mercadorias = defaultdict(lambda: Decimal(0))
    por_uf_o = defaultdict(lambda: Decimal(0))
    ferrovias = defaultdict(lambda: Decimal(0))
    anuais = defaultdict(lambda: Decimal(0))
    mt_anuais = defaultdict(lambda: Decimal(0))
    soja_anuais = defaultdict(lambda: Decimal(0))
    milho_anuais = defaultdict(lambda: Decimal(0))
    farelo_anuais = defaultdict(lambda: Decimal(0))
    n = 0
    anomalias = 0
    detalhes = {}
    for ano in anos:
        if type(ano) is not int:
            raise ErroTransporte("ano nao inteiro")
        registro = m.get("anos", {}).get(str(ano))
        if not registro or registro.get("status") != "STAGING_NAO_HOMOLOGADO":
            raise ErroTransporte("ano ausente ou sem controle no staging")
        raw = (pasta / f"antt-od-{ano}.csv").read_bytes()
        if hashlib.sha256(raw).hexdigest() != registro.get("sha256"):
            raise ErroTransporte("SHA-256 nao confere")
        linhas_ano = 0
        for line in (pasta / f"antt-od-{ano}.jsonl").open(encoding="utf-8"):
            try:
                x = json.loads(line)
                if (x["ano"] != ano or x["natureza_tu"] != "OBSERVADO_DECLARADO"
                        or not x["competencia"].startswith(str(ano) + "-")):
                    raise ErroTransporte("competencia/natureza divergente")
                tu = Decimal(x["toneladas_uteis"])
                tku = Decimal(x["tku_raw"])
                if not tu.is_finite() or not tku.is_finite() or tu < 0 or tku < 0:
                    raise ErroTransporte("TU/TKU invalidos")
                anomalias += int(bool(x.get("anomalia_tu_tku", False)))
                total["tu"] += tu
                total["tku_raw"] += tku
                meses[x["competencia"]] += tu
                mercadorias[x["mercadoria"]] += tu
                por_uf_o[x["uf_origem"]] += tu
                ferrovias[x["ferrovia"]] += tu
                anuais[ano] += tu
                if x["uf_origem"] == "MT":
                    mt_anuais[ano] += tu
                merc = x["mercadoria"].casefold()
                if "farelo" in merc and "soja" in merc:
                    farelo_anuais[ano] += tu
                elif "soja" in merc:
                    soja_anuais[ano] += tu
                elif "milho" in merc:
                    milho_anuais[ano] += tu
                linhas_ano += 1
                n += 1
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                raise ErroTransporte("JSONL ANTT invalido") from exc
        if linhas_ano != registro["registros"]:
            raise ErroTransporte("contagem de registros diverge do manifesto")
        detalhes[str(ano)] = {"registros": linhas_ano,
                             "competencia_maxima": registro["competencia_maxima"],
                             "sha256": registro["sha256"]}
    return {"fonte": "ANTT_SIADE_ORIGEM_DESTINO", "estado": "RESUMO_STAGING_NAO_HOMOLOGADO",
            "unidades": {"toneladas_uteis": "TU", "tku_raw": "TKU"},
            "observacao": "TU por fluxo ferroviario; nao equivale a carga unica sem transbordo",
            "registros": n, "anomalias_tu_tku": anomalias, "toneladas_uteis": str(total["tu"]),
            "tku_raw": str(total["tku_raw"]),
            "por_mes": {k: str(v) for k, v in sorted(meses.items())},
            "por_ano": {str(k): {"tu": str(anuais[k]),
                              "tu_origem_mt": str(mt_anuais[k]),
                              "tu_soja": str(soja_anuais[k]),
                              "tu_milho": str(milho_anuais[k]),
                              "tu_farelo_soja": str(farelo_anuais[k])}
                        for k in sorted(anuais)},
            "por_mercadoria": {k: str(v) for k, v in sorted(mercadorias.items(), key=lambda kv: -kv[1])},
            "por_ferrovia": {k: str(v) for k, v in sorted(ferrovias.items(), key=lambda kv: -kv[1])},
            "por_uf_origem": {k: str(v) for k, v in sorted(por_uf_o.items(), key=lambda kv: -kv[1])},
            "anos": detalhes}


def main() -> int:
    p = argparse.ArgumentParser(description="NIVON: consolidacao TU/TKU do staging ANTT")
    p.add_argument("--destino", required=True)
    p.add_argument("--anos", nargs="+", type=int, required=True)
    a = p.parse_args()
    try:
        r = consolidar_staging(a.destino, a.anos)
    except (ErroTransporte, FileNotFoundError) as e:
        print(json.dumps({"estado": "NAO_VALIDADO", "erro": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
