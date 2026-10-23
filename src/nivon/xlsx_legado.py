from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from xml.etree import ElementTree as ET

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF = re.compile(r"^([A-Z]+)([0-9]+)$")
_MAX_XLSX_BYTES = 50 * 1024 * 1024
_MAX_ZIP_ENTRIES = 5000
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 250


@dataclass(frozen=True)
class XlsxSheet:
    name: str
    rows: list[list[Any]]


def _column_index(reference: str) -> int:
    match = _CELL_REF.match(reference.upper())
    if not match:
        raise ValueError(f"referencia XLSX invalida: {reference!r}")
    letters = match.group(1)
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _validate_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise ValueError(f"XLSX excede limite de {_MAX_ZIP_ENTRIES} entradas")
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise ValueError("XLSX criptografado não é aceito")
        if info.file_size > _MAX_MEMBER_BYTES:
            raise ValueError(f"entrada XLSX excessiva: {info.filename}")
        total += info.file_size
        if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("XLSX excede limite total descompactado")
        if info.compress_size > 0 and info.file_size >= 1024 * 1024:
            ratio = info.file_size / info.compress_size
            if ratio > _MAX_COMPRESSION_RATIO:
                raise ValueError(f"XLSX com taxa de compressão suspeita: {info.filename}")


def _safe_xml(payload: bytes) -> Any:
    # O parser padrão não processa DTD/entidades de fontes não confiáveis.
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("DTD/ENTITY não admitidos em workbook")
    return ET.fromstring(payload)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _safe_xml(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(f"{{{_NS_MAIN}}}si"):
        parts = [node.text or "" for node in item.iter(f"{{{_NS_MAIN}}}t")]
        values.append("".join(parts))
    return values


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = _safe_xml(archive.read("xl/workbook.xml"))
    relationships = _safe_xml(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall(f"{{{_NS_PKG_REL}}}Relationship")
    }
    out: list[tuple[str, str]] = []
    sheets = workbook.find(f"{{{_NS_MAIN}}}sheets")
    if sheets is None:
        return out
    for sheet in sheets.findall(f"{{{_NS_MAIN}}}sheet"):
        if len(out) >= 50:
            raise ValueError("numero excessivo de abas")
        rel_id = sheet.attrib.get(f"{{{_NS_REL}}}id")
        target = rel_map.get(rel_id or "")
        if not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.lstrip("./")
        # XLSX relationship targets must remain inside the archive's xl/ tree.
        parts = path.replace("\\", "/").split("/")
        if ".." in parts or not path.startswith("xl/"):
            raise ValueError(f"relationship XLSX inseguro: {target}")
        out.append((sheet.attrib.get("name", "Sheet"), path))
    return out


def _parse_cell(cell: Any, shared: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = cell.find(f"{{{_NS_MAIN}}}is")
        if text is None:
            return ""
        return "".join(node.text or "" for node in text.iter(f"{{{_NS_MAIN}}}t"))

    value_node = cell.find(f"{{{_NS_MAIN}}}v")
    if value_node is None or value_node.text is None:
        return None
    raw = value_node.text
    if cell_type == "s":
        index = int(raw)
        return shared[index] if 0 <= index < len(shared) else raw
    if cell_type in {"str", "e"}:
        return raw
    if cell_type == "b":
        return raw == "1"
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def _parse_sheet(xml: bytes, shared: list[str]) -> list[list[Any]]:
    root = _safe_xml(xml)
    sheet_data = root.find(f"{{{_NS_MAIN}}}sheetData")
    if sheet_data is None:
        return []
    rows: list[list[Any]] = []
    for row in sheet_data.findall(f"{{{_NS_MAIN}}}row"):
        cells: dict[int, Any] = {}
        for cell in row.findall(f"{{{_NS_MAIN}}}c"):
            reference = cell.attrib.get("r")
            if not reference:
                continue
            cells[_column_index(reference)] = _parse_cell(cell, shared)
        if not cells:
            rows.append([])
            continue
        width = max(cells) + 1
        if width > 256 or len(rows) > 150000:
            raise ValueError("planilha com dimensões não suportadas")
        values = [None] * width
        for index, value in cells.items():
            values[index] = value
        while values and values[-1] is None:
            values.pop()
        rows.append(values)
    return rows


def read_xlsx(payload: bytes) -> list[XlsxSheet]:
    """Le workbook XLSX sem Excel/LibreOffice e sem avaliar formulas.

    O leitor preserva valores armazenados no arquivo. Datas formatadas permanecem
    como numeros seriais; a interpretacao semantica fica a cargo do parser de dominio.
    Arquivos são limitados e XML é processado com bloqueio explícito de DTD/entidades para reduzir risco de
    entidades externas, expansão XML e ZIP bombs vindos de fontes externas.
    """
    if not isinstance(payload, bytes) or len(payload) > _MAX_XLSX_BYTES:
        raise ValueError(f"XLSX excede limite de {_MAX_XLSX_BYTES} bytes")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            _validate_archive(archive)
            shared = _shared_strings(archive)
            sheets: list[XlsxSheet] = []
            for name, path in _sheet_targets(archive):
                if path not in archive.namelist():
                    raise ValueError(f"worksheet ausente no XLSX: {path}")
                sheets.append(XlsxSheet(name=name, rows=_parse_sheet(archive.read(path), shared)))
            return sheets
    except zipfile.BadZipFile as exc:
        raise ValueError("payload não é XLSX/ZIP válido") from exc
