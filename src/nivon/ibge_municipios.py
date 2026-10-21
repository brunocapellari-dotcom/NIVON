"""Normalizador offline da API IBGE Localidades (municipios).

Nenhum HTTP e nenhuma habilitacao de fontes. Somente identificadores canonicos,
sem inferir validade historica, cidade de embarque ou correspondencia incerta.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit


ENDPOINT = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
_UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


class ErroMunicipiosIBGE(ValueError):
    pass


def _carimbo(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroMunicipiosIBGE("data da coleta deve ser string ISO com fuso")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroMunicipiosIBGE("data da coleta invalida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroMunicipiosIBGE("data da coleta sem fuso")
    return dt.astimezone(timezone.utc).isoformat()


def _sem_duplicatas(pares):
    d = {}
    for k, v in pares:
        if k in d:
            raise ErroMunicipiosIBGE("JSON com chave duplicada")
        d[k] = v
    return d


def _uf_do_registro(item: dict) -> str:
    caminhos = (
        ("regiao-imediata", "regiao-intermediaria", "UF"),
        ("microrregiao", "mesorregiao", "UF"),
    )
    ufs = []
    for caminho in caminhos:
        node = item
        for campo in caminho:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(campo)
        if node is None:
            continue
        if not isinstance(node, dict) or node.get("sigla") not in _UFS:
            raise ErroMunicipiosIBGE("UF ausente/invalida no municipio")
        ufs.append(node["sigla"])
    if not ufs or len(set(ufs)) != 1:
        raise ErroMunicipiosIBGE("UF ausente ou divergente entre divisões regionais")
    return ufs[0]


def normalizar_municipios_ibge(payload: bytes, *, coletado_em: str,
                                consulta_url: str = ENDPOINT) -> dict:
    """Converte JSON oficial local em lista canonica, falhando em colisoes.

    A data de publicacao nao e disponibilizada pelo endpoint: permanece NULL.
    A consulta nao fornece validade historica nem reconciliacao de aliases.
    """
    p = urlsplit(consulta_url)
    if (p.scheme != "https" or p.netloc != "servicodados.ibge.gov.br" or
            p.path != "/api/v1/localidades/municipios" or p.query or p.fragment):
        raise ErroMunicipiosIBGE("URL fora do endpoint municipal oficial")
    coleta = _carimbo(coletado_em)
    if not isinstance(payload, bytes) or not payload or len(payload) > 8_000_000:
        raise ErroMunicipiosIBGE("payload ausente ou acima de 8 MB")
    try:
        dados = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_sem_duplicatas)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroMunicipiosIBGE("JSON municipal invalido") from exc
    if not isinstance(dados, list) or not 1 <= len(dados) <= 6500:
        raise ErroMunicipiosIBGE("API deve devolver lista municipal nao vazia e limitada")
    ids = set()
    nomes_uf = set()
    saida = []
    for idx, item in enumerate(dados):
        if not isinstance(item, dict):
            raise ErroMunicipiosIBGE(f"linha {idx}: objeto invalido")
        codigo = item.get("id")
        nome = item.get("nome")
        if type(codigo) is not int or not (1000000 <= codigo <= 9999999):
            raise ErroMunicipiosIBGE(f"linha {idx}: codigo de 7 digitos obrigatorio")
        if not isinstance(nome, str) or not nome.strip() or len(nome) > 150:
            raise ErroMunicipiosIBGE(f"linha {idx}: nome ausente")
        if any(ord(c) < 32 for c in nome):
            raise ErroMunicipiosIBGE("caracter de controle no nome")
        uf = _uf_do_registro(item)
        # Dois municipios com o mesmo nome na mesma UF exigem auditoria.
        chave = (uf, _chave_nome(nome))
        if codigo in ids or chave in nomes_uf:
            raise ErroMunicipiosIBGE("codigo duplicado ou nome conflitante dentro da UF")
        ids.add(codigo)
        nomes_uf.add(chave)
        saida.append({"codigo_ibge": str(codigo), "nome": nome.strip(), "uf": uf})
    saida.sort(key=lambda x: x["codigo_ibge"])
    return {
        "dataset_id": "IBGE_CODIGOS_MUNICIPIOS", "fonte_id": "IBGE",
        "url": consulta_url, "sha256_original": hashlib.sha256(payload).hexdigest(),
        "coleta": coleta, "publicacao": None, "referencia": None,
        "competencia": None, "municipios": saida, "quantidade": len(saida),
        "situacao": "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO_NEM_ATIVADO",
        "restricao": "sem historico de vigencia ou aliases; nao converter ausencia em zero",
    }


def _chave_nome(nome: str) -> str:
    t = unicodedata.normalize("NFKD", nome)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.casefold().strip())


def resolver_municipio(registros: list[dict], *, nome: str, uf: str | None = None) -> dict:
    """Pesquisa somente igualdade normalizada; nenhuma adivinhacao por fuzzy match."""
    if not isinstance(nome, str) or not nome.strip() or (uf is not None and uf not in _UFS):
        raise ErroMunicipiosIBGE("nome/UF invalidos")
    resultado = [m for m in registros if _chave_nome(m["nome"]) == _chave_nome(nome)
                 and (uf is None or m["uf"] == uf)]
    if len(resultado) != 1:
        raise ErroMunicipiosIBGE("municipio nao encontrado ou ambiguo; exige desambiguacao")
    return dict(resultado[0])
