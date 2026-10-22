"""Importador OFFLINE CEPEA/IMEA para armazenamento em quarentena.

Não é API de qualquer das fontes; CSV é contrato de intercâmbio do NIVON,
fornecido mediante autorização. Não faz scraping, coleta automática, publicação
ou promoção temporal para backtest.
"""
from __future__ import annotations
import csv
import hashlib
import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

class ErroImportacaoCotacoes(ValueError):
    pass

_ORIGENS = {
    "CEPEA": ("CEPEA_COTACOES_MANUAIS", {"cepea.esalq.usp.br", "www.cepea.esalq.usp.br"}),
    "IMEA": ("IMEA_COTACOES_MANUAIS", {"imea.com.br", "www.imea.com.br"}),
}
_CAMPOS = ("serie_id", "produto", "localidade", "competencia", "referencia", "preco", "unidade")
_UNIDADES = {"BRL/SC60KG", "BRL/ARROBA", "BRL/L", "BRL/T", "USD/SC60KG"}
_ID = re.compile(r"[A-Z][A-Z0-9_]{1,90}\Z")
_COMP = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])\Z")
_PRECO = re.compile(r"(?:0|[1-9][0-9]{0,10})(?:[,.][0-9]{1,4})?\Z")
_MAX_BYTES, _MAX_ROWS = 1_000_000, 3000
_ESTADO = "QUARENTENA_ORIGEM_E_DIREITOS_NAO_COMPROVADOS_EXTERNAMENTE"

def _utc(valor, campo):
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErroImportacaoCotacoes(campo + " exige texto ISO com fuso")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroImportacaoCotacoes(campo + " invalido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroImportacaoCotacoes(campo + " sem fuso")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

def _texto(valor, campo):
    if not isinstance(valor, str):
        raise ErroImportacaoCotacoes(campo + " ausente")
    v = valor.strip()
    if (not 1 <= len(v) <= 120 or v[0] in "=+-@" or
            any(ord(c) < 32 for c in v)):
        raise ErroImportacaoCotacoes(campo + " malformado")
    return v

def normalizar_arquivo_cotacoes(*, bruto: bytes, fonte_id: str, fonte_url: str,
                               edicao_id: str, coletado_em: str,
                               publicado_em: str | None = None,
                               disponivel_em: str | None = None) -> dict:
    if fonte_id not in _ORIGENS:
        raise ErroImportacaoCotacoes("fonte nao prevista")
    dataset_id, hosts = _ORIGENS[fonte_id]
    url = urlsplit(fonte_url if isinstance(fonte_url, str) else "")
    if (url.scheme != "https" or url.hostname not in hosts or url.username
            or url.password or url.fragment or url.port not in (None, 443)):
        raise ErroImportacaoCotacoes("origem HTTPS oficial invalida")
    edicao = _texto(edicao_id, "edicao")
    coleta = _utc(coletado_em, "coletado_em")
    publicacao, disponibilidade = _utc(publicado_em, "publicado_em"), _utc(disponivel_em, "disponivel_em")
    if (publicacao is None) != (disponibilidade is None):
        raise ErroImportacaoCotacoes("publicacao/disponibilidade incompletas")
    if publicacao and not publicacao <= disponibilidade <= coleta:
        raise ErroImportacaoCotacoes("cronologia impossivel")
    if not isinstance(bruto, bytes) or not 0 < len(bruto) <= _MAX_BYTES or b"\x00" in bruto:
        raise ErroImportacaoCotacoes("CSV ausente ou excessivo")
    try:
        leitor = csv.DictReader(io.StringIO(bruto.decode("utf-8-sig"), newline=""),
                               delimiter=";", strict=True)
        if leitor.fieldnames is None or tuple(leitor.fieldnames) != _CAMPOS:
            raise ErroImportacaoCotacoes("cabecalho divergente")
        linhas = list(leitor)
    except (UnicodeError, csv.Error) as exc:
        raise ErroImportacaoCotacoes("CSV malformado") from exc
    if not 1 <= len(linhas) <= _MAX_ROWS:
        raise ErroImportacaoCotacoes("linhas fora do limite")
    sha = hashlib.sha256(bruto).hexdigest()
    registros, metadados, vistos = [], [], set()
    for linha in linhas:
        if None in linha or any(v is None for v in linha.values()):
            raise ErroImportacaoCotacoes("coluna ausente ou adicional")
        serie = linha["serie_id"]
        if not _ID.fullmatch(serie):
            raise ErroImportacaoCotacoes("serie_id nao canonico")
        produto, localidade = _texto(linha["produto"], "produto"), _texto(linha["localidade"], "localidade")
        competencia = linha["competencia"]
        if not _COMP.fullmatch(competencia):
            raise ErroImportacaoCotacoes("competencia invalida")
        try:
            referencia = date.fromisoformat(linha["referencia"]).isoformat()
        except (ValueError, TypeError) as exc:
            raise ErroImportacaoCotacoes("data referencia invalida") from exc
        if referencia[:7] != competencia or referencia > coleta[:10]:
            raise ErroImportacaoCotacoes("referencia/competencia divergem")
        if publicacao and referencia > publicacao[:10]:
            raise ErroImportacaoCotacoes("referencia apos publicacao")
        preco = linha["preco"]
        if not _PRECO.fullmatch(preco):
            raise ErroImportacaoCotacoes("numero ambiguo ou separador de milhar")
        try:
            valor = Decimal(preco.replace(",", "."))
        except InvalidOperation as exc:
            raise ErroImportacaoCotacoes("preco invalido") from exc
        if not valor.is_finite() or not 0 < valor < Decimal("10000000000"):
            raise ErroImportacaoCotacoes("preco fora do dominio")
        if linha["unidade"] not in _UNIDADES:
            raise ErroImportacaoCotacoes("unidade desconhecida, conversao proibida")
        chave = (serie, competencia)
        if chave in vistos:
            raise ErroImportacaoCotacoes("serie e competencia duplicadas")
        vistos.add(chave)
        registros.append({
            "source_id": fonte_id, "dataset_id": dataset_id,
            "serie_id": serie, "competencia": competencia, "referencia": referencia,
            "edicao_id": edicao, "unidade": linha["unidade"], "valor": str(valor),
            "classe_evidencia": "INFORMADO", "publicado_em": publicacao,
            "disponivel_em": disponibilidade, "coletado_em": coleta,
            "fonte_url": fonte_url, "raw_sha256": sha,
            "disponibilidade_verificada": False, "prova_disponibilidade_sha256": None,
        })
        metadados.append({"serie_id": serie, "produto": produto, "localidade": localidade})
    return {
        "fonte_id": fonte_id, "dataset_id": dataset_id, "edicao_id": edicao,
        "sha256": sha, "bytes": len(bruto), "linhas": len(registros),
        "registros": registros, "metadados_linhas": metadados, "estado": _ESTADO,
        "api_confirmada": False, "coleta_automatica": False,
        "autorizado_publicar": False, "autorizado_backtest": False,
    }

def persistir_quarentena(armazem, pacote: dict, *, operador_autorizou_importacao: bool = False) -> dict:
    """Reutiliza o storage versionado. Replay idempotente; lote nao atomico."""
    if operador_autorizou_importacao is not True:
        raise PermissionError("importacao supervisionada requer opt-in")
    if not isinstance(pacote, dict) or pacote.get("estado") != _ESTADO:
        raise ErroImportacaoCotacoes("pacote fora de quarentena")
    registros = pacote.get("registros")
    if not isinstance(registros, list) or not 1 <= len(registros) <= _MAX_ROWS or len(registros) != pacote.get("linhas"):
        raise ErroImportacaoCotacoes("numero de linhas inconsistente")
    from .historico_vintages import normalizar_edicao
    for row in registros:
        if (not isinstance(row, dict) or row.get("source_id") != pacote.get("fonte_id")
                or row.get("dataset_id") != pacote.get("dataset_id")
                or row.get("raw_sha256") != pacote.get("sha256")
                or row.get("disponibilidade_verificada") is not False):
            raise ErroImportacaoCotacoes("registro de quarentena adulterado")
        normalizar_edicao(row)
    estados = [armazem.gravar(row) for row in registros]
    return {"dataset_id": pacote["dataset_id"], "linhas": len(estados),
            "novas": estados.count("EDICAO_PERSISTIDA_LOCALMENTE"),
            "duplicadas": estados.count("DUPLICATA_IDEMPOTENTE"),
            "estado": "QUARENTENA_LOCAL_SEM_PUBLICACAO"}
