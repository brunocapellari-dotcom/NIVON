"""Conectores de comercio exterior (MDIC) e fundos (CFTC) via agrobr 2.0.

Usa SOMENTE API publica do agrobr, ja declarada nas dependencias do NIVON.
NÃO reimplementa parsers de sites nem cria outro banco/serviço.
Snapshots são JSON NORMALIZADOS do agrobr; NÃO são o RAW original do MDIC/CFTC.
Coleta/despesa na nuvem nunca é disparada implicitamente.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .ingestao_fontes_reais import exportar_jsonl, gravar_lote

CONTRATOS = {
    "exportacao": ("BR_COMEXSTAT_EXPORTACAO_AGROBR", "comexstat", "https://comexstat.mdic.gov.br"),
    "importacao": ("BR_COMEXSTAT_IMPORTACAO_AGROBR", "comexstat", "https://comexstat.mdic.gov.br"),
    "posicionamento_fundos": ("US_CFTC_COT_AGROBR", "cftc", "https://publicreporting.cftc.gov"),
}
PRODUTOS_COMEX = frozenset({"soja", "milho", "cafe", "algodao", "acucar", "farelo_soja", "oleo_soja"})
PRODUTOS_CFTC = frozenset({
    "soja", "milho", "trigo", "farelo_soja", "oleo_soja", "acucar",
    "cafe", "algodao", "boi", "suino", "laranja", "arroz",
})
METRICAS_COMEX = ("kg_liquido", "valor_fob_usd")
METRICAS_CFTC = ("posicoes_abertas", "fundos_compra", "fundos_venda", "fundos_spread", "fundos_saldo")
UNIDADES = {"kg_liquido": "kg", "valor_fob_usd": "USD",
            "valor_frete_usd": "USD", "valor_seguro_usd": "USD"}
MAX_LINHAS = 1500
MAX_NORMALIZADO_BYTES = 20_000_000


class ErroAgrobrMercados(ValueError):
    pass


def _numero(v, *, obrigatorio=False):
    """Número decimal não negativo, ausente permanece ausente."""
    if v is None or isinstance(v, bool):
        if obrigatorio:
            raise ErroAgrobrMercados("valor obrigatório ausente")
        return None
    if isinstance(v, (list, tuple, dict)):
        raise ErroAgrobrMercados("célula numérica estruturada inesperada")
    texto = str(v)
    if texto in ("<NA>", "NaT", "nan", "NaN", "None", ""):
        if obrigatorio:
            raise ErroAgrobrMercados("valor obrigatório ausente")
        return None
    try:
        d = Decimal(texto)
    except (InvalidOperation, ValueError) as exc:
        raise ErroAgrobrMercados("valor fora do contrato decimal") from exc
    if not d.is_finite() or d < 0:
        raise ErroAgrobrMercados("valor negativo/não-finito")
    return format(d, "f")


def _inteiro(v, nome, minimo, maximo):
    if isinstance(v, bool) or v is None:
        raise ErroAgrobrMercados(nome + " ausente")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as exc:
        raise ErroAgrobrMercados(nome + " inválido") from exc
    if not d.is_finite() or d != int(d) or not minimo <= int(d) <= maximo:
        raise ErroAgrobrMercados(nome + " fora do limite")
    return int(d)


def _data(v):
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    elif isinstance(v, str):
        try:
            d = date.fromisoformat(v[:10])
        except ValueError as exc:
            raise ErroAgrobrMercados("data não ISO") from exc
    else:
        raise ErroAgrobrMercados("data do CFTC ausente")
    return d


def _linhas(frame):
    if not hasattr(frame, "to_dict"):
        raise ErroAgrobrMercados("agrobr não retornou DataFrame")
    result = frame.to_dict(orient="records")
    if not isinstance(result, list) or not 1 <= len(result) <= MAX_LINHAS:
        raise ErroAgrobrMercados("dataset vazio ou fora do limite de linhas")
    if any(not isinstance(x, dict) for x in result):
        raise ErroAgrobrMercados("linhas inválidas")
    return result


def _metadados(meta, dataset):
    """Bloqueia fallback/licença não livre ANTES de qualquer gravação."""
    if not hasattr(meta, "to_dict"):
        raise ErroAgrobrMercados("metadados de proveniência obrigatórios")
    m = meta.to_dict()
    if not isinstance(m, dict):
        raise ErroAgrobrMercados("metadados malformados")
    esperado = CONTRATOS[dataset][1]
    selecao = str(m.get("selected_source") or "").strip().lower()
    if selecao != esperado:
        raise ErroAgrobrMercados("fonte inesperada/fallback não permitido: " + selecao[:50])
    if m.get("license") != "livre":
        raise PermissionError("fonte sem licença de uso classificada como livre pelo agrobr")
    if m.get("validation_passed") is False:
        raise ErroAgrobrMercados("validação upstream não aprovada")
    if not isinstance(m.get("agrobr_version"), str) or not m["agrobr_version"].startswith("2."):
        raise ErroAgrobrMercados("requer agrobr versão 2.x para contrato fixado")
    contrato = str(m.get("contract_version") or "")
    if dataset == "posicionamento_fundos" and not contrato.startswith("2."):
        raise ErroAgrobrMercados("versão do contrato CFTC incompatível")
    if dataset == "exportacao" and not contrato.startswith("1."):
        raise ErroAgrobrMercados("versão do contrato exportação incompatível")
    if dataset == "importacao" and not contrato.startswith("1."):
        raise ErroAgrobrMercados("versão do contrato importação incompatível")
    return {
        "agrobr_version": m["agrobr_version"],
        "contract_version": contrato,
        "selected_source": selecao,
        "source_url": m.get("source_url") if isinstance(m.get("source_url"), str) else None,
        "raw_content_hash_upstream": m.get("raw_content_hash"),
        "license": m["license"],
        "validation_warnings": m.get("validation_warnings") or [],
    }


def _normalizar_comex(dataset, produto, rows, meta, *, ano, uf):
    obs = []
    chaves = set()
    for r in rows:
        y = _inteiro(r.get("ano"), "ano", 1997, date.today().year)
        mo = _inteiro(r.get("mes"), "mes", 1, 12)
        pr = str(r.get("produto") or "").strip()
        regiao = r.get("uf")
        regiao = None if regiao is None or str(regiao) in ("<NA>", "nan", "") else str(regiao).strip().upper()
        if pr != produto or y != ano or (uf is not None and regiao != uf):
            raise ErroAgrobrMercados("produto/ano/UF não corresponde à consulta")
        if regiao is not None and (not re.fullmatch(r"[A-Z]{2}", regiao)):
            raise ErroAgrobrMercados("UF inválida")
        chave = (y, mo, pr, regiao)
        if chave in chaves:
            raise ErroAgrobrMercados("chave comercial duplicada")
        chaves.add(chave)
        ref = date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
        metricas = list(METRICAS_COMEX)
        if dataset == "importacao":
            metricas += ["valor_frete_usd", "valor_seguro_usd"]
        medidas = {}
        for metrica in metricas:
            medidas[metrica] = _numero(r.get(metrica), obrigatorio=metrica in METRICAS_COMEX)
        if "volume_ton" in r:
            volume = _numero(r.get("volume_ton"))
            if volume is not None and abs(Decimal(volume) * 1000 - Decimal(medidas["kg_liquido"])) > Decimal("1"):
                raise ErroAgrobrMercados("kg_liquido diverge de volume_ton")
        for metrica, val in medidas.items():
            if val is None:
                continue
            obs.append({
                "identidade": f"{dataset}|{pr}|{regiao or 'BR'}|{y:04d}-{mo:02d}|{metrica}",
                "referencia": ref, "competencia": f"{y:04d}-{mo:02d}",
                "natureza": "INFORMADO", "unidade": UNIDADES[metrica], "valor": val,
                "campos": {
                    "tipo_dado": "AGROBR_NORMALIZADO_NAO_RAW_ORIGINAL",
                    "produto": pr, "uf": regiao, "ano": y, "mes": mo,
                    "metrica": metrica, "valor": val,
                    "fonte_primaria": "MDIC/ComexStat", "selected_source": meta["selected_source"],
                    "contrato_agrobr": meta["contract_version"],
                    "classificacao_licenca_agrobr": meta["license"],
                },
            })
    return obs


def _normalizar_cftc(produto, rows, meta, *, inicio, fim):
    observacoes, chaves = [], set()
    for r in rows:
        d = _data(r.get("data"))
        contrato = str(r.get("codigo_cftc") or "").strip()
        pr = str(r.get("produto") or "").strip()
        if not re.fullmatch(r"\d{6}", contrato) or pr != produto or not inicio <= d <= fim:
            raise ErroAgrobrMercados("chave CFTC inválida ou fora da janela")
        if (d, contrato) in chaves:
            raise ErroAgrobrMercados("chave CFTC semanal duplicada")
        chaves.add((d, contrato))
        medidas = {m: _numero(r.get(m), obrigatorio=True) for m in METRICAS_CFTC}
        if Decimal(medidas["fundos_saldo"]) != (Decimal(medidas["fundos_compra"]) - Decimal(medidas["fundos_venda"])):
            # saldo líquido pode ser negativo; tratado separadamente abaixo
            raise ErroAgrobrMercados("saldo dos fundos não reconcilia")
        for metrica, val in medidas.items():
            observacoes.append({
                "identidade": f"CFTC|{contrato}|{d.isoformat()}|{metrica}",
                "referencia": d.isoformat(), "competencia": d.isoformat(),
                "natureza": "INFORMADO", "unidade": "contratos", "valor": val,
                "campos": {
                    "tipo_dado": "AGROBR_NORMALIZADO_NAO_RAW_ORIGINAL",
                    "codigo_cftc": contrato, "contrato": str(r.get("contrato") or ""),
                    "produto": pr, "metrica": metrica, "valor": val,
                    "fonte_primaria": "CFTC", "selected_source": meta["selected_source"],
                    "contrato_agrobr": meta["contract_version"],
                    "classificacao_licenca_agrobr": meta["license"],
                    "observacao": "COT semanal, NÃO cotação de futuros",
                },
            })
    return observacoes


async def _consultar(dataset, produto, kwargs, provider=None):
    if provider is not None:
        return await provider(dataset, produto, **kwargs)
    try:
        from agrobr import datasets
    except ImportError as exc:
        raise RuntimeError('instale apenas o extra já definido: pip install -e ".[agro]"') from exc
    return await getattr(datasets, dataset)(produto, return_meta=True, **kwargs)


def coletar_mercado_agrobr(*, dataset, produto, banco, raw_dir, executar=False,
                         ano=None, uf=None, inicio=None, fim=None,
                         provider=None, instante=None, hoje=None):
    """Consulta delimitada e opt-in; grava via ledger existente do NIVON."""
    if executar is not True:
        raise PermissionError("AGROBR_MERCADOS_REQUER_EXECUTAR")
    if dataset not in CONTRATOS:
        raise ErroAgrobrMercados("dataset não permitido")
    permitidos = PRODUTOS_CFTC if dataset == "posicionamento_fundos" else PRODUTOS_COMEX
    if produto not in permitidos:
        raise ErroAgrobrMercados("produto fora do contrato")
    hoje = date.today() if hoje is None else hoje
    instante = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(hoje, date) or not isinstance(instante, datetime) or instante.utcoffset() is None:
        raise ErroAgrobrMercados("relógio/data inválidos")
    if dataset == "posicionamento_fundos":
        start = date.fromisoformat(inicio) if inicio else date(hoje.year, 1, 1)
        end = date.fromisoformat(fim) if fim else hoje
        if start > end or end > hoje or (end - start).days > 370 or start.year < 2006:
            raise ErroAgrobrMercados("janela CFTC fora dos limites")
        kwargs = {"inicio": start.isoformat(), "fim": end.isoformat(), "combinado": False}
        ano_req, uf_req = None, None
    else:
        if inicio is not None or fim is not None:
            raise ErroAgrobrMercados("datas mensais Comex requerem ano, não janela CFTC")
        if type(ano) is not int or not 1997 <= ano <= hoje.year:
            raise ErroAgrobrMercados("ano Comex obrigatório fora do intervalo")
        if uf is not None and (not isinstance(uf, str) or not re.fullmatch(r"[A-Z]{2}", uf)):
            raise ErroAgrobrMercados("UF Comex inválida")
        kwargs = {"ano": ano, "uf": uf}
        ano_req, uf_req = ano, uf
    resultado = asyncio.run(_consultar(dataset, produto, kwargs, provider=provider))
    if not isinstance(resultado, tuple) or len(resultado) != 2:
        raise ErroAgrobrMercados("agrobr não entregou DataFrame + MetaInfo")
    df, meta_obj = resultado
    meta = _metadados(meta_obj, dataset)
    rows = _linhas(df)
    if dataset == "posicionamento_fundos":
        registros = _normalizar_cftc(produto, rows, meta, inicio=start, fim=end)
    else:
        registros = _normalizar_comex(dataset, produto, rows, meta, ano=ano_req, uf=uf_req)
    if not registros or len(registros) > 7500:
        raise ErroAgrobrMercados("observações vazias ou excessivas")
    # Serialização independente da ordem do dataframe e sem carimbos voláteis:
    # consultas repetidas NÃO produzem novos snapshots quando dados não mudaram.
    payload = {"tipo": "AGROBR_RESULTADO_NORMALIZADO", "dataset": dataset,
               "produto": produto, "parametros": kwargs,
               "fonte": meta["selected_source"],
               "agrobr_version": meta["agrobr_version"],
               "contrato": meta["contract_version"],
               "hash_original_upstream": meta["raw_content_hash_upstream"],
               "observacoes": sorted(registros, key=lambda r: r["identidade"])}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if len(raw) > MAX_NORMALIZADO_BYTES:
        raise ErroAgrobrMercados("resultado serializado acima do limite")
    dataset_id, _, url = CONTRATOS[dataset]
    resp = gravar_lote(
        banco=banco, diretorio_bruto=raw_dir, dataset_id=dataset_id,
        origem=url, raw=raw, tipo="application/json",
        coletado_em=instante, registros=registros, estado="NORMALIZED",
    )
    resp.update({"dataset": dataset, "produto": produto,
                 "licenca": meta["license"], "fonte_selecionada": meta["selected_source"],
                 "observacoes_recebidas": len(registros), "linhas_entrada": len(rows),
                 "payload": "AGROBR_RESULTADO_NORMALIZADO, NÃO RAW DA FONTE",
                 "raw_sha256_upstream": meta["raw_content_hash_upstream"],
                 "publicado_no_terminal": False, "bigquery_executado": False})
    return resp


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: conectores de mercado via agrobr 2.0")
    p.add_argument("--dataset", required=True, choices=sorted(CONTRATOS))
    p.add_argument("--produto", required=True)
    p.add_argument("--ano", type=int)
    p.add_argument("--uf")
    p.add_argument("--inicio")
    p.add_argument("--fim")
    p.add_argument("--banco", default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir", default="data/nivon/raw")
    p.add_argument("--exportar-jsonl", action="store_true")
    p.add_argument("--executar", action="store_true")
    args = p.parse_args(argv)
    saida = coletar_mercado_agrobr(
        dataset=args.dataset, produto=args.produto, ano=args.ano, uf=args.uf,
        inicio=args.inicio, fim=args.fim,
        banco=args.banco, raw_dir=args.raw_dir, executar=args.executar,
    )
    if args.exportar_jsonl:
        destino = Path(args.banco).parent / ("agrobr_" + args.dataset + "_staging.jsonl")
        saida["stage"] = exportar_jsonl(
            banco=args.banco, destino=destino, dataset_id=CONTRATOS[args.dataset][0])
    print(json.dumps(saida, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
