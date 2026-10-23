"""Leitura OFFLINE e limitada de células OOXML já validadas pela cadeia CONAB.

Não infere cultura, unidade, indicador, status realizado, nem vintage temporal.
As células servem para auditoria exploratória do layout de um RAW capturado.
Este código não é sandbox de processo. Entradas externas exigem worker isolado.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .conab_anexo_xlsx_levantamento import ErroDocumentoConab, _estrutura_zip_xlsx
from .conab_ooxml_metadados import inspecionar_abas_ooxml_conab

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REF = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z")
_MAX_BYTES_SHEET = 8_000_000
_MAX_BYTES_SHARED = 5_000_000
_MAX_ROWS = 2000
_MAX_COLUMNS = 100
_MAX_CELLS = 10000


def _xml_limitado(z: ZipFile, path: str, maximum: int) -> ET.Element:
    try:
        member = z.getinfo(path)
        if member.file_size > maximum:
            raise ErroDocumentoConab("XML de células excede limite")
        body = z.read(member)
    except (KeyError, OSError, EOFError) as exc:
        raise ErroDocumentoConab("parte XML de células ausente/corrompida") from exc
    if len(body) > maximum or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ErroDocumentoConab("XML de células inseguro")
    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise ErroDocumentoConab("XML de células malformado") from exc


def _strings_compartilhadas(z: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = _xml_limitado(z, "xl/sharedStrings.xml", _MAX_BYTES_SHARED)
    if root.tag != _NS + "sst":
        raise ErroDocumentoConab("sharedStrings OOXML inválido")
    entries = root.findall(_NS + "si")
    if len(entries) > 10000:
        raise ErroDocumentoConab("sharedStrings acima do limite de inspeção")
    values = []
    for si in entries:
        text = "".join(e.text or "" for e in si.iter(_NS + "t"))
        if len(text) > 2500:
            raise ErroDocumentoConab("texto compartilhado excessivo")
        values.append(text)
    return values


def _numero(v: str) -> str:
    try:
        if len(v) > 80:
            raise ValueError("decimal excessivo")
        d = Decimal(v)
        if not d.is_finite() or abs(d.adjusted()) > 14:
            raise ValueError("decimal não finito ou fora do domínio")
    except (InvalidOperation, ValueError) as exc:
        raise ErroDocumentoConab("número OOXML inválido") from exc
    return str(d)


def _celula(c: ET.Element, compartilhadas: list[str]) -> dict:
    r = c.attrib.get("r")
    m = _REF.fullmatch(r) if isinstance(r, str) else None
    if not m:
        raise ErroDocumentoConab("referência de célula OOXML inválida")
    ncol = 0
    for char in m[1]:
        ncol = ncol * 26 + ord(char) - ord("A") + 1
    row = int(m[2])
    if row > _MAX_ROWS or ncol > _MAX_COLUMNS:
        raise ErroDocumentoConab("célula fora da janela de inspeção")
    if c.find(_NS + "f") is not None:
        raise ErroDocumentoConab("fórmula em planilha exige auditoria separada")
    kind = c.attrib.get("t", "n")
    item = c.find(_NS + "v")
    val = item.text if item is not None else None
    if kind == "s":
        try:
            idx = int(val)
            if idx < 0 or str(idx) != val:
                raise ValueError
            val = compartilhadas[idx]
        except (TypeError, ValueError, IndexError) as exc:
            raise ErroDocumentoConab("índice sharedStrings inválido") from exc
        kind = "texto_compartilhado"
    elif kind == "inlineStr":
        inline = c.find(_NS + "is")
        val = "".join(e.text or "" for e in inline.iter(_NS + "t")) if inline is not None else ""
        kind = "texto"
    elif kind == "n":
        kind = "numero" if val not in (None, "") else "vazio"
        if kind == "numero":
            val = _numero(val)
    elif kind == "b":
        if val not in ("0", "1"):
            raise ErroDocumentoConab("booleano OOXML inválido")
        kind = "booleano"
    elif kind in ("str",):
        kind = "texto"
    elif kind == "e":
        raise ErroDocumentoConab("erro de fórmula presente na planilha")
    else:
        raise ErroDocumentoConab("tipo de célula OOXML desconhecido")
    if val is not None and len(val) > 2500:
        raise ErroDocumentoConab("valor de célula excessivo")
    return {"referencia": r, "linha": row, "coluna": ncol, "tipo": kind, "valor": val}


def ler_amostra_celulas_conab(
    *, manifesto_vinculo: dict, xlsx_raw: bytes,
    max_abas: int = 8, max_linhas: int = 25, max_celulas: int = 200,
) -> dict:
    """Extrai amostra de layout, não uma tabela agronômica normalizada.

    A leitura falha fechada se houver fórmulas, células fora dos limites ou
    células repetidas nas áreas inspecionadas. Não calcula nem publica números.
    """
    if (type(max_abas) is not int or not 1 <= max_abas <= 8 or
            type(max_linhas) is not int or not 1 <= max_linhas <= 100 or
            type(max_celulas) is not int or not 1 <= max_celulas <= 500):
        raise ErroDocumentoConab("limites de inspeção inválidos")
    # Inspeção estrutural também revalida sha do arquivo e flags do manifesto.
    index = inspecionar_abas_ooxml_conab(
        manifesto_vinculo=manifesto_vinculo, xlsx_raw=xlsx_raw
    )
    with ZipFile(BytesIO(xlsx_raw)) as z:
        shared = _strings_compartilhadas(z)
        itens = []
        for aba in index["abas"][:max_abas]:
            xml = _xml_limitado(z, aba["parte_xml"], _MAX_BYTES_SHEET)
            if xml.tag != _NS + "worksheet":
                raise ErroDocumentoConab("XML não é worksheet")
            data = xml.find(_NS + "sheetData")
            rows = [] if data is None else list(data.findall(_NS + "row"))
            if len(rows) > _MAX_ROWS:
                raise ErroDocumentoConab("número de linhas excede janela suportada")
            valoracoes = []
            vistos = set()
            linhas_visitadas = set()
            total_celulas = 0
            for row in rows:
                r_id = row.attrib.get("r")
                if not r_id or not r_id.isascii() or not r_id.isdecimal():
                    raise ErroDocumentoConab("linha OOXML sem índice")
                numero = int(r_id)
                if numero < 1 or numero > _MAX_ROWS or numero in linhas_visitadas:
                    raise ErroDocumentoConab("linha OOXML repetida/fora dos limites")
                linhas_visitadas.add(numero)
                for cell in row.findall(_NS + "c"):
                    total_celulas += 1
                    if total_celulas > _MAX_CELLS:
                        raise ErroDocumentoConab("planilha excede limite de células")
                    datum = _celula(cell, shared)
                    if datum["linha"] != numero or datum["referencia"] in vistos:
                        raise ErroDocumentoConab("célula fora da linha ou repetida")
                    vistos.add(datum["referencia"])
                    if (numero <= max_linhas and
                            len(valoracoes) < max_celulas):
                        valoracoes.append(datum)
            itens.append({
                "nome_aba": aba["nome"], "parte_xml": aba["parte_xml"],
                "estado_aba": aba["estado"],
                "total_celulas_inspecionadas": total_celulas,
                "amostra_celulas": valoracoes,
            })
    return {
        "estado": "AMOSTRA_OOXML_SEM_TABELA_AGRICOLA_HOMOLOGADA",
        "fonte_id": "CONAB", "arquivo_raw_sha256": sha256(xlsx_raw).hexdigest(),
        "safra": index["safra"], "numero_levantamento": index["numero_levantamento"],
        "total_abas_documento": index["quantidade_abas"],
        "abas_amostradas": len(itens), "abas": itens,
        "celulas_xlsx_lidas": True,
        "estrutura_xml_amostrada": True,
        "tabela_agricola_normalizada": False,
        "edicao_historica_autenticada": False,
        "disponibilidade_asof_comprovada": False,
        "habilita_backtest": False, "habilita_treino": False,
        "habilita_publicacao": False,
    }
