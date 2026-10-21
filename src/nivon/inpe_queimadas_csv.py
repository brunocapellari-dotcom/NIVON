"""Adaptador offline CSV diário INPE/Programa Queimadas.

Cada linha é DETECÇÃO de foco por satélite, não incêndio individual, não ROI
administrativo IBAMA e não polígono de área queimada. Não acessa rede.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

BASE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/"
COLUNAS = {"satelite", "data_hora_gmt"}
UF = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


class ErroFocosINPE(ValueError):
    pass


def url_focos_diario(*, data: str) -> str:
    try:
        dia = date.fromisoformat(data)
    except (TypeError, ValueError) as exc:
        raise ErroFocosINPE("data deve ser AAAA-MM-DD") from exc
    if dia.isoformat() != data:
        raise ErroFocosINPE("data inválida")
    return BASE + "focos_diario_br_" + dia.strftime("%Y%m%d") + ".csv"


def _tempo(s: str) -> str:
    if not isinstance(s, str):
        raise ErroFocosINPE("coleta sem data")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroFocosINPE("coleta inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroFocosINPE("coleta sem timezone")
    return d.astimezone(timezone.utc).isoformat()


def _valor(row: dict, principal: str, alternativo: str | None = None):
    return (row.get(principal) if row.get(principal) not in (None, "") else
            row.get(alternativo) if alternativo else None)


def _geo(valor, *, limite, nome):
    try:
        numero = float(valor)
    except (ValueError, TypeError) as exc:
        raise ErroFocosINPE("coordenada ausente: " + nome) from exc
    if not math.isfinite(numero) or not -limite <= numero <= limite:
        raise ErroFocosINPE("coordenada fora do domínio: " + nome)
    return numero


def _float_opt(valor, *, nome, minimo, maximo):
    if valor in (None, "", "-999"):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ErroFocosINPE("valor numérico inválido: " + nome) from exc
    if not math.isfinite(numero) or not minimo <= numero <= maximo:
        raise ErroFocosINPE("valor fora da faixa: " + nome)
    return numero


def normalizar_focos_diarios(*, payload: bytes, data_arquivo: str,
                           coletado_em: str, max_registros: int = 150_000) -> dict:
    url = url_focos_diario(data=data_arquivo)
    coleta = _tempo(coletado_em)
    if type(max_registros) is not int or not 1 <= max_registros <= 150_000:
        raise ErroFocosINPE("limite de linhas inválido")
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 20_000_000:
        raise ErroFocosINPE("CSV vazio ou acima do limite")
    try:
        s = payload.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroFocosINPE("CSV precisa ser UTF-8") from exc
    primeira = s.partition("\n")[0]
    try:
        dialect = csv.Sniffer().sniff(primeira, delimiters=",;")
    except csv.Error as exc:
        raise ErroFocosINPE("delimitador CSV desconhecido") from exc
    leitor = csv.DictReader(io.StringIO(s), dialect=dialect)
    campos = leitor.fieldnames
    if not campos or len(campos) > 80 or len(campos) != len(set(campos)):
        raise ErroFocosINPE("cabeçalho ausente/duplicado")
    if not COLUNAS <= set(campos) or not ({"latitude", "lat"} & set(campos)) or not ({"longitude", "lon"} & set(campos)):
        raise ErroFocosINPE("campos básicos de satélite/posição/data ausentes")
    observacoes, ids = [], set()
    for linha in leitor:
        if len(observacoes) >= max_registros:
            raise ErroFocosINPE("arquivo supera o limite de registros")
        if None in linha or any(not isinstance(v, str) for v in linha.values()):
            raise ErroFocosINPE("linha CSV desalinhada")
        quando = linha["data_hora_gmt"]
        if not quando:
            raise ErroFocosINPE("data/hora GMT ausente")
        try:
            dt = datetime.fromisoformat(quando.replace(" ", "T").replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroFocosINPE("data/hora GMT inválida") from exc
        if dt.tzinfo is not None and dt.utcoffset() != timezone.utc.utcoffset(dt):
            raise ErroFocosINPE("campo GMT com fuso diferente de UTC")
        dia = dt.date()
        if dia.isoformat() != data_arquivo:
            raise ErroFocosINPE("foco fora da data do arquivo")
        data_utc = dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.astimezone(timezone.utc).isoformat()
        lat = _geo(_valor(linha, "latitude", "lat"), limite=90, nome="latitude")
        lon = _geo(_valor(linha, "longitude", "lon"), limite=180, nome="longitude")
        sat = linha["satelite"].strip()
        if not sat or len(sat) > 70:
            raise ErroFocosINPE("satélite não informado")
        raw_uf = _valor(linha, "estado")
        regiao = raw_uf.strip() if isinstance(raw_uf, str) else None
        # Estado pode vir como nome completo. Não forçar crosswalk IBGE incerto.
        if regiao and len(regiao) > 50:
            raise ErroFocosINPE("estado inválido")
        mun = _valor(linha, "municipio")
        foco_id = _valor(linha, "foco_id", "id")
        if foco_id is not None and (not isinstance(foco_id, str) or not 1 <= len(foco_id) <= 150):
            raise ErroFocosINPE("id do foco inválido")
        chave = foco_id or hashlib.sha256(f"{data_utc}|{lat}|{lon}|{sat}".encode()).hexdigest()
        if chave in ids:
            raise ErroFocosINPE("foco repetido dentro de um arquivo")
        ids.add(chave)
        observacoes.append({
            "foco_id_fonte_ou_hash": chave, "id_gerado_localmente": foco_id is None,
            "data_hora_deteccao_utc": data_utc, "data_referencia": dia.isoformat(),
            "competencia": dia.strftime("%Y-%m"),
            "satelite": sat, "latitude": lat, "longitude": lon,
            "estado_reportado": regiao,
            "municipio_reportado": mun.strip() if isinstance(mun, str) else None,
            "codigo_ibge": None,
            "bioma": _valor(linha, "bioma"),
            "risco_fogo_inpe": _float_opt(linha.get("risco_fogo"), nome="risco_fogo", minimo=0, maximo=1),
            "frp_mw": _float_opt(linha.get("frp"), nome="frp", minimo=0, maximo=100_000),
            "coleta": coleta, "publicacao": None,
            "natureza": "DETECCAO_SATELITE_INPE_NAO_INCENDIO_NEM_AREA_QUEIMADA",
        })
    return {"dataset_id": "INPE_QUEIMADAS_FOCOS_CSV", "fonte_id": "INPE_QUEIMADAS",
            "url": url, "data_arquivo": data_arquivo,
            "observacoes": observacoes, "quantidade": len(observacoes),
            "sha256_original": hashlib.sha256(payload).hexdigest(), "coleta": coleta,
            "arquivo_dia_possivelmente_parcial": True, "apto_publicacao_automatica": False,
            "estado": "CSV_PONTUAL_NAO_HOMOLOGADO"}
