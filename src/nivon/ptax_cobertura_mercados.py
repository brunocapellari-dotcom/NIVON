"""Cobertura PTAX por evidências RAW visíveis no corte — NÃO forecast.

Relê bytes e snapshots oficiais armazenados (não faz HTTP) e só
classifica fechamento quando tipoBoletim é explicitamente Fechamento.
Não atribui horário de publicação, não infere feriados, não chama
motor_tendencias com campo de publicação inventado. Sem publicação.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256
import sqlite3
from typing import Mapping

from .qualidade_mercados import _momento
from .ptax_odata_bruta_mercados import verificar_ptax_odata_bruta


class ErroCoberturaPTAX(ValueError):
    """Duplicidade conflitante ou corrupção de séries PTAX."""


MAX_CAPTURAS = 1000
MAX_BOLETINS = 10000


def diagnosticar_cobertura_ptax(
    db: sqlite3.Connection, *, corte: str, moeda: str = "USD",
    incluir_sinteticos: bool = False, max_dias: int = 90,
) -> dict:
    """Cobertura por data de referência usando apenas capturas até o corte.

    Cada data de fechamento explícito tem uma única identidade econômica.
    Se duas capturas discordam para o mesmo dia, o conjunto inteiro é
    bloqueado, mesmo quando o último valor coincide com o anterior.
    """
    if (not isinstance(db, sqlite3.Connection) or moeda not in {"USD", "EUR"}
            or type(incluir_sinteticos) is not bool
            or type(max_dias) is not int or not 1 <= max_dias <= 366):
        raise ErroCoberturaPTAX("parâmetros de cobertura inválidos")
    instante = _momento(corte, "corte")
    try:
        capturas = db.execute(
            "SELECT c.sha256,c.coletado_em,c.consulta_url,c.tipo,b.dados "
            "FROM nivon_ptax_raw_capturas c "
            "JOIN nivon_ptax_raw_blobs b ON b.sha256=c.sha256 "
            "JOIN nivon_snapshots s ON s.id=c.snapshot_id "
            "JOIN nivon_coletas v ON v.snapshot_id=s.id "
            "AND v.coletado_utc=c.coletado_em "
            "WHERE c.coletado_em<=? AND c.moeda=? "
            "AND s.dataset_id='BCB_PTAX' AND s.sha256=c.sha256 "
            "AND s.tipo=c.tipo "
            "AND s.schema_versao IN ('PTAX_ODATA_1','PTAX_ODATA_RAW_V1') "
            "AND ((c.tipo='SINTETICO' "
            "AND c.origem_execucao='TRANSPORTE_INJETADO_SINTETICO') "
            "OR (c.tipo='REAL_AUTORIZADO' "
            "AND s.evidencia_direitos IS NOT NULL "
            "AND c.origem_execucao='HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO')) "
            "AND (?=1 OR c.tipo='REAL_AUTORIZADO') "
            "ORDER BY c.coletado_em,c.id LIMIT 1001",
            (instante.isoformat(), moeda, int(incluir_sinteticos)),
        ).fetchall()
    except sqlite3.Error:
        return {"status": "SEM_BASE_RAW_PTAX", "publicavel": False}
    if len(capturas) > MAX_CAPTURAS:
        return {"status": "COBERTURA_EXCESSIVA", "publicavel": False}
    fechas: dict[str, dict] = {}
    sem_tipo = 0
    outros_boletins = 0
    total = 0
    limite_data = instante.date().toordinal() - max_dias + 1
    for digest, coletado, url, tipo, raw in capturas:
        if type(raw) is not bytes or sha256(raw).hexdigest() != digest:
            raise ErroCoberturaPTAX("snapshot RAW adulterado")
        try:
            r = verificar_ptax_odata_bruta(
                raw, consulta_url=url, moeda=moeda,
                coletado_em=coletado, as_of=instante.isoformat(),
                raw_sha256_esperado=digest,
            )
        except (TypeError, ValueError) as exc:
            raise ErroCoberturaPTAX("captura PTAX inválida") from exc
        for obs in r["boletins"]:
            total += 1
            if total > MAX_BOLETINS:
                return {"status": "OBSERVACOES_EXCESSIVAS", "publicavel": False}
            dia = date.fromisoformat(obs["data_referencia"])
            if dia.toordinal() < limite_data:
                continue
            if obs["tipo_boletim"] != "Fechamento":
                if obs["tipo_boletim"] is None:
                    sem_tipo += 1
                else:
                    outros_boletins += 1
                continue
            novo = (Decimal(obs["cotacao_compra_decimal"]),
                    Decimal(obs["cotacao_venda_decimal"]))
            existente = fechas.get(dia.isoformat())
            if existente is not None:
                if existente["_valores"] != novo:
                    return {
                        "status": "FECHAMENTOS_CONFLITANTES",
                        "dia": dia.isoformat(), "moeda": moeda,
                        "publicavel": False,
                        "apto_backtest_por_publicacao": False,
                    }
                existente["arquivos_raw_distintos"].add(digest)
                continue
            fechas[dia.isoformat()] = {
                "data_referencia": dia.isoformat(),
                "compra_decimal": obs["cotacao_compra_decimal"],
                "venda_decimal": obs["cotacao_venda_decimal"],
                "raw_sha256": digest,
                "ponteiro_json": obs["ponteiro_json"],
                "primeira_coleta_observada": coletado,
                "_valores": novo,
                "arquivos_raw_distintos": {digest},
            }
    rows = []
    for item in (fechas[k] for k in sorted(fechas)):
        rows.append({
            k: (len(v) if k == "arquivos_raw_distintos" else v)
            for k, v in item.items() if k != "_valores"
        })
    return {
        "status": ("COBERTURA_FECHAMENTO_RAW_SEM_PUBLICACAO"
                   if rows else "SEM_FECHAMENTO_EXPLICITO_NO_CORTE"),
        "moeda": moeda, "corte": instante.isoformat(),
        "janela_dias_civis": max_dias,
        "capturas_consultadas": len(capturas),
        "boletins_verificados": total,
        "boletins_sem_tipo": sem_tipo,
        "outros_boletins": outros_boletins,
        "fechamentos_comprovados_no_raw": len(rows),
        "dias_referencia": [x["data_referencia"] for x in rows],
        "serie": rows,
        "sessoes_sem_cobertura": None,
        "calendario_oficial_validado": False,
        "publicacao_oficial_comprovada": False,
        "pode_informar_motor_preditivo": False,
        "pode_alimentar_briefing": False,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
    }
