"""FAOSTAT QCL — extrator ZIP seletivo, com stage SQLite versionado.

Apenas soja/milho/trigo, produção em toneladas, BRA/ARG/USA, janela de anos.
O ZIP de cerca de 33 MB é baixado UMA vez para um arquivo temporário local.
O CSV de milhões de linhas é percorrido por streaming; somente linhas filtradas
ocupam memória. Sem deploy, cron, GCP, API keys ou publicação automática.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

QCL_URL = ("https://bulks-faostat.fao.org/production/"
           "Production_Crops_Livestock_E_All_Data_(Normalized).zip")
QCL_CSV = "Production_Crops_Livestock_E_All_Data_(Normalized).csv"
AREAS = {"BRA": "21", "ARG": "9", "USA": "231"}
ITEMS = {"SOJA": "236", "MILHO": "56", "TRIGO": "15"}
ELEMENT = "5510"
MAX_DOWNLOAD = 43_000_000
MAX_SCAN = 5_000_000
MAX_UNCOMPRESSED = 950_000_000
MAX_MATCHES = 600
REQUIRED = {"Area Code", "Item Code", "Element Code",
            "Year", "Unit", "Value", "Flag"}
USER_AGENT = "NIVON/0.1 (pesquisa-nao-comercial)"


class ErroQCL(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _utc(s):
    if not isinstance(s, str):
        raise ErroQCL("data de coleta ausente")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroQCL("data de coleta inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroQCL("coleta sem fuso")
    return dt.astimezone(timezone.utc).isoformat()


def validar_recorte(*, pais="BRA", cultura="SOJA", inicio=2015, fim=2024):
    if pais not in AREAS or cultura not in ITEMS:
        raise ErroQCL("área/cultura fora da allowlist")
    if (type(inicio) is not int or type(fim) is not int or
            inicio < 1961 or fim > 2100 or inicio > fim or fim-inicio > 40):
        raise ErroQCL("intervalo de anos não permitido")


def url_qcl_manifest(manifest: dict) -> str:
    """Obter URL somente de um manifesto já validado pelo parser canônico."""
    records = manifest.get("dominios_prioritarios") if isinstance(manifest, dict) else None
    if not isinstance(records, list):
        raise ErroQCL("manifesto normalizado ausente")
    found = [x for x in records if isinstance(x, dict) and x.get("dominio") == "QCL"]
    if len(found) != 1:
        raise ErroQCL("domínio QCL ausente ou duplicado")
    row = found[0]
    url = row.get("arquivo_zip_url_somente_referencia")
    if url != QCL_URL or not row.get("data_atualizacao_dataset"):
        raise ErroQCL("arquivo QCL divergente do manifest oficial")
    return url


def baixar_zip_qcl(*, manifest: dict, executar=False, abridor=None) -> tuple:
    """Retorna SpooledTemporaryFile posicionada em zero, sha256 e bytes.

    O caller deve fechar o arquivo (context manager/finally), sem persistência.
    """
    url = url_qcl_manifest(manifest)
    if executar is not True:
        raise PermissionError("download histórico desabilitado por padrão")
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != "bulks-faostat.fao.org" or
            p.path != "/production/" + QCL_CSV[:-4] + ".zip" or
            p.port not in (None, 443) or p.query or p.fragment or
            p.username or p.password):
        raise ErroQCL("origem QCL não homologada")
    cliente = abridor if abridor is not None else build_opener(_NoRedirect())
    req = Request(url, headers={"Accept": "application/zip,application/octet-stream",
                                "User-Agent": USER_AGENT})
    temp = tempfile.SpooledTemporaryFile(max_size=2_000_000, mode="w+b")
    checksum = hashlib.sha256()
    size = 0
    try:
        with cliente.open(req, timeout=40) as resp:
            if int(resp.status) != 200 or resp.geturl() != url:
                raise ErroQCL("HTTP/redirect não permitido")
            mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
            if mime not in ("application/zip", "application/x-zip-compressed",
                            "application/octet-stream"):
                raise ErroQCL("ZIP com MIME incompatível")
            stated = resp.headers.get("Content-Length")
            if stated and (not stated.isdecimal() or int(stated) > MAX_DOWNLOAD):
                raise ErroQCL("ZIP acima de limite")
            while True:
                buf = resp.read(131_072)
                if not isinstance(buf, bytes):
                    raise ErroQCL("resposta não binária")
                if not buf:
                    break
                size += len(buf)
                if size > MAX_DOWNLOAD:
                    raise ErroQCL("ZIP excedeu limite de download")
                checksum.update(buf)
                temp.write(buf)
        if size < 100 or size < 22:
            raise ErroQCL("ZIP incompleto")
        temp.seek(0)
        return temp, checksum.hexdigest(), size
    except Exception:
        temp.close()
        raise


def _valor(source):
    if not isinstance(source, str) or not source.strip():
        raise ErroQCL("quantidade numérica vazia")
    try:
        val = Decimal(source)
    except InvalidOperation as exc:
        raise ErroQCL("quantidade não numérica") from exc
    if not val.is_finite() or val < 0 or val > Decimal("100000000000000"):
        raise ErroQCL("quantidade fora de faixa")
    return format(val, "f")


def extrair_qcl(stream, *, sha256_zip: str, zip_bytes: int, coleta: str,
                data_atualizacao_fonte: str,
                pais="BRA", cultura="SOJA", inicio=2015, fim=2024) -> dict:
    validar_recorte(pais=pais, cultura=cultura, inicio=inicio, fim=fim)
    coletado_em = _utc(coleta)
    if (not isinstance(sha256_zip, str) or len(sha256_zip) != 64 or
            any(x not in "0123456789abcdef" for x in sha256_zip) or
            type(zip_bytes) is not int or not 1 <= zip_bytes <= MAX_DOWNLOAD):
        raise ErroQCL("hash/tamanho ZIP inválidos")
    if not isinstance(data_atualizacao_fonte, str) or len(data_atualizacao_fonte) > 32:
        raise ErroQCL("data de atualização da fonte ausente")
    try:
        z = zipfile.ZipFile(stream)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ErroQCL("ZIP inválido") from exc
    with z:
        info = z.infolist()
        if not 1 <= len(info) <= 30:
            raise ErroQCL("número de partes ZIP fora de limite")
        if sum(x.file_size for x in info) > MAX_UNCOMPRESSED:
            raise ErroQCL("ZIP descomprimido demasiado")
        for x in info:
            path = x.filename.replace("\\", "/")
            if (path.startswith("/") or ".." in path.split("/") or
                    x.flag_bits & 1 or x.file_size > MAX_UNCOMPRESSED or
                    not (path.endswith(".csv") and "/" not in path)):
                raise ErroQCL("ZIP com entradas inseguras")
        files = [x for x in info if x.filename == QCL_CSV]
        if len(files) != 1:
            raise ErroQCL("CSV normalizado QCL não encontrado")
        if files[0].file_size > MAX_UNCOMPRESSED or files[0].compress_size > MAX_DOWNLOAD:
            raise ErroQCL("arquivo interno acima de limite")
        count = 0
        obs = []
        selected = set()
        try:
            with z.open(files[0]) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="",
                                      errors="strict") as txt:
                    reader = csv.DictReader(txt)
                    fields = reader.fieldnames
                    if (not fields or not REQUIRED <= set(fields) or
                            len(fields) > 40 or len(fields) != len(set(fields))):
                        raise ErroQCL("colunas FAOSTAT QCL ausentes/duplicadas")
                    for row in reader:
                        count += 1
                        if count > MAX_SCAN:
                            raise ErroQCL("scan excede limite de 5 milhões")
                        if None in row or any(x is None for x in row.values()):
                            raise ErroQCL("CSV com colunas desalinhadas")
                        if (row["Area Code"] != AREAS[pais] or
                                row["Item Code"] != ITEMS[cultura] or
                                row["Element Code"] != ELEMENT):
                            continue
                        try:
                            ano = int(row["Year"])
                        except ValueError as exc:
                            raise ErroQCL("ano filtrado não numérico") from exc
                        if not inicio <= ano <= fim:
                            continue
                        if "Year Code" in row and str(row["Year Code"]) != str(ano):
                            raise ErroQCL("ano e código ano divergentes")
                        if row["Unit"].strip() != "t":
                            raise ErroQCL("produção QCL em unidade inesperada")
                        key = (pais, cultura, ELEMENT, ano)
                        if key in selected:
                            raise ErroQCL("duplicata de indicador/ano dentro do ZIP")
                        selected.add(key)
                        if len(obs) >= MAX_MATCHES:
                            raise ErroQCL("mais resultados que o recorte permite")
                        obs.append({
                            "dataset_id": "FAO_FAOSTAT_LONG_RUN",
                            "source_id": "FAO", "dominio": "QCL",
                            "pais": pais, "cultura": cultura,
                            "area_code": AREAS[pais], "item_code": ITEMS[cultura],
                            "element_code": ELEMENT, "ano": ano,
                            "data_referencia": str(ano), "competencia": str(ano),
                            "data_publicacao": None, "data_coleta": coletado_em,
                            "valor": _valor(row["Value"]), "unidade": "t",
                            "flag_fonte": row["Flag"],
                            "nota_fonte": row.get("Note") or None,
                            "natureza": "ESTATISTICA_PRODUCAO_FAOSTAT_REVISAO_POSSIVEL",
                            "source_sha256": sha256_zip,
                            "data_atualizacao_fonte": data_atualizacao_fonte,
                        })
        except UnicodeError as exc:
            raise ErroQCL("QCL CSV não UTF-8, encoding exige homologação") from exc
    if count == 0:
        raise ErroQCL("arquivo normalizado vazio")
    if not obs:
        raise ErroQCL("nenhum registro com códigos/recorte selecionados")
    obs.sort(key=lambda r: r["ano"])
    return {
        "dataset_id": "FAO_FAOSTAT_LONG_RUN", "fonte_id": "FAO",
        "dominio": "QCL", "filtro": {"pais": pais,"cultura": cultura,
                                   "inicio": inicio,"fim": fim},
        "observacoes": obs, "selecionadas": len(obs),
        "linhas_varridas": count, "sha256_zip": sha256_zip,
        "bytes_download": zip_bytes, "data_coleta": coletado_em,
        "data_atualizacao_fonte": data_atualizacao_fonte,
        "data_publicacao": None, "habilitado_para_publicacao": False,
        "completo_no_arquivo": True, "estado": "QCL_FILTRADO_SEM_PUBLICACAO",
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS faostat_qcl_snapshot (
  dataset_id TEXT NOT NULL,
  pais TEXT NOT NULL,
  cultura TEXT NOT NULL,
  area_code TEXT NOT NULL,
  item_code TEXT NOT NULL,
  element_code TEXT NOT NULL,
  ano INTEGER NOT NULL,
  unidade TEXT NOT NULL,
  valor TEXT NOT NULL,
  flag_fonte TEXT,
  data_referencia TEXT NOT NULL,
  competencia TEXT NOT NULL,
  data_publicacao TEXT,
  data_coleta TEXT NOT NULL,
  data_atualizacao_fonte TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  PRIMARY KEY(dataset_id,pais,cultura,element_code,ano,source_sha256)
);
CREATE INDEX IF NOT EXISTS idx_faostat_qcl_asof
  ON faostat_qcl_snapshot (pais,cultura,ano,data_coleta);
"""


def gravar_snapshot_sqlite(snapshot: dict, *, arquivo_banco: str) -> dict:
    """Stage local opt-in: arquivo SQLite ou :memory:, nunca GCP."""
    if snapshot.get("estado") != "QCL_FILTRADO_SEM_PUBLICACAO":
        raise ErroQCL("snapshot não homologado para staging")
    obs = snapshot.get("observacoes")
    if not isinstance(obs, list) or not 1 <= len(obs) <= MAX_MATCHES:
        raise ErroQCL("coleção inesperada")
    if (not isinstance(arquivo_banco, str) or not arquivo_banco or
            "\x00" in arquivo_banco):
        raise ErroQCL("caminho SQLite inválido")
    con = sqlite3.connect(arquivo_banco, timeout=10)
    try:
        con.executescript(SCHEMA)
        inicio = con.total_changes
        with con:
            for row in obs:
                if (row.get("source_sha256") != snapshot.get("sha256_zip") or
                        row.get("data_coleta") != snapshot.get("data_coleta") or
                        row.get("unidade") != "t"):
                    raise ErroQCL("observação inconsistente com snapshot")
                con.execute("""INSERT OR IGNORE INTO faostat_qcl_snapshot
                   (dataset_id,pais,cultura,area_code,item_code,element_code,
                    ano,unidade,valor,flag_fonte,data_referencia,competencia,
                    data_publicacao,data_coleta,data_atualizacao_fonte,source_sha256)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(row[k] for k in (
                        "dataset_id","pais","cultura","area_code","item_code",
                        "element_code","ano","unidade","valor","flag_fonte",
                        "data_referencia","competencia","data_publicacao",
                        "data_coleta","data_atualizacao_fonte","source_sha256")))
        inserted = con.total_changes - inicio
        return {"dataset_id": snapshot["dataset_id"],
                "selecionadas": len(obs), "inseridas": inserted,
                "duplicadas_ignoradas": len(obs)-inserted,
                "sqlite_local": True, "cloud_write": False,
                "agendamento": False}
    finally:
        con.close()


def executar_qcl(*, manifest:dict, pais="BRA",cultura="SOJA",
                 inicio=2015,fim=2024,executar=False,abridor=None,
                 coleta=None,arquivo_banco=None) -> dict:
    """End-to-end sob demanda. SQLite gravado só com arquivo_banco explícito."""
    validar_recorte(pais=pais,cultura=cultura,inicio=inicio,fim=fim)
    url_qcl_manifest(manifest)
    if executar is not True:
        raise PermissionError("download QCL não ativado")
    registros = [x for x in manifest["dominios_prioritarios"] if x["dominio"]=="QCL"]
    data_fonte = registros[0]["data_atualizacao_dataset"]
    coleta = _utc(coleta or datetime.now(timezone.utc).isoformat())
    temp, sha, num_bytes = baixar_zip_qcl(manifest=manifest,executar=True,abridor=abridor)
    try:
        snapshot = extrair_qcl(temp,sha256_zip=sha,zip_bytes=num_bytes,
                              coleta=coleta,data_atualizacao_fonte=data_fonte,
                              pais=pais,cultura=cultura,inicio=inicio,fim=fim)
    finally:
        temp.close()
    retorno = {
        "dataset_id": snapshot["dataset_id"],"selecionadas": snapshot["selecionadas"],
        "linhas_varridas": snapshot["linhas_varridas"],
        "sha256_zip": snapshot["sha256_zip"],"bytes_download":num_bytes,
        "data_coleta":coleta,"persistencia":None,
        "validacao_operacional":False}
    if arquivo_banco is not None:
        retorno["persistencia"] = gravar_snapshot_sqlite(snapshot,arquivo_banco=arquivo_banco)
    return retorno
