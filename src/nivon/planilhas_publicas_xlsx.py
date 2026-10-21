"""Conectores públicos XLSX: USDA AMS GTR e World Bank Pink Sheet.

Leitor OOXML limitado com biblioteca padrão. Não executa fórmulas, macros,
hiperlinks, conexões externas nem URLs presentes nas células. Mantém os
valores/texto originais até homologação de layouts, unidades e vintages.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from urllib.request import Request, HTTPRedirectHandler, build_opener
from xml.etree import ElementTree as ET

URLS = {
    "USDA_AMS_GTR_FRETE_MULTIMODAL":
        "https://www.ams.usda.gov/sites/default/files/media/GTRTable1.xlsx",
    "USDA_AMS_GTR_PRECO_BASIS_EXPORT":
        "https://www.ams.usda.gov/sites/default/files/media/GTRTable2A_B.xlsx",
    "WB_PINK_SHEET_COMMODITIES":
        "https://thedocs.worldbank.org/en/doc/18675f1d1639c7a34d463f59263ba0a2-0050012025/related/CMO-Historical-Data-Monthly.xlsx",
}
XLSX_MIME = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "application/octet-stream"}
N = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
OFFREL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_BYTES = 12_000_000


class ErroPlanilhaPublica(ValueError):
    pass


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _data_coleta(iso):
    if not isinstance(iso, str):
        raise ErroPlanilhaPublica("carimbo ausente")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPlanilhaPublica("coleta inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroPlanilhaPublica("coleta sem fuso horário")
    return dt.astimezone(timezone.utc).isoformat()


def _verificar_zip(blob: bytes):
    if not isinstance(blob, bytes) or not 1 <= len(blob) <= MAX_BYTES:
        raise ErroPlanilhaPublica("XLSX vazio ou muito grande")
    if not blob.startswith(b"PK\x03\x04"):
        raise ErroPlanilhaPublica("arquivo não é XLSX")
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        info = z.infolist()
    except (OSError, zipfile.BadZipFile) as e:
        raise ErroPlanilhaPublica("XLSX ZIP inválido") from e
    if len(info) > 300:
        raise ErroPlanilhaPublica("muitas partes internas")
    total = 0
    nomes = set()
    for f in info:
        nome = f.filename.replace("\\", "/")
        if (nome.startswith("/") or any(p in ("", ".", "..") for p in nome.split("/"))
                or f.file_size > 15_000_000 or f.compress_size > MAX_BYTES):
            raise ErroPlanilhaPublica("OOXML parte insegura ou gigante")
        total += f.file_size
        nomes.add(nome)
    if total > 35_000_000 or not {"xl/workbook.xml", "[Content_Types].xml"} <= nomes:
        raise ErroPlanilhaPublica("OOXML ausente ou risco de descompressão")
    if any("vbaProject" in x or x.startswith("xl/externalLinks/") for x in nomes):
        raise ErroPlanilhaPublica("macros/conexões externas não permitidas")
    return z


def _xml(z, path):
    if path not in z.namelist():
        raise ErroPlanilhaPublica("parte OOXML ausente: " + path)
    try:
        return ET.fromstring(z.read(path))
    except ET.ParseError as e:
        raise ErroPlanilhaPublica("XML malformado") from e


def _compartilhadas(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = _xml(z, "xl/sharedStrings.xml")
    strs = []
    for si in root.findall(N + "si"):
        texto = "".join(n.text or "" for n in si.iter(N + "t"))
        if len(texto) > 500:
            raise ErroPlanilhaPublica("texto de célula excede 500 caracteres")
        strs.append(texto)
        if len(strs) > 100_000:
            raise ErroPlanilhaPublica("shared strings excessivas")
    return strs


def _caminhos_planilhas(z):
    root = _xml(z, "xl/workbook.xml")
    relroot = _xml(z, "xl/_rels/workbook.xml.rels")
    relacionamentos = {}
    for r in relroot.findall(PKGREL + "Relationship"):
        rid = r.get("Id")
        target = r.get("Target", "").replace("\\", "/").lstrip("/")
        if r.get("TargetMode") == "External":
            continue
        path = target if target.startswith("xl/") else "xl/" + target
        if not path.startswith("xl/worksheets/") or ".." in path.split("/"):
            continue
        relacionamentos[rid] = path
    sheets = []
    for s in root.findall(N + "sheets/" + N + "sheet"):
        nome = s.get("name")
        rid = s.get(OFFREL + "id")
        if not isinstance(nome, str) or not 1 <= len(nome) <= 60 or rid not in relacionamentos:
            raise ErroPlanilhaPublica("planilha sem relação interna segura")
        sheets.append((nome, relacionamentos[rid]))
    if not 1 <= len(sheets) <= 30:
        raise ErroPlanilhaPublica("número de abas inválido")
    return sheets


def _indice_coluna(cell):
    m = re.fullmatch(r"([A-Z]{1,3})[1-9][0-9]*", cell or "")
    if not m:
        raise ErroPlanilhaPublica("referência OOXML incorreta")
    n = 0
    for c in m[1]:
        n = n * 26 + ord(c) - 64
    return n - 1


def _aba(z, path, shared):
    root = _xml(z, path)
    data = root.find(N + "sheetData")
    if data is None:
        return []
    out = []
    for row in data.findall(N + "row"):
        if len(out) >= 10_000:
            raise ErroPlanilhaPublica("mais de 10 mil linhas em uma aba")
        celulas = []
        for c in row.findall(N + "c"):
            idx = _indice_coluna(c.get("r"))
            if idx > 79:
                raise ErroPlanilhaPublica("mais de 80 colunas na aba")
            if idx < len(celulas):
                raise ErroPlanilhaPublica("coluna fora de ordem/duplicada")
            celulas.extend([None] * (idx-len(celulas)))
            typ = c.get("t", "n")
            value_elem = c.find(N + "v")
            raw = value_elem.text if value_elem is not None else None
            if c.find(N + "f") is not None:
                # Nunca avaliar fórmula; descartar seu cache para impedir dado não auditado.
                valor = None
            elif typ == "s":
                if raw is None:
                    valor = None
                else:
                    try:
                        numero = int(raw)
                        valor = shared[numero]
                    except (ValueError, IndexError) as e:
                        raise ErroPlanilhaPublica("índice sharedString inválido") from e
            elif typ == "inlineStr":
                el = c.find(N + "is")
                valor = "".join(v.text or "" for v in el.iter(N + "t")) if el is not None else None
            elif typ == "e":
                valor = None
            elif typ == "b":
                valor = raw == "1" if raw is not None else None
            elif typ in ("n", "str"):
                valor = raw
            else:
                raise ErroPlanilhaPublica("tipo de célula não homologado")
            if isinstance(valor, str) and len(valor) > 500:
                raise ErroPlanilhaPublica("célula acima de 500 caracteres")
            celulas.append(valor)
        if celulas:
            out.append({"linha_fisica": int(row.get("r", len(out)+1)),
                        "celulas": celulas})
    return out


def normalizar_planilha(blob: bytes, *, dataset_id: str, coletado_em: str) -> dict:
    if dataset_id not in URLS:
        raise ErroPlanilhaPublica("dataset XLSX não cadastrado")
    coleta = _data_coleta(coletado_em)
    z = _verificar_zip(blob)
    try:
        shared = _compartilhadas(z)
        abas = []
        for nome, path in _caminhos_planilhas(z):
            linhas = _aba(z, path, shared)
            abas.append({"aba": nome, "n_linhas": len(linhas),
                         "linhas": linhas})
    finally:
        z.close()
    if not any(x["n_linhas"] for x in abas):
        raise ErroPlanilhaPublica("todas as abas vazias")
    return {
        "dataset_id": dataset_id, "fonte_id": "WB" if dataset_id.startswith("WB_") else "USDA",
        "url": URLS[dataset_id], "abas": abas,
        "coleta": coleta, "publicacao": None, "referencia": None,
        "sha256_original": hashlib.sha256(blob).hexdigest(),
        "valores_monetarios_publicaveis": False,
        "unidades_e_vigencia_homologadas": False,
        "formulas_ignoradas": True,
        "estado": "ESTRUTURA_XLSX_EXTRAIDA_AGUARDANDO_MAPEAMENTO_SEMANTICO",
    }


def consultar_planilha(*, dataset_id: str, executar: bool = False,
                       abridor=None, instante=None):
    if dataset_id not in URLS:
        raise ErroPlanilhaPublica("dataset não cadastrado")
    if executar is not True:
        raise PermissionError("download pontual exige executar=True")
    instante = instante or datetime.now(timezone.utc)
    coleta = _data_coleta(instante.isoformat())
    cliente = abridor if abridor is not None else build_opener(_SemRedirecionamento())
    url = URLS[dataset_id]
    req = Request(url, headers={"Accept": ",".join(sorted(XLSX_MIME)),
                                "User-Agent": "NIVON/0.1 (pesquisa nao comercial)"})
    with cliente.open(req, timeout=25) as resp:
        if int(resp.status) != 200 or resp.geturl() != url:
            raise ErroPlanilhaPublica("HTTP erro ou redirecionamento não permitido")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in XLSX_MIME:
            raise ErroPlanilhaPublica("MIME de planilha não permitido")
        content = resp.read(MAX_BYTES+1)
        if len(content) > MAX_BYTES:
            raise ErroPlanilhaPublica("download excedeu limite")
    data = normalizar_planilha(content, dataset_id=dataset_id, coletado_em=coleta)
    return {"aquisicao": {"bytes": len(content), "sha256": data["sha256_original"],
                           "coleta": coleta}, "dados": data}
