"""Inspeção de arquivos públicos autorizados sem coleta externa nem persistência.

Estágio de layout para CSV e ZIP/CSV de fontes sem custo contratual.
Não transforma contagem de linhas ou arquivo existente em série homologada.
"""
from __future__ import annotations
import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone

class ErroArquivoAberto(ValueError):
    pass

DATASETS_CSV = frozenset({
    "MAPA_ZARC", "MAPA_SISZARC", "MAPA_SIPEAGRO",
    "MAPA_SEGURO_RURAL", "ANTT_CIOT", "ANTT_RNTRC",
    "ANTT_DNIT_TRAFEGO", "ANP_DIESEL_PRECO", "ANP_MOVIMENTACAO",
    "MDIC_COMEX_NCM", "MDIC_COMEX_MUNICIPIO", "ANTAQ_MOVIMENTACAO",
    "USDA_ERS_CUSTOS", "FAOSTAT_CSV", "MAPA_SIAGRO_FERTILIZANTES",
})
LIMITE_BRUTO = 8_000_000
LIMITE_EXTRAIDO = 16_000_000
LIMITE_LINHAS = 100_000

def _extrair(raw, nome):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= LIMITE_BRUTO:
        raise ErroArquivoAberto("arquivo vazio ou tamanho bruto excessivo")
    if not isinstance(nome, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", nome):
        raise ErroArquivoAberto("nome de arquivo fora do formato seguro")
    if nome.lower().endswith(".csv"):
        return raw, "CSV"
    if not nome.lower().endswith(".zip") or not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ErroArquivoAberto("somente CSV ou ZIP com CSV")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            files = zf.infolist()
            if len(files) != 1:
                raise ErroArquivoAberto("ZIP deve ter exatamente um CSV")
            item = files[0]
            if (item.is_dir() or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}[.]csv", item.filename,
                   re.IGNORECASE) or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ErroArquivoAberto("ZIP inseguro ou contém arquivo não CSV")
            if (item.file_size > LIMITE_EXTRAIDO or item.file_size == 0
                    or item.compress_size == 0 or item.file_size > item.compress_size * 50):
                raise ErroArquivoAberto("arquivo compactado excessivo / ZIP bomb")
            extracted = zf.read(item)
            if len(extracted) != item.file_size:
                raise ErroArquivoAberto("tamanho extraído não confere")
            return extracted, "ZIP_CSV"
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ErroArquivoAberto("ZIP corrompido") from exc

def inspecionar_arquivo(dataset, *, nome, bytes_brutos, coletado_em, encoding="utf-8-sig"):
    if dataset not in DATASETS_CSV:
        raise ErroArquivoAberto("dataset fora da whitelist")
    if encoding not in ("utf-8-sig", "iso-8859-1"):
        raise ErroArquivoAberto("codificação não autorizada")
    try:
        dt = datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ErroArquivoAberto("coleta inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroArquivoAberto("coleta sem timezone")
    b, tipo = _extrair(bytes_brutos, nome)
    try:
        texto = b.decode(encoding)
    except UnicodeError as exc:
        raise ErroArquivoAberto("CSV não decodificável") from exc
    linhas = texto.splitlines()
    if not linhas or len(linhas) > LIMITE_LINHAS + 2:
        raise ErroArquivoAberto("CSV vazio ou acima do limite de amostra")
    sep = ";" if linhas[0].count(";") >= linhas[0].count(",") else ","
    reader = csv.reader(linhas, delimiter=sep, strict=True)
    try:
        header = next(reader)
        if not 1 <= len(header) <= 150 or any(not 1 <= len(x.strip()) <= 120 for x in header):
            raise ErroArquivoAberto("cabeçalho inválido")
        header = [x.strip() for x in header]
        if len(set(header)) != len(header):
            raise ErroArquivoAberto("colunas duplicadas")
        count = 0
        for row in reader:
            if len(row) != len(header) or any(len(v) > 20_000 for v in row):
                raise ErroArquivoAberto("linha desalinhada/excessiva")
            count += 1
            if count > LIMITE_LINHAS:
                raise ErroArquivoAberto("amostra excedeu limite")
    except csv.Error as exc:
        raise ErroArquivoAberto("CSV inválido") from exc
    return {"dataset_id": dataset, "tipo_arquivo": tipo,
            "linhas_amostra": count, "colunas": header,
            "sha256_original": hashlib.sha256(bytes_brutos).hexdigest(),
            "coleta": dt.astimezone(timezone.utc).isoformat(),
            "referencia": None, "publicacao": None, "competencia": None,
            "natureza": "ESTRUTURA_ARQUIVO_NAO_MEDICAO",
            "persistido": False, "homologado": False, "publicavel": False,
            "direitos_de_uso_verificados": False}
