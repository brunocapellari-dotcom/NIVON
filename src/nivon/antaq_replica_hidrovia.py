"""Validador de réplica SECUNDÁRIA dos agregados hidroviários da ANTAQ.

Não representa coleta direta na ANTAQ, não alimenta dado canônico e não faz HTTP.
Fonte alternativa: HF vinicius-souza/antaq (CC-BY-4.0).
Parquet inspecionado na prova real de 2026-10-23, versão ff0349f...
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

HF_DATASET = "vinicius-souza/antaq"
HF_PATH = "gold/carga_hidrovia_anual.parquet"
HF_REVISION_VERIFICADA = "ff0349fa6dc8cebcec161ee3ce48f6f73f7f3ba8"
HF_SHA256_VERIFICADO = "62ea05fccd015044d7fcb0a80c6c6efd9fd7175aefd394d25320ec2aeeb6ab42"
FONTE_OFICIAL_REFERENCIA_MADEIRA = (
    "https://www.gov.br/portos-e-aeroportos/pt-br/assuntos/noticias/2026/02/"
    "hidrovia-do-madeira-transportou-12-1-milhoes-de-toneladas-em-2025"
)


class ErroReplicaANTAQ(ValueError):
    pass


def nome_normalizado(nome: str) -> str:
    if not isinstance(nome, str) or not nome or len(nome) > 180:
        raise ErroReplicaANTAQ("nome de hidrovia invalido")
    s = nome.strip()
    if "Ã" in s or "Â" in s:
        try:
            s = s.encode("latin-1").decode("utf-8")
        except (UnicodeError, ValueError):
            raise ErroReplicaANTAQ("codificacao de hidrovia nao reconhecida") from None
    s = re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()
    if not s or any(ord(c) < 32 for c in s):
        raise ErroReplicaANTAQ("nome de hidrovia invalido")
    return unicodedata.normalize("NFC", s)


def validar_linhas(linhas: list[dict], *, sha256: str, revisao: str) -> dict:
    if not isinstance(linhas, list) or not 1 <= len(linhas) <= 5000:
        raise ErroReplicaANTAQ("quantidade de linhas inesperada")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or not re.fullmatch(r"[0-9a-f]{40}", revisao):
        raise ErroReplicaANTAQ("identificador de fonte invalido")
    visto = set()
    registros = []
    for raw in linhas:
        if not isinstance(raw, dict) or set(raw) != {"Hidrovia", "Ano", "tonelagem_total", "n_registros"}:
            raise ErroReplicaANTAQ("schema externo mudou")
        hidro = nome_normalizado(raw["Hidrovia"])
        ano = raw["Ano"]
        count = raw["n_registros"]
        total = raw["tonelagem_total"]
        if type(ano) is not int or not 2010 <= ano <= 2026:
            raise ErroReplicaANTAQ("ano da fonte fora do intervalo")
        if type(count) is not int or count <= 0:
            raise ErroReplicaANTAQ("contagem invalida")
        if type(total) not in (float, int) or not math.isfinite(total) or total < 0:
            raise ErroReplicaANTAQ("tonelagem invalida")
        key = (hidro, ano)
        if key in visto:
            raise ErroReplicaANTAQ("hidrovia/ano duplicado na fonte secundaria")
        visto.add(key)
        registros.append({
            "hidrovia": hidro, "ano": ano,
            "toneladas": str(Decimal(str(total))),
            "registros_origem": count,
            "fonte": "REPLICA_TERCEIRO_HF_ANTAQ",
            "classificacao": "DERIVADO_TERCEIRO_NAO_CONCILIADO",
            "unidade": "toneladas",
            "hf_revision": revisao,
            "arquivo_sha256": sha256,
            "licenca_declarada_pelo_distribuidor": "CC-BY-4.0",
            "metodologia_confirmada": False,
            "tipo_navegacao_confirmado": False,
            "aditividade_entre_hidrovias_confirmada": False,
        })
    return {
        "estado": "VALIDADO_ESTRUTURALMENTE_NAO_HOMOLOGADO",
        "fonte": HF_DATASET, "arquivo": HF_PATH,
        "revision": revisao, "sha256": sha256,
        "n_linhas": len(registros),
        "anos": sorted(set(r["ano"] for r in registros)),
        "registros": sorted(registros, key=lambda r: (r["ano"], r["hidrovia"])),
        "observacao": "Nao somar hidrovias sem reconciliar navegacao, sobreposicoes e definicoes com ANTAQ",
    }


def ler_parquet(path: str | Path, *, revisao: str) -> dict:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise ErroReplicaANTAQ("pyarrow nao instalado") from None
    p = Path(path)
    if not p.is_file() or not 100 <= p.stat().st_size <= 20_000_000:
        raise ErroReplicaANTAQ("arquivo ausente/tamanho invalido")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    table = pq.read_table(p)
    if table.num_rows > 5000:
        raise ErroReplicaANTAQ("numero de linhas excedeu limite")
    return validar_linhas(table.to_pylist(), sha256=sha, revisao=revisao)


def resumo_2025(doc: dict) -> dict:
    dados = {r["hidrovia"]: r for r in doc["registros"] if r["ano"] == 2025}
    madeira = dados.get("Hidrovia do Madeira")
    if not madeira:
        raise ErroReplicaANTAQ("Madeira 2025 ausente para confronto")
    t = Decimal(madeira["toneladas"])
    ref = Decimal("12100000")   # número OFICIAL arredondado a 0,1 milhão de t
    diferenca = abs(t - ref) / ref
    return {
        "estado": "COMPARACAO_PONTUAL_NAO_HOMOLOGACAO",
        "ano": 2025, "fonte_oficial": FONTE_OFICIAL_REFERENCIA_MADEIRA,
        "madeira_terceiro_ton": str(t),
        "madeira_oficial_aproximado_ton": str(ref),
        "divergencia_relativa": str(diferenca),
        "comparacao_compatibilidade_1pct": diferenca <= Decimal("0.01"),
        "hidrovias": {k: v["toneladas"] for k, v in sorted(dados.items())},
        "regra": "NÃO SOMAR: hidrovias podem conter movimentacao ampla e dupla contagem",
    }


def serializar_resumo(doc: dict) -> str:
    r = resumo_2025(doc)
    return json.dumps({"source_revision": doc["revision"], "source_sha256": doc["sha256"],
                       "n_linhas": doc["n_linhas"], "anos": doc["anos"],
                       "confronto": r}, ensure_ascii=False, sort_keys=True)
