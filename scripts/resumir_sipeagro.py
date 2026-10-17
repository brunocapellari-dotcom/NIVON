#!/usr/bin/env python3
"""Resumo geográfico do CSV público SIPEAGRO em execução efêmera.

Não grava arquivo, não imprime CPF/CNPJ, razão social nem número de registro.
A unidade de observação é cadastro, NÃO capacidade ou consumo de milho.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

URL = (
    "https://dados.agricultura.gov.br/dataset/"
    "52a01565-72d6-410e-b21b-64035831a7be/resource/"
    "378b184b-67bd-48fa-9901-17bb7a0700fb/download/"
    "sipeagroalimentacaoanimal.csv"
)
MAX_BYTES = 60_000_000
CAMPOS = {
    "UF", "MUNICIPIO", "NUMERO_REGISTRO_ESTABELECIMENTO",
    "STATUS_DO_REGISTRO", "AREA_ATUACAO", "ATIVIDADE", "CLASSIFICACAO",
}


def _norm(v: str) -> str:
    s = unicodedata.normalize("NFKD", (v or "").strip())
    return " ".join("".join(x for x in s if not unicodedata.combining(x)).upper().split())


def resumir(payload: bytes) -> dict:
    texto = payload.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(texto, newline=""), delimiter=";")
    if reader.fieldnames is None or not CAMPOS <= set(reader.fieldnames):
        raise ValueError("schema oficial diferente do esperado")
    contagem_linhas = 0
    linhas_elegiveis = 0
    sem_id = 0
    registros_unicos: set[tuple[str, str, str]] = set()
    cidades: set[tuple[str, str]] = set()
    municipios_por_uf: dict[str, set[str]] = defaultdict(set)
    registros_por_municipio: dict[tuple[str, str], set[str]] = defaultdict(set)
    for linha in reader:
        contagem_linhas += 1
        if contagem_linhas > 2_000_000:
            raise ValueError("limite de linhas excedido")
        if not ( _norm(linha.get("STATUS_DO_REGISTRO")) == "ATIVO" and
                 _norm(linha.get("AREA_ATUACAO")) == "ALIMENTACAO ANIMAL" and
                 _norm(linha.get("ATIVIDADE")) == "FABRICANTE" and
                 _norm(linha.get("CLASSIFICACAO")) == "RACAO"):
            continue
        uf = _norm(linha.get("UF"))
        municipio = _norm(linha.get("MUNICIPIO"))
        if len(uf) != 2 or not municipio:
            raise ValueError("município/UF vazio na linha elegível")
        linhas_elegiveis += 1
        cidades.add((uf, municipio))
        municipios_por_uf[uf].add(municipio)
        numero_registro = (linha.get("NUMERO_REGISTRO_ESTABELECIMENTO") or "").strip()
        if not numero_registro:
            sem_id += 1
            continue
        registros_unicos.add((uf, municipio, numero_registro))
        registros_por_municipio[(uf, municipio)].add(numero_registro)
    top = sorted(
        ((uf, cidade, len(regs)) for (uf, cidade), regs in registros_por_municipio.items()),
        key=lambda x: (-x[2], x[0], x[1]),
    )[:25]
    return {
        "licenca_catalogo": "Creative Commons Attribution",
        "fonte": "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL",
        "url": URL,
        "sha256_arquivo": hashlib.sha256(payload).hexdigest(),
        "data_coleta_utc": datetime.now(timezone.utc).isoformat(),
        "arquivo_bytes": len(payload),
        "linhas_do_arquivo": contagem_linhas,
        "linhas_filtradas_fabricante_ativo_racao": linhas_elegiveis,
        "registros_estabelecimento_distintos_com_identificador": len(registros_unicos),
        "linhas_elegiveis_sem_registro": sem_id,
        "municipios_distintos_com_fabricante_ativo_racao": len(cidades),
        "municipios_por_uf": {uf: len(municipios_por_uf[uf]) for uf in sorted(municipios_por_uf)},
        "municipios_com_mais_registros_top_25": [
            {"uf": uf, "municipio": cidade, "registros_distintos": n} for uf, cidade, n in top
        ],
        "natureza": "CADASTRO_OFICIAL_OBSERVADO_NAO_CONSUMO",
        "cautela": "A classificação RAÇÃO não comprova aves/suínos, capacidade, produção nem destino das cargas. Listagem pode conter erros/revisões e plantas com múltiplas atividades.",
        "privacidade": "Sem publicação de CPF_CNPJ, RAZAO_SOCIAL ou NUMERO_REGISTRO_ESTABELECIMENTO.",
    }


def executar() -> dict:
    req = Request(URL, headers={
        "Accept": "text/csv,application/octet-stream,text/plain",
        "User-Agent": "NIVON/0.1 (resumo geográfico de dados abertos MAPA)",
    })
    with urlopen(req, timeout=45) as response:
        origem = urlsplit(response.geturl())
        if origem.scheme != "https" or origem.hostname != "dados.agricultura.gov.br":
            raise ValueError("redirecionamento fora da fonte oficial")
        if int(response.status) != 200:
            raise ValueError("resposta HTTP incompleta")
        raw = response.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("arquivo vazio ou acima do teto")
    return resumir(raw)


if __name__ == "__main__":
    try:
        print(json.dumps(executar(), ensure_ascii=False, indent=2))
    except Exception as exc:
        # Logar somente classe do erro, evitando valores potencialmente identificáveis.
        print(json.dumps({"estado": "FALHA_RESUMO_MAPA", "classe_erro": type(exc).__name__}))
        raise SystemExit(2)
