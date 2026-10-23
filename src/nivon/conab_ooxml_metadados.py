"""Inspeção OFFLINE das abas declaradas por um XLSX de levantamento CONAB.

Lê apenas metadados OOXML essenciais; não lê células, cálculos ou quantidades.
O manifesto de captura continua não autenticado como edição histórica. Executar
em worker isolado: limites por ZIP/XML não são um sandbox de processo.
"""
from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
from io import BytesIO
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .conab_anexo_xlsx_levantamento import ErroDocumentoConab, _estrutura_zip_xlsx

_NS_DOC = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_SHEET_REL = _NS_OFFICE_REL + "/worksheet"
_DOC_REL = _NS_OFFICE_REL + "/officeDocument"
_TYPE_WORKBOOK = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_XML = 2_000_000


def _xml(z: ZipFile, name: str, *, size_limit: int = _MAX_XML) -> ET.Element:
    try:
        info = z.getinfo(name)
        if info.file_size > size_limit:
            raise ErroDocumentoConab("XML OOXML excede tamanho permitido: " + name)
        # Bytes descomprimidos limitados pelo tamanho verificado no índice.
        raw = z.read(info)
    except (KeyError, BadZipFile, EOFError, OSError) as exc:
        raise ErroDocumentoConab("XML OOXML ausente/corrompido: " + name) from exc
    if len(raw) > size_limit or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ErroDocumentoConab("XML OOXML extenso ou com DTD/entidade")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ErroDocumentoConab("XML OOXML malformado: " + name) from exc


def _resolve_target(base_dir: str, target: str) -> str:
    if not isinstance(target, str) or not target or target.startswith("//"):
        raise ErroDocumentoConab("relationship OOXML sem destino interno")
    if "\\" in target or "?" in target or "#" in target or ":" in target:
        raise ErroDocumentoConab("relationship OOXML com URL ou destino ambíguo")
    if target.startswith("/"):
        path = target[1:]
    else:
        path = posixpath.join(base_dir, target)
    canon = posixpath.normpath(path)
    # OOXML permite caminhos internos relativos como ../drawings/drawing1.xml;
    # após a normalização, nunca podem ultrapassar a raiz do pacote ZIP.
    if (canon in ("", ".", "..") or canon.startswith("../") or
            canon.startswith("/") or "\x00" in canon):
        raise ErroDocumentoConab("relationship OOXML tenta sair do pacote")
    return canon


def _rels(arquivo: ZipFile, name: str, base: str) -> dict:
    root = _xml(arquivo, name)
    if root.tag != f"{{{_NS_PACKAGE_REL}}}Relationships":
        raise ErroDocumentoConab("raiz Relationships inválida")
    rels = {}
    entries = list(root)
    if len(entries) > 2000:
        raise ErroDocumentoConab("relationships excessivos")
    for child in entries:
        if child.tag != f"{{{_NS_PACKAGE_REL}}}Relationship":
            raise ErroDocumentoConab("item Relationship estranho")
        rel_id = child.attrib.get("Id")
        typ = child.attrib.get("Type")
        target = child.attrib.get("Target")
        if (not rel_id or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.-]{0,90}", rel_id)
                or rel_id in rels or not typ):
            raise ErroDocumentoConab("relationships com ID ou tipo inválido")
        if child.attrib.get("TargetMode", "Internal") != "Internal":
            raise ErroDocumentoConab("relationship externo não permitido")
        rels[rel_id] = (typ, _resolve_target(base, target))
    return rels


def _planilha_contida(rel: tuple[str, str], nomes: set[str]) -> str:
    typ, target = rel
    if typ != _SHEET_REL or not target.startswith("xl/worksheets/"):
        raise ErroDocumentoConab("aba OOXML não é worksheet interno")
    if not target.endswith(".xml") or target not in nomes:
        raise ErroDocumentoConab("arquivo de worksheet não existe no XLSX")
    return target


def inspecionar_abas_ooxml_conab(*, manifesto_vinculo: dict, xlsx_raw: bytes) -> dict:
    """Inventaria nome, estado e caminho das abas, sem publicar dado agrícola.

    SHA do binário é recomputado. Não revalida os HTMLs originais nem as
    condições HTTP; chamador precisa manter a prova RAW de aquisição íntegra.
    Nenhum campo pode certificar as-of, edição original ou células numéricas.
    """
    if (not isinstance(manifesto_vinculo, dict) or
            manifesto_vinculo.get("estado") !=
            "ANEXO_XLSX_VINCULADO_A_CAPTURA_SEM_PROVA_HISTORICA"):
        raise ErroDocumentoConab("manifesto do anexo ausente ou incompatível")
    expected = manifesto_vinculo.get("arquivo_raw_sha256")
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ErroDocumentoConab("hash do anexo ausente")
    if not isinstance(xlsx_raw, bytes):
        raise ErroDocumentoConab("bytes XLSX ausentes")
    digest = sha256(xlsx_raw).hexdigest()
    if not compare_digest(digest, expected):
        raise ErroDocumentoConab("XLSX não corresponde ao manifesto RAW")
    for gate in ("edicao_historica_autenticada", "disponibilidade_asof_comprovada",
                 "habilita_treino", "habilita_backtest", "habilita_publicacao",
                 "celulas_xlsx_lidas"):
        if manifesto_vinculo.get(gate) is not False:
            raise ErroDocumentoConab("manifesto manipulou gate: " + gate)
    if manifesto_vinculo.get("estrutura_xlsx_basica_verificada") is not True:
        raise ErroDocumentoConab("estrutura básica do XLSX não comprovada")
    qtd, bytes_total = _estrutura_zip_xlsx(xlsx_raw)
    if (manifesto_vinculo.get("zip_entradas") != qtd or
            manifesto_vinculo.get("zip_bytes_descomprimidos_declarados") != bytes_total):
        raise ErroDocumentoConab("metadados ZIP divergentes do manifesto")

    try:
        with ZipFile(BytesIO(xlsx_raw)) as z:
            nomes = set(z.namelist())
            if "xl/_rels/workbook.xml.rels" not in nomes:
                raise ErroDocumentoConab("workbook sem mapa de relationships")
            root_relationships = _rels(z, "_rels/.rels", "")
            if not any(rel == (_DOC_REL, "xl/workbook.xml")
                       for rel in root_relationships.values()):
                raise ErroDocumentoConab("arquivo não aponta para workbook principal")
            workbook_relationships = _rels(z, "xl/_rels/workbook.xml.rels", "xl")
            # Falha fechada em qualquer relationship externo, inclusive hyperlinks,
            # sem autorizar execução de links, fórmulas ou conexões.
            for name in nomes:
                if name.endswith(".rels") and name not in (
                        "_rels/.rels", "xl/_rels/workbook.xml.rels"):
                    directory = posixpath.dirname(name)
                    # Em OOXML, xxx/_rels/file.xml.rels referencia xxx/file.xml.
                    if "/_rels" in directory:
                        directory = directory.replace("/_rels", "")
                    _rels(z, name, directory)
            types = _xml(z, "[Content_Types].xml")
            if types.tag != f"{{{_NS_TYPES}}}Types":
                raise ErroDocumentoConab("content types OOXML inválidos")
            overrides = {}
            for elem in types:
                if elem.tag == f"{{{_NS_TYPES}}}Override":
                    part = elem.attrib.get("PartName")
                    if not part or part in overrides:
                        raise ErroDocumentoConab("Content_Types com parte duplicada")
                    overrides[part] = elem.attrib.get("ContentType")
            if overrides.get("/xl/workbook.xml") != _TYPE_WORKBOOK:
                raise ErroDocumentoConab("content type do workbook inválido")
            workbook = _xml(z, "xl/workbook.xml")
            if workbook.tag != f"{{{_NS_DOC}}}workbook":
                raise ErroDocumentoConab("raiz workbook OOXML inesperada")
            sheet_nodes = workbook.findall(f"./{{{_NS_DOC}}}sheets/{{{_NS_DOC}}}sheet")
            if not 1 <= len(sheet_nodes) <= 150:
                raise ErroDocumentoConab("quantidade de abas inválida")
            abas = []
            nomes_abas = set()
            ids_abas = set()
            for sheet in sheet_nodes:
                nome = sheet.attrib.get("name")
                sheet_id = sheet.attrib.get("sheetId")
                rid = sheet.attrib.get(f"{{{_NS_OFFICE_REL}}}id")
                estado = sheet.attrib.get("state", "visible")
                if (not isinstance(nome, str) or not 1 <= len(nome) <= 31
                        or nome.casefold() in nomes_abas or
                        not isinstance(sheet_id, str) or
                        not sheet_id.isascii() or not sheet_id.isdecimal()
                        or int(sheet_id) < 1 or sheet_id in ids_abas
                        or not rid or rid not in workbook_relationships
                        or estado not in ("visible", "hidden", "veryHidden")):
                    raise ErroDocumentoConab("identidade ou estado da aba inválido")
                target = _planilha_contida(workbook_relationships[rid], nomes)
                nomes_abas.add(nome.casefold())
                ids_abas.add(sheet_id)
                abas.append({"nome": nome, "sheet_id": int(sheet_id),
                             "estado": estado, "parte_xml": target})
    except (BadZipFile, EOFError, OSError) as exc:
        raise ErroDocumentoConab("XLSX corrompido durante inspeção OOXML") from exc

    return {
        "estado": "ABAS_OOXML_MAPEADAS_SEM_LEITURA_DE_CELULAS",
        "fonte_id": "CONAB",
        "safra": manifesto_vinculo.get("safra"),
        "numero_levantamento": manifesto_vinculo.get("numero_levantamento"),
        "arquivo_raw_sha256": digest,
        "quantidade_abas": len(abas), "abas": abas,
        "estrutura_ooxml_mapeada": True,
        "integridade_xml_planilhas_validada": False,
        "celulas_xlsx_lidas": False,
        "dados_agricolas_extraidos": False,
        "edicao_historica_autenticada": False,
        "disponibilidade_asof_comprovada": False,
        "habilita_backtest": False, "habilita_treino": False,
        "habilita_publicacao": False,
    }
