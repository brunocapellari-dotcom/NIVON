#!/usr/bin/env python3
"""Inspeciona SOMENTE cabeçalho do CSV público SIPEAGRO, sem guardar registros.

Uso restrito à pesquisa de esquema dos dados abertos licenciados como CC BY.
A rotina nunca imprime linhas pessoais/empresariais, apenas nomes das colunas.
"""
from __future__ import annotations

import csv
import io
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

URL = (
    "https://dados.agricultura.gov.br/dataset/"
    "52a01565-72d6-410e-b21b-64035831a7be/resource/"
    "378b184b-67bd-48fa-9901-17bb7a0700fb/download/"
    "sipeagroalimentacaoanimal.csv"
)


def inspecionar() -> dict:
    req = Request(URL, headers={
        "User-Agent": "NIVON/0.1 (+auditoria somente cabecalho)",
        "Accept": "text/csv,application/octet-stream,text/plain",
        "Range": "bytes=0-131071",
    })
    with urlopen(req, timeout=25) as resposta:
        destino = urlsplit(resposta.geturl())
        if destino.scheme != "https" or destino.hostname != "dados.agricultura.gov.br":
            raise ValueError("redirecionamento fora do domínio oficial")
        dados = resposta.read(131072)
        mime = resposta.headers.get("Content-Type", "").split(";", 1)[0]
        if not dados:
            raise ValueError("resposta vazia")
        texto = None
        codificacao = ""
        for tentativa in ("utf-8-sig", "cp1252"):
            try:
                texto = dados.decode(tentativa, errors="strict")
                codificacao = tentativa
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            raise ValueError("codificação de amostra não suportada")
        primeira = texto.splitlines()[0]
        if len(primeira) > 32000:
            raise ValueError("cabeçalho excessivo")
        delimitador = ";" if primeira.count(";") >= primeira.count(",") else ","
        colunas = next(csv.reader(io.StringIO(primeira), delimiter=delimitador))
        if not colunas or len(colunas) == 1 or len(set(colunas)) != len(colunas):
            raise ValueError("cabeçalho ausente ou inválido")
        return {
            "fonte": "MAPA_SIPEAGRO_ALIMENTACAO_ANIMAL",
            "url_oficial": URL,
            "licenca_catalogo": "Creative Commons Attribution (confirmar atribuição)",
            "codigo_http": int(resposta.status),
            "tipo_conteudo": mime,
            "codificacao_amostra": codificacao,
            "delimitador": delimitador,
            "quantidade_colunas": len(colunas),
            "nomes_colunas": colunas,
            "observacao": "NAO COLETOU HISTORICO NEM VALIDOU OS VALORES DAS LINHAS",
        }


if __name__ == "__main__":
    try:
        print(json.dumps(inspecionar(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({
            "estado": "FALHA_INSPECAO_SCHEMA",
            "tipo_erro": type(exc).__name__,
            "detalhe": str(exc)[:400],
        }, ensure_ascii=False))
        raise SystemExit(2)
