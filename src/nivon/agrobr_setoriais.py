"""NIVON: coletores setoriais via agrobr 2.0; SEM execução automática.

Complementa agrobr_mercados.py e preserva o ledger atual.
A saída é um SNAPSHOT NORMALIZADO do agrobr, NÃO os bytes originais IBGE/ANP.
Código incorporado por solicitação de 26/10/2026; testes foram adiados.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from .ingestao_fontes_reais import gravar_lote, exportar_jsonl

# Fonte permitida é vinculada ao contrato, não à URL fornecida por usuários.
# Nunca misturar fallback CONAB com PAM IBGE, nem PPI ANP com preços de revenda.
CONTRATOS = {
    "pecuaria_municipal": {
        "dataset_id": "BR_IBGE_PECUARIA_MUNICIPAL_AGROBR",
        "fontes": ("ibge_ppm",),
        "url": "https://apisidra.ibge.gov.br/",
        "chave": ("ano", "localidade_cod", "especie"),
        "medidas": {"valor": None},
        "produto_permitido": ("bovino", "leite", "suino"),
    },
    "abate_trimestral": {
        "dataset_id": "BR_IBGE_ABATE_TRIMESTRAL_AGROBR",
        "fontes": ("ibge_abate",),
        "url": "https://apisidra.ibge.gov.br/",
        "chave": ("trimestre", "localidade_cod", "especie", "categoria"),
        "medidas": {"animais_abatidos": "cabecas", "peso_carcacas": "kg"},
        "produto_permitido": ("bovino", "suino", "frango"),
    },
    "leite_industrial": {
        "dataset_id": "BR_IBGE_LEITE_INDUSTRIAL_AGROBR",
        "fontes": ("ibge_leite_trimestral",),
        "url": "https://apisidra.ibge.gov.br/",
        "chave": ("trimestre", "localidade_cod"),
        "medidas": {"leite_adquirido": "mil_litros",
                    "leite_industrializado": "mil_litros",
                    "preco_medio": "BRL/litro"},
        "produto_permitido": (),
    },
    "producao_anual": {
        "dataset_id": "BR_IBGE_PAM_PRODUCAO_ANUAL_AGROBR",
        "fontes": ("ibge_pam",),
        "url": "https://apisidra.ibge.gov.br/",
        "chave": ("ano", "localidade_cod", "produto"),
        "medidas": {"area_plantada": "ha", "area_colhida": "ha",
                    "producao": "unidade_producao",
                    "rendimento": "unidade_rendimento",
                    "valor_producao": "unidade_valor_producao"},
        "produto_permitido": ("soja", "milho", "algodao", "arroz", "trigo"),
    },
    "precos_diesel": {
        "dataset_id": "BR_ANP_DIESEL_REVENDA_AGROBR",
        "fontes": ("anp_diesel",),
        "url": "https://www.gov.br/anp/",
        "chave": ("data", "uf", "municipio", "produto", "nivel", "agregacao"),
        "medidas": {"preco_venda": "BRL/litro",
                    "preco_compra": "BRL/litro",
                    "margem": "BRL/litro"},
        "produto_permitido": ("DIESEL S10", "DIESEL"),
    },
    "pib_agro": {
        "dataset_id": "BR_IBGE_PIB_AGRO_TRIMESTRAL_AGROBR",
        "fontes": ("ibge",),
        "url": "https://apisidra.ibge.gov.br/",
        "chave": ("trimestre", "setor", "precos"),
        "medidas": {"valor": "unidade"},
        "produto_permitido": ("agropecuaria",),
    },
}
LIMITE_LINHAS = 2000
LIMITE_ARQUIVO = 20_000_000


class ErroFontesSetoriais(ValueError):
    pass


def _escalar(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _escalar(value.item())
        except (TypeError, ValueError, OverflowError):
            pass
    if str(value) in {"<NA>", "NaT", "nan", "NaN", "None"}:
        return None
    raise ErroFontesSetoriais("tipo de célula não suportado: " + type(value).__name__)


def _numero(value, *, aceita_negativo=False):
    v = _escalar(value)
    if v is None:
        return None
    if isinstance(v, bool):
        raise ErroFontesSetoriais("booleano não é número")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as exc:
        raise ErroFontesSetoriais("medida numérica inválida") from exc
    if not d.is_finite() or (not aceita_negativo and d < 0):
        raise ErroFontesSetoriais("medida fora da faixa numérica")
    return format(d, "f")


def _referencia(linha):
    if linha.get("data") is not None:
        raw = _escalar(linha["data"])
        try:
            return date.fromisoformat(str(raw)[:10]).isoformat(), "DATA"
        except ValueError as exc:
            raise ErroFontesSetoriais("data semanal inválida") from exc
    if linha.get("trimestre") is not None:
        q = str(_escalar(linha["trimestre"]))
        if not re.fullmatch(r"20\d{2}0[1-4]", q):
            raise ErroFontesSetoriais("trimestre YYYYQQ inválido")
        y, quarter = int(q[:4]), int(q[-1])
        month = 3 * quarter
        return date(y, month, calendar.monthrange(y, month)[1]).isoformat(), "FIM_TRIMESTRE_CONVENCIONAL"
    if linha.get("ano") is not None:
        try:
            year = int(str(_escalar(linha["ano"])))
        except (TypeError, ValueError) as exc:
            raise ErroFontesSetoriais("ano não numérico") from exc
        if not 1990 <= year <= date.today().year:
            raise ErroFontesSetoriais("ano fora da faixa")
        return f"{year}-12-31", "FIM_ANO_CONVENCIONAL"
    raise ErroFontesSetoriais("sem período conhecido")


def _parametros(dataset, *, produto=None, ano=None, uf=None, trimestre=None,
                inicio=None, fim=None):
    if dataset not in CONTRATOS:
        raise ErroFontesSetoriais("dataset fora do escopo")
    rule = CONTRATOS[dataset]
    if rule["produto_permitido"] and produto not in rule["produto_permitido"]:
        raise ErroFontesSetoriais("produto ausente ou não permitido")
    if not rule["produto_permitido"] and produto is not None:
        raise ErroFontesSetoriais("produto não admitido neste dataset")
    if uf is not None and (not isinstance(uf, str) or not re.fullmatch(r"[A-Z]{2}", uf)):
        raise ErroFontesSetoriais("UF deve ter 2 letras maiúsculas")
    if dataset in {"pecuaria_municipal", "producao_anual"}:
        if type(ano) is not int or not 2000 <= ano <= date.today().year:
            raise ErroFontesSetoriais("ano IBGE inválido")
        if trimestre is not None or inicio or fim:
            raise ErroFontesSetoriais("parâmetros de frequência diferentes")
        return (produto,), {"ano": ano, "nivel": "uf", "uf": uf}
    if dataset in {"abate_trimestral", "leite_industrial", "pib_agro"}:
        if (not isinstance(trimestre, str) or not re.fullmatch(r"20\d{2}0[1-4]", trimestre)
                or int(trimestre[:4]) > date.today().year):
            raise ErroFontesSetoriais("trimestre fora do contrato")
        if ano is not None or inicio or fim or (uf and dataset == "pib_agro"):
            raise ErroFontesSetoriais("parâmetros incompatíveis")
        if dataset == "leite_industrial":
            return (), {"trimestre": trimestre, "uf": uf}
        if dataset == "pib_agro":
            return (produto,), {"trimestre": trimestre}
        return (produto,), {"trimestre": trimestre, "uf": uf}
    if dataset == "precos_diesel":
        if ano is not None or trimestre is not None or uf is None:
            raise ErroFontesSetoriais("diesel exige UF e intervalo semanal")
        try:
            a, b = date.fromisoformat(inicio), date.fromisoformat(fim)
        except (ValueError, TypeError) as exc:
            raise ErroFontesSetoriais("diesel exige inicio/fim ISO") from exc
        if not a <= b <= date.today() or (b-a).days > 100:
            raise ErroFontesSetoriais("janela de diesel fora do limite")
        return (produto,), {"inicio": inicio, "fim": fim, "nivel": "uf",
                             "uf": uf, "agregacao": "semanal"}
    raise ErroFontesSetoriais("sem rota pública definida")


async def _adquirir(dataset, args, params, fornecedor=None):
    if fornecedor is not None:
        return await fornecedor(dataset, args, params)
    try:
        from agrobr import datasets as datasets_agrobr
    except ImportError as exc:
        raise RuntimeError("agrobr==2.0.0 já previsto no extra NIVON [agro]") from exc
    return await getattr(datasets_agrobr, dataset)(
        *args, return_meta=True, **params)


def coletar_setorial_agrobr(*, dataset, banco, raw_dir, executar=False,
                          produto=None, ano=None, uf=None, trimestre=None,
                          inicio=None, fim=None, fornecedor=None, instante=None):
    if executar is not True:
        raise PermissionError("COLETA_AGROBR_SETORIAL_NAO_HABILITADA")
    args, params = _parametros(dataset, produto=produto, ano=ano, uf=uf,
                               trimestre=trimestre, inicio=inicio, fim=fim)
    rule = CONTRATOS[dataset]
    stamp = instante or datetime.now(timezone.utc)
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ErroFontesSetoriais("instante sem fuso")
    result = asyncio.run(_adquirir(dataset, args, params, fornecedor=fornecedor))
    if not isinstance(result, tuple) or len(result) != 2:
        raise ErroFontesSetoriais("agrobr não entregou dados e metadados")
    frame, meta = result
    if not hasattr(frame, "to_dict") or not hasattr(meta, "to_dict"):
        raise ErroFontesSetoriais("contrato DataFrame/MetaInfo não satisfeito")
    m = meta.to_dict()
    if (not isinstance(m, dict) or
            not str(m.get("agrobr_version", "")).startswith("2.") or
            m.get("validation_passed") is False or
            m.get("selected_source") not in rule["fontes"] or
            m.get("license") != "livre"):
        raise PermissionError("fonte, versão, validação ou direitos não autorizados")
    rows = frame.to_dict(orient="records")
    if not isinstance(rows, list) or not 1 <= len(rows) <= LIMITE_LINHAS:
        raise ErroFontesSetoriais("dados vazios ou limite de linhas excedido")
    obs, seen = [], set()
    for original in rows:
        if not isinstance(original, dict):
            raise ErroFontesSetoriais("linha fora do contrato")
        linha = {k: _escalar(v) for k, v in original.items()}
        ref, base_temporal = _referencia(linha)
        chave = {k: linha.get(k) for k in rule["chave"]}
        if any(v is None for v in chave.values()):
            raise ErroFontesSetoriais("chave de linha incompleta")
        dim = json.dumps(chave, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if dim in seen:
            raise ErroFontesSetoriais("chave primária repetida no resultado")
        seen.add(dim)
        for metrica, tipo_unidade in rule["medidas"].items():
            valor = _numero(linha.get(metrica), aceita_negativo=metrica == "margem")
            if valor is None:
                continue
            unidade = (
                linha.get("unidade") if tipo_unidade is None else
                linha.get(tipo_unidade) if tipo_unidade in linha else tipo_unidade
            )
            if not isinstance(unidade, str) or not unidade.strip():
                raise ErroFontesSetoriais("unidade métrica não comprovada")
            identity_hash = hashlib.sha256(dim.encode("utf-8")).hexdigest()[:20]
            obs.append({
                "identidade": f"{dataset}|{identity_hash}|{metrica}",
                "referencia": ref,
                "competencia": str(linha.get("trimestre") or linha.get("ano") or ref),
                "natureza": "INFORMADO",
                "valor": valor, "unidade": unidade,
                "campos": {
                    "fonte_primaria": m["selected_source"],
                    "dataset_agrobr": dataset,
                    "metrica": metrica, "valor": valor, "unidade": unidade,
                    "chave": chave, "base_temporal": base_temporal,
                    "linha_normalizada_agrobr": linha,
                    "schema_agrobr": m.get("contract_version"),
                    "tipo_snapshot": "AGROBR_NORMALIZADO_NAO_RAW_PRIMARIO",
                },
            })
    if not obs:
        raise ErroFontesSetoriais("não há observações numéricas aproveitáveis")
    if len(obs) > 10_000:
        raise ErroFontesSetoriais("resultado requer particionamento")
    pacote = {
        "tipo": "AGROBR_NORMALIZADO_NAO_RAW_PRIMARIO",
        "dataset": dataset, "args": args, "parametros": params,
        "fonte_selecionada": m["selected_source"],
        "versao_agrobr": m.get("agrobr_version"),
        "contrato": m.get("contract_version"),
        "hash_arquivo_upstream_se_fornecido": m.get("raw_content_hash"),
        "observacoes": sorted(obs, key=lambda r: r["identidade"] + r["referencia"]),
    }
    payload = json.dumps(pacote, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > LIMITE_ARQUIVO:
        raise ErroFontesSetoriais("snapshot normalizado excede limite")
    out = gravar_lote(
        banco=banco, diretorio_bruto=raw_dir, dataset_id=rule["dataset_id"],
        origem=rule["url"], raw=payload, tipo="application/json",
        coletado_em=stamp, registros=obs, estado="NORMALIZED",
    )
    out.update({
        "fonte": dataset, "instituicao": m["selected_source"],
        "linhas_recebidas": len(rows), "observacoes_normalizadas": len(obs),
        "snapshot_eh_raw_primario": False, "licenca_reportada": m["license"],
        "publicado_terminal": False, "cloud_executado": False,
        "testes_nesta_entrega": "ADIADOS",
    })
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: coletores setoriais agrobr registrados")
    p.add_argument("--dataset", choices=sorted(CONTRATOS), required=True)
    p.add_argument("--produto")
    p.add_argument("--ano", type=int)
    p.add_argument("--uf")
    p.add_argument("--trimestre")
    p.add_argument("--inicio")
    p.add_argument("--fim")
    p.add_argument("--banco", default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir", default="data/nivon/raw")
    p.add_argument("--exportar-jsonl", action="store_true")
    p.add_argument("--executar", action="store_true")
    x = p.parse_args(argv)
    out = coletar_setorial_agrobr(
        dataset=x.dataset, banco=x.banco, raw_dir=x.raw_dir,
        produto=x.produto, ano=x.ano, uf=x.uf, trimestre=x.trimestre,
        inicio=x.inicio, fim=x.fim, executar=x.executar,
    )
    if x.exportar_jsonl:
        from pathlib import Path
        out["stage"] = exportar_jsonl(
            banco=x.banco,
            destino=Path(x.banco).parent / f"agrobr_{x.dataset}_staging.jsonl",
            dataset_id=CONTRATOS[x.dataset]["dataset_id"],
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
