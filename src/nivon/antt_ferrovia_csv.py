"""Adaptador CSV público ANTT/SIADE para produção ferroviária por origem/destino.

Fonte SIADE ANTT, CC Atribuição indicada no catálogo. É uma matriz por
ESTAÇÃO ferroviária e mercadoria, não é MDF-e rodoviário nem consumo final.
Volumes TU (toneladas úteis) e TKU (toneladas úteis x quilômetros).
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections import defaultdict
from typing import Iterator

from .antt_ferrovia import ErroFerrovia, UFS

CAMPOS = (
    "Mes_Ano", "Ferrovia", "Mercadoria_ANTT", "Estacao_Origem",
    "UF_Origem", "Estacao_Destino", "UF_Destino", "TU", "TKU",
)
_PERIODO = re.compile(r"^(0[1-9]|1[0-2])/(20\d{2})$")
_NUMERO = re.compile(r"^(?:0|[1-9]\d*|[1-9]\d{0,2}(?:\.\d{3})+)(?:,\d+)?$")
_LIMITE = 3_000_000


def _numero_ptbr(valor: str, campo: str) -> float:
    if not isinstance(valor, str) or not _NUMERO.fullmatch(valor.strip()):
        raise ErroFerrovia(f"{campo}: número fora do contrato pt-BR")
    numero = float(valor.strip().replace(".", "").replace(",", "."))
    if not math.isfinite(numero) or numero < 0:
        raise ErroFerrovia(f"{campo}: valor inválido")
    return numero


def extrair_csv(dados: bytes, *, fonte_id: str = "ANTT_SIADE_2026") -> list[dict]:
    """Falha fechado com qualquer coluna/UF/volume incompatível.

    Não devolve dados parciais em caso de erro. Não grava registros em disco.
    """
    if not isinstance(dados, bytes) or not dados or len(dados) > _LIMITE:
        raise ErroFerrovia("CSV vazio ou acima do limite")
    if not fonte_id or not fonte_id.strip():
        raise ErroFerrovia("identificador da fonte obrigatório")
    try:
        texto = dados.decode("cp1252", errors="strict")
    except UnicodeDecodeError as exc:
        raise ErroFerrovia("CSV precisa da codificação cp1252 validada") from exc
    leitor = csv.DictReader(io.StringIO(texto, newline=""), delimiter=";")
    if leitor.fieldnames is None or tuple(leitor.fieldnames) != CAMPOS:
        raise ErroFerrovia("schema SIADE alterado ou colunas em ordem inesperada")
    resultado = []
    hash_arquivo = hashlib.sha256(dados).hexdigest()
    for numero_linha, row in enumerate(leitor, start=2):
        if numero_linha > 25_002:
            raise ErroFerrovia("limite de linhas excedido")
        if None in row or any(row.get(c) is None for c in CAMPOS):
            raise ErroFerrovia(f"linha {numero_linha}: CSV desalinhado")
        periodo = str(row["Mes_Ano"]).strip()
        match = _PERIODO.fullmatch(periodo)
        if not match:
            raise ErroFerrovia(f"linha {numero_linha}: mês/ano inválido")
        uf_origem = row["UF_Origem"].strip().upper()
        uf_destino = row["UF_Destino"].strip().upper()
        if uf_origem not in UFS or uf_destino not in UFS:
            raise ErroFerrovia(f"linha {numero_linha}: UF inválida")
        rotulos = {}
        for campo, nome in (
            ("Ferrovia", "ferrovia"),
            ("Mercadoria_ANTT", "mercadoria_antt"),
            ("Estacao_Origem", "origem_estacao"),
            ("Estacao_Destino", "destino_estacao"),
        ):
            texto_bruto = row[campo].strip()
            if not texto_bruto or len(texto_bruto) > 180:
                raise ErroFerrovia(f"linha {numero_linha}: {campo} ausente ou excessivo")
            rotulos[nome] = texto_bruto
        resultado.append({
            "periodo": f"{match.group(2)}-{match.group(1)}",
            **rotulos,
            "origem_uf": uf_origem,
            "destino_uf": uf_destino,
            "tu_t": _numero_ptbr(row["TU"], "TU"),
            "tku": _numero_ptbr(row["TKU"], "TKU"),
            "modal": "FERROVIARIO",
            "local_tipo": "ESTACAO_NAO_MUNICIPIO",
            "arquivo_sha256": hash_arquivo,
            "fonte_id": fonte_id,
        })
    if not resultado:
        raise ErroFerrovia("CSV SIADE sem registros")
    return resultado


def resumo_safra_ferroviaria(registros: list[dict]) -> dict:
    """Movimento ferroviário agregado e origem MT, sem inferir carregamento rodoviário."""
    if not registros:
        raise ErroFerrovia("sem registros")
    por_mes = defaultdict(lambda: {"linhas": 0, "tu_t": 0.0, "tku": 0.0})
    mt = defaultdict(lambda: {"linhas": 0, "tu_t": 0.0})
    conjunto_hash = {r["arquivo_sha256"] for r in registros}
    if len(conjunto_hash) != 1:
        raise ErroFerrovia("arquivos/edições diferentes na mesma agregação")
    for r in registros:
        per = r["periodo"]
        por_mes[per]["linhas"] += 1
        por_mes[per]["tu_t"] += r["tu_t"]
        por_mes[per]["tku"] += r["tku"]
        if r["origem_uf"] == "MT":
            tipo = r["mercadoria_antt"].casefold()
            if "soja" in tipo and "farelo" not in tipo:
                produto = "SOJA_FONTE_ANTT"
            elif "milho" in tipo:
                produto = "MILHO_FONTE_ANTT"
            elif "farelo de soja" in tipo:
                produto = "FARELO_SOJA_FONTE_ANTT"
            else:
                continue
            k = (per, produto, r["origem_estacao"], r["destino_estacao"], r["destino_uf"])
            mt[k]["linhas"] += 1
            mt[k]["tu_t"] += r["tu_t"]
    return {
        "modal": "FERROVIARIO",
        "natureza": "MOVIMENTACAO_ANTT_SIADE_NAO_CONSUMO_NAO_MDFE",
        "origem_sha256": next(iter(conjunto_hash)),
        "linhas_totais": len(registros),
        "por_mes": [
            {"mes": mes, "linhas": x["linhas"],
             "tu_t": round(x["tu_t"], 3), "tku": round(x["tku"], 3)}
            for mes, x in sorted(por_mes.items())
        ],
        "fluxos_mt_por_estacao": [
            {"mes": k[0], "mercadoria_fonte": k[1],
             "estacao_origem": k[2], "estacao_destino": k[3],
             "destino_uf": k[4], "linhas": v["linhas"], "tu_t": round(v["tu_t"], 3)}
            for k, v in sorted(mt.items())
        ],
        "limitacoes": (
            "Estação não equivale a município",
            "Movimento ferroviário não determina destinatário industrial",
            "Não é base rodoviária MDF-e",
        ),
    }
