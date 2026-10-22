"""Leitura limitada do CABEÇALHO e prefixo CSV CKAN (ZARC e CIOT).

Para arquivos >8 MB, lê até 512 KiB com Range e fecha conexão.
Nunca interpreta prefixo como arquivo completo, nunca segue redirect e
nunca armazena/publica dados. O SHA é apenas do prefixo efetivamente lido.
"""
from __future__ import annotations

import hashlib
import io
import csv
import re
from datetime import datetime, timezone
from urllib.request import Request, build_opener

from .fontes_abertas_lote import consultar as consultar_catalogo
from .coleta_ckan_csv_pontual import (
    FONTES_CSV_APROVADAS_PARA_ENSAIO, LICENCAS_CC_BY,
    _alvo, _SemRedirect, ErroCSVCKAN
)

PREFIXO_PADRAO = 512 * 1024
PREFIXO_MAX = 1024 * 1024


def _amostra_csv(bruto: bytes) -> dict:
    """Considerar somente linhas terminadas em LF; descartar linha truncada."""
    if not isinstance(bruto, bytes) or not bruto:
        raise ErroCSVCKAN("amostra CSV vazia")
    fim = bruto.rfind(b"\n")
    if fim < 0:
        raise ErroCSVCKAN("prefixo sem linha completa")
    # Excluir último registro parcial sem inferir sua validade.
    completo = bruto[:fim + 1]
    try:
        txt = completo.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroCSVCKAN("amostra não UTF-8") from exc
    linhas = txt.splitlines()
    if not linhas:
        raise ErroCSVCKAN("cabeçalho CSV ausente")
    delimitador = ";" if linhas[0].count(";") > linhas[0].count(",") else ","
    try:
        reader = csv.reader(io.StringIO(txt), delimiter=delimitador, strict=True)
        colunas = next(reader)
        if (not 1 <= len(colunas) <= 180
                or any(not 1 <= len(k.strip()) <= 140 for k in colunas)
                or len(set(colunas)) != len(colunas)):
            raise ErroCSVCKAN("cabeçalho CSV inválido/duplicado")
        n = 0
        for row in reader:
            if len(row) != len(colunas):
                raise ErroCSVCKAN("linha CSV incompleta/desalinhada")
            n += 1
            if n > 150_000:
                raise ErroCSVCKAN("prefixo excedeu limite de linhas")
    except (csv.Error, StopIteration) as exc:
        raise ErroCSVCKAN("parser CSV rejeitou amostra") from exc
    return {"colunas": [c.strip() for c in colunas],
            "linhas_amostra_completas": n,
            "bytes_linhas_completas": len(completo),
            "delimitador": delimitador}


def consultar_prefixo_ckan(*, fonte, recurso_id, executar=False,
                           abridor=None, instante=None, max_bytes=PREFIXO_PADRAO):
    if executar is not True:
        raise PermissionError("LEITURA_CSV_REDE_OFF")
    if fonte not in FONTES_CSV_APROVADAS_PARA_ENSAIO:
        raise PermissionError("fonte fora do recorte CSV público")
    if not isinstance(recurso_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", recurso_id):
        raise ErroCSVCKAN("resource UUID inválido")
    if type(max_bytes) is not int or not 4096 <= max_bytes <= PREFIXO_MAX:
        raise ErroCSVCKAN("limite de prefixo excedido")
    dt = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroCSVCKAN("coleta sem timezone")
    cliente = abridor if abridor is not None else build_opener(_SemRedirect())
    metadados = consultar_catalogo(fonte, executar=True, abridor=cliente, instante=dt)
    licenca = metadados.get("licenca_declarada")
    if not isinstance(licenca, str) or licenca.strip().lower() not in LICENCAS_CC_BY:
        raise PermissionError("licença do catálogo não validada para teste")
    rec = [x for x in metadados["recursos"] if x["id"].lower() == recurso_id.lower()]
    if len(rec) != 1:
        raise ErroCSVCKAN("recurso não encontrado no catálogo canônico")
    url = _alvo(fonte, rec[0])
    req = Request(url, headers={
        "Accept": "text/csv,application/csv",
        "Range": f"bytes=0-{max_bytes-1}",
        "User-Agent": "NIVON/0.1 pesquisa-nao-comercial"
    })
    with cliente.open(req, timeout=25) as resp:
        if int(resp.status) not in (200, 206) or resp.geturl() != url:
            raise ErroCSVCKAN("status ou redirect de CSV não permitido")
        status = int(resp.status)
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].lower().strip()
        if mime not in ("text/csv", "text/plain", "application/csv", "application/octet-stream"):
            raise ErroCSVCKAN("MIME incompatível com CSV")
        if status == 206:
            content_range = str(resp.headers.get("Content-Range", ""))
            if not content_range.startswith("bytes 0-"):
                raise ErroCSVCKAN("Range não corresponde ao prefixo")
        b = resp.read(max_bytes)
        if not isinstance(b, bytes) or not b:
            raise ErroCSVCKAN("prefixo vazio")
    amostra = _amostra_csv(b)
    return {
        "dataset_id": fonte, "recurso_id": recurso_id,
        "sha256_catalogo": metadados["sha256_original"],
        "sha256_prefixo": hashlib.sha256(b).hexdigest(),
        "bytes_prefixo_lidos": len(b),
        **amostra,
        "http_status": status, "suporte_range_comprovado": status == 206,
        "coleta": dt.astimezone(timezone.utc).isoformat(),
        "competencia": None, "publicacao": None, "referencia": None,
        "arquivo_completo": False, "hash_do_arquivo_completo": None,
        "estado": "PREFIXO_CSV_NAO_TOTAL_NAO_HOMOLOGADO",
        "chamadas_http": 2, "persistido": False, "publicavel": False,
    }
