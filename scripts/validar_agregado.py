#!/usr/bin/env python3
"""Validação de publicabilidade de agregado municipal SIPEAGRO.

Não confirma verdade cadastral; só impede PII/linhas brutas no artefato.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


class ErroPublicacao(ValueError):
    pass


ALLOWED_CITY_FIELDS = frozenset({"uf", "municipio", "registros_distintos"})
BANNED_TEXT = ("CPF_CNPJ", "RAZAO_SOCIAL", "NUMERO_REGISTRO_ESTABELECIMENTO",
               "EMAIL", "TELEFONE", "LOGRADOURO")


def validar(publicacao: dict) -> dict:
    if publicacao.get("fonte") != "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL":
        raise ErroPublicacao("fonte oficial divergente")
    if publicacao.get("licenca_catalogo") != "Creative Commons Attribution":
        raise ErroPublicacao("atribuição/licença ausente")
    nomes = publicacao.get("municipios_candidatos")
    if not isinstance(nomes, list) or not 1 <= len(nomes) <= 6000:
        raise ErroPublicacao("lista de municípios vazia ou excessiva")
    if len(nomes) != publicacao.get("municipios_distintos_com_fabricante_ativo_racao"):
        raise ErroPublicacao("contagem de municípios inconsistente")
    chaves = set()
    for item in nomes:
        if not isinstance(item, dict) or set(item) != ALLOWED_CITY_FIELDS:
            raise ErroPublicacao("campos municipais não permitidos")
        uf = item["uf"]
        m = item["municipio"]
        n = item["registros_distintos"]
        if (not isinstance(uf, str) or not re.fullmatch(r"[A-Z]{2}", uf)
                or not isinstance(m, str) or not re.fullmatch(r"[A-ZÀ-Ÿ0-9 /.'-]{2,100}", m)
                or type(n) is not int or n < 0):
            raise ErroPublicacao("valor municipal inválido")
        if (uf, m) in chaves:
            raise ErroPublicacao("município repetido")
        chaves.add((uf, m))
    serialized = json.dumps(publicacao, ensure_ascii=False)
    if any(termo in serialized.upper() for termo in BANNED_TEXT):
        raise ErroPublicacao("identificador pessoal/empresarial em agregado")
    return {"municipios_validados": len(nomes), "publicavel": True,
            "natureza": "GEOGRAFIA_AGREGADA_NAO_CONSUMO_REAL"}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/validar_agregado.py arquivo.json")
    arq = Path(sys.argv[1])
    if arq.stat().st_size > 600_000:
        raise SystemExit("arquivo agregado acima do limite")
    try:
        print(json.dumps(validar(json.loads(arq.read_text(encoding="utf-8"))),
                         ensure_ascii=False))
    except (ErroPublicacao, ValueError) as exc:
        print(json.dumps({"publicavel": False, "erro": type(exc).__name__}))
        raise SystemExit(2)
