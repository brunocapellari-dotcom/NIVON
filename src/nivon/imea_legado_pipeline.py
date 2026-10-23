"""Integração E2E local do workbook operacional IMEA herdado do AgroLog.

As cinco abas são tratadas como fonte especializada publicada. O destino local
é quarentena, NÃO o catálogo/mart canônico, até homologação de cada indicador.
Não há download, publicação, agendamento ou deploy por este módulo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .imea_operacional_xlsx import parse_workbook
from .ingestao_fontes_reais import gravar_lote

STAGING = "IMEA_WORKBOOK_LEGADO_STAGING"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ABAS = frozenset({
    "indicadores diarios", "indicadores semanais", "frete", "semeadura", "colheita",
})
OPS_REAIS = frozenset({"COLETA", "ARMAZENAMENTO", "USO_INTERNO"})
_UF = re.compile(r"^[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9 /()._-]{0,100}$")


class ErroIntegracaoImea(ValueError):
    pass


def _data(data_str: str | None, *, campo: str) -> str | None:
    if data_str is None:
        return None
    if not isinstance(data_str, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_str):
        raise ErroIntegracaoImea(f"{campo} deve ser YYYY-MM-DD ou null")
    try:
        return date.fromisoformat(data_str).isoformat()
    except ValueError as exc:
        raise ErroIntegracaoImea(f"{campo} não é data válida") from exc


def _coleta_utc(value: str) -> str:
    if not isinstance(value, str):
        raise ErroIntegracaoImea("data_coleta obrigatória")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroIntegracaoImea("data_coleta inválida") from exc
    if dt.utcoffset() is None:
        raise ErroIntegracaoImea("data_coleta deve ter timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _origem(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroIntegracaoImea("origem deve ser URL HTTPS")
    url = urlsplit(valor)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.port not in (None, 443) or url.fragment or len(valor) > 1600):
        raise ErroIntegracaoImea("URL de proveniência insegura ou inválida")
    if url.hostname.lower() not in {
        "www.imea.com.br", "imea.com.br", "drive.google.com", "docs.google.com",
    }:
        raise ErroIntegracaoImea("somente fonte IMEA ou workbook Drive identificado")
    return valor


def preparar_lote(payload: bytes, *, origem: str, coletado_em: str,
                  publicado_em: str | None = None) -> dict:
    """Normaliza localmente o workbook, sem persistir ou conceder direitos.

    Referência vem da célula da planilha. Publicação exige prova externa,
    não é estimada por data de coleta nem pelo histórico no Drive.
    """
    origem = _origem(origem)
    coletado_utc = _coleta_utc(coletado_em)
    publicado = _data(publicado_em, campo="publicado_em")
    if publicado and publicado > coletado_utc[:10]:
        raise ErroIntegracaoImea("publicação posterior à coleta")
    if not isinstance(payload, bytes) or not 0 < len(payload) <= 25_000_000:
        raise ErroIntegracaoImea("XLSX não informado ou grande demais")
    try:
        parsed = parse_workbook(payload)
    except (ValueError, KeyError, OverflowError, TypeError, IndexError) as exc:
        raise ErroIntegracaoImea(f"parser IMEA rejeitou workbook: {exc}") from exc
    registros = []
    vistos = set()
    resumo = Counter()
    for row in parsed["records"]:
        origem_aba = row["source_sheet"]
        if origem_aba not in ABAS:
            raise ErroIntegracaoImea("aba fora do contrato de migração")
        value = row["valor"]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ErroIntegracaoImea("valor não finito, negativo ou ausente")
        ref = _data(row["data_referencia"], campo="data_referencia")
        if ref is None:
            raise ErroIntegracaoImea("data_referencia ausente")
        if ref > coletado_utc[:10]:
            raise ErroIntegracaoImea("data_referencia futura para data_coleta")
        if not isinstance(row.get("record_id"), str) or not re.fullmatch(r"[a-f0-9]{64}", row["record_id"]):
            raise ErroIntegracaoImea("id de observação inválido")
        if row["record_id"] in vistos:
            raise ErroIntegracaoImea("colisão de observação")
        vistos.add(row["record_id"])
        # Não equivale ao preço de contrato realizado ou à viagem de frete.
        natureza = "ESTIMADO" if origem_aba in {"semeadura", "colheita"} else "INFORMADO"
        if origem_aba in {"semeadura", "colheita"}:
            destino = "IMEA_MT_SAFRA"
        elif origem_aba == "frete":
            destino = None  # dataset de frete não mapeado, não usar IMEA_FISICO
        else:
            destino = None  # pode conter CBOT/mercado/indicador não físico
        campos = {
            "fonte": "IMEA",
            "planilha": origem_aba,
            "produto": row["produto"],
            "metrica": row["metric_name"],
            "valor_canonico": value,  # necessario ao fingerprint de revisao as-of
            "local": row.get("local"),
            "origem_frete": row.get("origem"),
            "destino_frete": row.get("destino"),
            "safra": row.get("safra"),
            "regiao": row.get("regiao"),
            "unidade_origem": row.get("unidade_origem"),
            "unidade_canonica": row.get("unidade_canonica"),
            "natureza": natureza,
            "frete_negociado_comprovado": False if origem_aba == "frete" else None,
            "mapeamento_canonico_sugerido": destino,
            "publicacao_verificada": False,  # data recebida não é prova de publicação
            "data_disponibilidade": None,
            "snapshot_etapa": "QUARENTENA_SEM_HOMOLOGACAO",
            "id_registro_legado": row["record_id"],
        }
        registros.append({
            "identidade": row["record_id"], "referencia": ref,
            "competencia": ref[:7], "publicacao": publicado,
            "natureza": natureza, "unidade": row.get("unidade_canonica"),
            "valor": value, "campos": campos,
        })
        resumo[origem_aba] += 1
    if set(resumo) != ABAS:
        raise ErroIntegracaoImea("todas as cinco abas precisam conter observações")
    return {
        "dataset_id": STAGING, "raw": payload, "origem": origem,
        "tipo": MIME_XLSX, "coletado_em": coletado_utc,
        "registros": registros, "estado": "QUARANTINED",
        "contagem_abas": dict(sorted(resumo.items())),
        "metadados": {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "primeira_referencia": parsed["qa"]["first_date"],
            "ultima_referencia": parsed["qa"]["last_date"],
            "data_publicacao_informada": publicado,
            "data_disponibilidade_verificada": False,
            "coleta_remota_realizada": False,
            "direitos_de_redistribuicao": False,
        },
    }


def persistir_lote_local(lote: dict, *, banco: str | Path,
                         pasta_raw: str | Path, tipo: str = "SINTETICO",
                         autorizacoes: frozenset[str] = frozenset(),
                         evidencia: str | None = None) -> dict:
    """Recebe lote previamente validado. Somente staging/quarentena local."""
    if tipo not in {"SINTETICO", "REAL_AUTORIZADO"}:
        raise ErroIntegracaoImea("tipo de lote não permitido")
    if tipo == "REAL_AUTORIZADO":
        if not OPS_REAIS <= set(autorizacoes) or not isinstance(evidencia, str) or len(evidencia.strip()) < 10:
            raise PermissionError("IMEA real exige COLETA, ARMAZENAMENTO, USO_INTERNO e evidência")
    if lote.get("dataset_id") != STAGING or lote.get("estado") != "QUARANTINED":
        raise ErroIntegracaoImea("lote somente pode ser gravado em quarentena IMEA")
    resultado = gravar_lote(banco=banco, diretorio_bruto=pasta_raw,
                           dataset_id=STAGING, origem=lote["origem"],
                           raw=lote["raw"], tipo=MIME_XLSX,
                           coletado_em=lote["coletado_em"], registros=lote["registros"],
                           estado="QUARANTINED")
    return {
        "status": "QUARENTENA_LOCAL",
        "tipo_lote": tipo,
        "persistencia_google_cloud": False,
        "publicacao_automatica": False,
        "producao_homologada": False,
        "observacoes_por_aba": lote["contagem_abas"],
        "qa": lote["metadados"],
        "lote": resultado,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="IMEA legado: validar XLSX e opcionalmente persistir em quarentena")
    p.add_argument("xlsx", type=Path)
    p.add_argument("--origem", required=True)
    p.add_argument("--coletado-em", required=True)
    p.add_argument("--publicado-em")
    p.add_argument("--banco", type=Path)
    p.add_argument("--raw-dir", type=Path)
    p.add_argument("--sintetico", action="store_true",
                   help="somente fixture sintética; nunca rotular dados IMEA reais como sintéticos")
    args = p.parse_args(argv)
    try:
        if args.xlsx.is_symlink() or args.xlsx.suffix.lower() != ".xlsx" or not args.xlsx.is_file():
            raise ErroIntegracaoImea("arquivo XLSX local regular obrigatório")
        lote = preparar_lote(args.xlsx.read_bytes(), origem=args.origem,
                             coletado_em=args.coletado_em, publicado_em=args.publicado_em)
        if args.banco or args.raw_dir:
            if not args.banco or not args.raw_dir:
                raise ErroIntegracaoImea("banco e raw-dir obrigatórios juntos")
            if not args.sintetico:
                raise PermissionError("CLI não persiste workbook real sem gate de autorização em código")
            result = persistir_lote_local(lote, banco=args.banco, pasta_raw=args.raw_dir)
        else:
            result = {"status": "VALIDADO_SEM_PERSISTIR", "qa": lote["metadados"],
                      "observacoes": len(lote["registros"]), "abas": lote["contagem_abas"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, PermissionError) as exc:
        print(json.dumps({"status": "BLOQUEADO", "motivo": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
