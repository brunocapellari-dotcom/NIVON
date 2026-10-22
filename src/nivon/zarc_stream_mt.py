"""Download e leitura integral STREAMING do ZARC 2026/27, sem persistência.

CSV oficial MAPA, CC Atribuição declarada:
https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico
Apenas uma edição e uma requisição explicitamente habilitada. Mantém códigos
dec1..dec36 BRUTOS — não interpreta classes nem recomenda plantio.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, HTTPRedirectHandler, build_opener

URL = (
    "https://dados.agricultura.gov.br/dataset/"
    "6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/"
    "139e5a60-1f43-4cc8-aeab-a35dbbf816c0/download/"
    "dados-abertos-tabua-de-risco-safra-2026-2027.csv"
)
FIXOS = (
    "Nome_cultura","SafraIni","SafraFin","Cod_Cultura","Cod_Ciclo",
    "Cod_Solo","geocodigo","UF","municipio","Cod_Clima","Nome_Clima",
    "Cod_Outros_Manejos","Nome_Outros_Manejos","Produtividade","Cod_NM",
    "Cod_Munic","Cod_Meso","Cod_Micro","Portaria"
)
DEC = tuple("dec" + str(n) for n in range(1, 37))
COLUNAS = FIXOS + DEC
# Tamanho comprovado via Content-Range HTTP 206 em 22/10/2026:
# 211.652.014 bytes (GitHub Actions #39854558010). Teto de 230 MB
# restrito a esta URL/edicao. Se crescer além, bloquear para reavaliar.
MAX_DOWNLOAD = 230_000_000
MAX_LINHAS = 5_000_000
MAX_GRUPOS = 500
MAX_PORTARIAS = 10_000

class ErroZarcStream(ValueError):
    pass

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _utc(instante):
    if not isinstance(instante, datetime) or instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroZarcStream("instante de coleta inválido")
    return instante.astimezone(timezone.utc).isoformat()

def _analisar_arquivo(fh, *, sha256, bytes_baixados, coleta, max_linhas=MAX_LINHAS):
    """Varredura sequencial, agregando contagem de linhas — NÃO de risco."""
    if not isinstance(sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ErroZarcStream("hash total ausente")
    if type(bytes_baixados) is not int or not 1 <= bytes_baixados <= MAX_DOWNLOAD:
        raise ErroZarcStream("tamanho inválido")
    if type(max_linhas) is not int or not 1 <= max_linhas <= MAX_LINHAS:
        raise ErroZarcStream("max_linhas inválido")
    fh.seek(0)
    txt = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="", errors="strict")
    try:
        header = txt.readline()
        if not header or len(header) > 20_000:
            raise ErroZarcStream("cabeçalho inválido")
        delim = ";" if header.count(";") > header.count(",") else ","
        txt.seek(0)
        reader = csv.DictReader(txt, delimiter=delim, restkey="_EXTRA", restval=None)
        names = reader.fieldnames
        if names != list(COLUNAS):
            raise ErroZarcStream("layout CSV não corresponde às 55 colunas oficiais")
        total = 0
        mt = 0
        classes = Counter()
        municipios = set()
        portarias = set()
        safras = set()
        valores_dec = Counter()
        for row in reader:
            total += 1
            if total > max_linhas:
                raise ErroZarcStream("excedeu limite de linhas do arquivo")
            if ("_EXTRA" in row or any(v is None for v in row.values())
                    or len(row) != len(COLUNAS)):
                raise ErroZarcStream("CSV com campos não alinhados")
            if row["UF"].strip() != "MT":
                continue
            mt += 1
            c = row["Nome_cultura"].strip()
            ibge = row["geocodigo"].strip()
            if (not 1 <= len(c) <= 100 or not re.fullmatch(r"\d{7}", ibge)
                    or row["SafraIni"].strip() != "2026"
                    or row["SafraFin"].strip() != "2027"):
                raise ErroZarcStream("linha MT fora do contrato territorial/safra")
            classes[c] += 1
            municipios.add(ibge)
            if len(classes) > MAX_GRUPOS or len(municipios) > 1500:
                raise ErroZarcStream("cardinalidade de agregação excessiva")
            p = row["Portaria"].strip()
            if not p or len(p) > 300:
                raise ErroZarcStream("referência de portaria ausente")
            portarias.add(p)
            if len(portarias) > MAX_PORTARIAS:
                raise ErroZarcStream("referências de portarias excessivas")
            safras.add((row["SafraIni"].strip(), row["SafraFin"].strip()))
            for k in DEC:
                v = row[k].strip()
                if len(v) > 100:
                    raise ErroZarcStream("valor decendial não validado")
                valores_dec[v if v else "<VAZIO>"] += 1
                if len(valores_dec) > 80:
                    raise ErroZarcStream("muitas codificações decendiais")
        if total == 0 or mt == 0:
            raise ErroZarcStream("arquivo não contém registros MT")
        return {
            "dataset_id": "ZARC_JANELAS", "fonte_id": "ZARC",
            "competencia": "2026/2027", "referencia": None,
            "publicacao": None, "coleta": coleta,
            "sha256_original": sha256, "bytes_originais": bytes_baixados,
            "linhas_total_arquivo": total, "linhas_mt": mt,
            "municipios_ibge_mt": len(municipios),
            "linhas_por_cultura_nome_original": dict(sorted(classes.items())),
            "portarias_distintas_mt": len(portarias),
            "safras_mt": sorted([a + "/" + b for a,b in safras]),
            "codigos_decendiais_brutos_diferentes": len(valores_dec),
            "valores_decendiais_interpretados": False,
            "classe_evidencia": "INFORMADO_TABELA_ZARC_NAO_METEOROLOGIA_OBSERVADA",
            "estado": "ARQUIVO_INTEGRAL_VALIDADO_ESTRUTURALMENTE_SEM_QC_AGRONOMICO",
            "persistido": False, "publicavel": False,
        }
    except (UnicodeError, csv.Error) as exc:
        raise ErroZarcStream("falha de decodificação ou CSV") from exc
    finally:
        # Fecha wrapper. Arquivo temporário também é fechado pelo chamador.
        txt.detach()

def processar_zarc_mt(*, executar=False, abridor=None, instante=None,
                      max_download=MAX_DOWNLOAD):
    if executar is not True:
        raise PermissionError("DOWNLOAD_ZARC_DESATIVADO_POR_PADRAO")
    if type(max_download) is not int or not 4096 <= max_download <= MAX_DOWNLOAD:
        raise ErroZarcStream("limite de download inválido")
    dt = datetime.now(timezone.utc) if instante is None else instante
    coleta = _utc(dt)
    cliente = abridor if abridor is not None else build_opener(_NoRedirect())
    req = Request(URL, headers={"Accept": "text/csv,application/csv",
                                "User-Agent": "NIVON/0.1 pesquisa-nao-comercial"})
    with tempfile.SpooledTemporaryFile(max_size=2_000_000) as temp:
        with cliente.open(req, timeout=90) as resp:
            if int(resp.status) != 200 or resp.geturl() != URL:
                raise ErroZarcStream("HTTP/redirect inválido")
            mime = str(resp.headers.get("Content-Type", "")).split(";",1)[0].lower().strip()
            if mime not in ("text/csv","text/plain","application/octet-stream","application/csv"):
                raise ErroZarcStream("MIME não CSV")
            declared = resp.headers.get("Content-Length")
            if declared and (not declared.isdecimal() or int(declared) > max_download):
                raise ErroZarcStream("arquivo excede limite declarado")
            sha = hashlib.sha256()
            n = 0
            while True:
                b = resp.read(65_536)
                if not isinstance(b, bytes):
                    raise ErroZarcStream("download retornou bytes inválidos")
                if not b:
                    break
                n += len(b)
                if n > max_download:
                    raise ErroZarcStream("arquivo excede limite de download")
                temp.write(b)
                sha.update(b)
        return _analisar_arquivo(temp, sha256=sha.hexdigest(),
                                bytes_baixados=n, coleta=coleta)
