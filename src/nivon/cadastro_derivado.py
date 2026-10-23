"""Consumidor do agregado geográfico de fábricas de ração do MAPA.

Nunca precisa receber CPF/CNPJ ou nome individual. O resultado é localização
de POSSÍVEL demanda industrial, não consumo efetivo nem espécie animal.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .destinos import FabricaMAPA, chave_municipio


class ErroCadastroDerivado(ValueError):
    pass


def carregar_municipios_racao(caminho: str | Path) -> dict:
    arquivo = Path(caminho)
    if arquivo.is_symlink() or not arquivo.is_file() or arquivo.suffix.lower() != ".json":
        raise ErroCadastroDerivado("arquivo JSON regular necessário")
    conteudo = arquivo.read_bytes()
    if not conteudo or len(conteudo) > 600_000:
        raise ErroCadastroDerivado("agregado ausente ou fora do limite")
    try:
        dados = json.loads(conteudo.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroCadastroDerivado("JSON agregado inválido") from exc
    if not isinstance(dados, dict) or dados.get("fonte") != "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL":
        raise ErroCadastroDerivado("fonte divergente")
    if dados.get("licenca_catalogo") != "Creative Commons Attribution":
        raise ErroCadastroDerivado("atribuição da fonte ausente")
    raw_sha = dados.get("sha256_arquivo")
    if not isinstance(raw_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_sha):
        raise ErroCadastroDerivado("hash da fonte primária ausente")
    linhas = dados.get("municipios_candidatos")
    total = dados.get("municipios_distintos_com_fabricante_ativo_racao")
    if not isinstance(linhas, list) or not 1 <= len(linhas) <= 6000 or len(linhas) != total:
        raise ErroCadastroDerivado("listagem ou contagem inconsistente")
    permitidos = {"uf", "municipio", "registros_distintos"}
    registros = []
    vistos = set()
    for item in linhas:
        if not isinstance(item, dict) or set(item) != permitidos:
            raise ErroCadastroDerivado("campos não autorizados no agregado")
        uf, cidade = item["uf"], item["municipio"]
        numero = item["registros_distintos"]
        if not isinstance(uf, str) or not isinstance(cidade, str) or type(numero) is not int or numero < 0:
            raise ErroCadastroDerivado("identidade municipal ou contagem inválida")
        try:
            chave = chave_municipio(uf, cidade)
        except ValueError as exc:
            raise ErroCadastroDerivado("município inválido") from exc
        if chave in vistos:
            raise ErroCadastroDerivado("município repetido")
        vistos.add(chave)
        registros.append(FabricaMAPA(
            uf=uf, municipio=cidade, fabricante=True, ativa=True,
            alimentacao_animal=True,
            fonte_id="SIPEAGRO_AGREGADO_" + raw_sha[:12],
            classe_produto="RAÇÃO",
        ))
    return {
        "fabrica_candidata_por_municipio": registros,
        "municipios": len(registros),
        "hash_arquivo_agregado_sha256": hashlib.sha256(conteudo).hexdigest(),
        "hash_arquivo_mapa_origem_sha256": raw_sha,
        "coletado_em": dados.get("data_coleta_utc"),
        "natureza": "CADASTRO_AGREGADO_NAO_CONSUMO",
    }
