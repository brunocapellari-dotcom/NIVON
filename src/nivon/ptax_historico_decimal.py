"""Histórico PTAX Decimal a partir de RAW versionado no SQLite do NIVON.

Consulta todas as capturas visíveis no corte, reconfere bytes e resolve
identidades de boletim sem fazer inferência sobre publicação histórica.
Não altera as tabelas/consumidores legados com float e não acessa rede.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import sqlite3

from .ptax_odata_bruta_mercados import verificar_ptax_odata_bruta
from .qualidade_mercados import _momento


class ErroHistoricoPTAX(ValueError):
    """Falha em dados históricos, vintage, integridade ou seleção temporal."""


MAX_CAPTURAS = 10000
MAX_BOLETINS = 100000


def _decimal(txt: object, nome: str) -> Decimal:
    if not isinstance(txt, str):
        raise ErroHistoricoPTAX(f"{nome} não preservado em texto Decimal")
    try:
        valor = Decimal(txt)
    except InvalidOperation as exc:
        raise ErroHistoricoPTAX(f"{nome} inválido") from exc
    if not valor.is_finite() or valor <= 0 or len(valor.as_tuple().digits) > 16:
        raise ErroHistoricoPTAX(f"{nome} inválido")
    return valor


def selecionar_ptax_decimal_asof(
    db: sqlite3.Connection, *, corte: str, moeda: str = "USD",
    incluir_sinteticos: bool = False, somente_fechamento: bool = False,
    idade_maxima_horas: int = 168,
) -> dict:
    """Seleciona o último boletim visível com cada RAW conferido.

    Se existe conflito de taxas para mesma identidade temporal, bloqueia
    em vez de inventar revisão. Consulta TODAS as capturas no intervalo
    as-of, não apenas a última página/último snapshot.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroHistoricoPTAX("conexão SQLite obrigatória")
    if moeda not in ("USD", "EUR") or type(incluir_sinteticos) is not bool or (
        type(somente_fechamento) is not bool
    ) or type(idade_maxima_horas) is not int or not 1 <= idade_maxima_horas <= 336:
        raise ErroHistoricoPTAX("parâmetros de consulta inválidos")
    corte_dt = _momento(corte, "corte")
    # Leitura nunca cria tabela (inclusive quando o banco está vazio).
    try:
        rows = db.execute(
            "SELECT c.sha256, c.coletado_em, c.consulta_url, c.tipo, b.dados "
            "FROM nivon_ptax_raw_capturas c "
            "JOIN nivon_ptax_raw_blobs b ON b.sha256=c.sha256 "
            "JOIN nivon_snapshots s ON s.id=c.snapshot_id "
            "WHERE c.coletado_em<=? AND c.moeda=? "
            "AND s.dataset_id='BCB_PTAX' AND s.sha256=c.sha256 "
            "AND s.tipo=c.tipo AND (?=1 OR c.tipo='REAL_AUTORIZADO') "
            "ORDER BY c.coletado_em ASC, c.id ASC LIMIT 10001",
            (corte_dt.isoformat(), moeda, int(incluir_sinteticos)),
        ).fetchall()
    except sqlite3.Error:
        return {"status": "RAW_PTAX_INDISPONIVEL", "publicavel": False}
    if len(rows) > MAX_CAPTURAS:
        return {"status": "JANELA_RAW_PTAX_EXCESSIVA", "publicavel": False}
    if not rows:
        return {"status": "SEM_RAW_PTAX_ATE_CORTE", "publicavel": False}

    boletins = {}
    lidos = 0
    for digest, coleta, url, tipo, raw in rows:
        if type(raw) is not bytes or sha256(raw).hexdigest() != digest:
            raise ErroHistoricoPTAX("bytes originais divergentes do ledger")
        try:
            resultado = verificar_ptax_odata_bruta(
                raw, consulta_url=url, moeda=moeda, coletado_em=coleta,
                as_of=corte_dt.isoformat(), raw_sha256_esperado=digest,
            )
        except (TypeError, ValueError) as exc:
            raise ErroHistoricoPTAX("vintage RAW PTAX inválido") from exc
        for obs in resultado["boletins"]:
            lidos += 1
            if lidos > MAX_BOLETINS:
                return {"status": "AMOSTRA_PTAX_EXCESSIVA", "publicavel": False}
            chave = (obs["referencia_em"], obs["tipo_boletim"])
            valores = (
                _decimal(obs["cotacao_compra_decimal"], "compra"),
                _decimal(obs["cotacao_venda_decimal"], "venda"),
                obs["paridades"],
            )
            atual = boletins.get(chave)
            if atual is not None and atual["valores"] != valores:
                return {
                    "status": "VINTAGES_CONFLITANTES",
                    "motivo": "mesma referência/tipo PTAX com valores diferentes em capturas",
                    "publicavel": False,
                    "apto_backtest_por_publicacao": False,
                }
            # A ocorrência mais antiga prova a primeira coleta local
            # conhecida; recapturas idênticas nunca a reescrevem.
            if atual is None:
                boletins[chave] = {
                    "obs": obs, "valores": valores,
                    "primeira_coleta": coleta, "sha": digest,
                    "tipo_origem": tipo,
                }
    candidatos = list(boletins.values())
    fechamentos = [v for v in candidatos
                   if v["obs"]["tipo_boletim"] == "Fechamento"]
    if somente_fechamento and not fechamentos:
        return {
            "status": "SEM_FECHAMENTO_EXPLICITO",
            "quantidade_boletins": len(candidatos), "publicavel": False,
        }
    elegiveis = fechamentos if fechamentos else candidatos
    # Fechamento explícito domina outras categorias; sem tipo explícito
    # não se presume fechamento. A referência é temporal, não a coleta.
    selecao = max(elegiveis, key=lambda r: (
        _momento(r["obs"]["referencia_em"], "referencia_em"),
        _momento(r["primeira_coleta"], "coleta"), r["sha"],
    ))
    obs = selecao["obs"]
    ref = _momento(obs["referencia_em"], "referencia_em")
    if corte_dt - ref > timedelta(hours=idade_maxima_horas):
        return {
            "status": "DADO_PTAX_VENCIDO", "ultima_referencia": ref.isoformat(),
            "publicavel": False,
        }
    valor_compra, valor_venda, _ = selecao["valores"]
    status = ("FECHAMENTO" if obs["tipo_boletim"] == "Fechamento"
              else "BOLETIM_SEM_FECHAMENTO_COMPROVADO")
    return {
        "status": "PTAX_DECIMAL_ASOF_CONFERIDA_OFFLINE",
        "serie_id": f"BCB_PTAX:{moeda}:BRL:{status}",
        "moeda": moeda, "tipo_boletim": obs["tipo_boletim"],
        "tipo_selecionado": status,
        "compra_decimal": obs["cotacao_compra_decimal"],
        "venda_decimal": obs["cotacao_venda_decimal"],
        "compra_dec4": str(valor_compra.quantize(Decimal("0.0001"))),
        "venda_dec4": str(valor_venda.quantize(Decimal("0.0001"))),
        "referencia_em": ref.isoformat(),
        "primeira_coleta_conhecida": selecao["primeira_coleta"],
        "raw_sha256": selecao["sha"], "ponteiro_json": obs["ponteiro_json"],
        "origem_tipo": selecao["tipo_origem"],
        "total_capturas": len(rows),
        "total_boletins_unicos": len(candidatos),
        "referencia_temporal": "COLETA_OBSERVADA_LOCAL_NAO_PUBLICACAO_BCB",
        "publicacao_oficial_comprovada": False,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
        "probabilidades_calibradas": None,
    }


def indicador_ptax_decimal_raw(
    db: sqlite3.Connection, *, gerado_em: str, fontes: dict,
    moeda: str = "USD", idade_maxima_horas: int = 168,
) -> dict:
    """Prévia isolada que só consome RAW real com direitos de leitura+derivada.

    O adaptador legado indicador_ptax_sqlite continua inalterado.
    """
    from .indicadores_historicos import _direitos

    if not isinstance(fontes, dict) or not _direitos(fontes, "BCB_PTAX"):
        return {"status": "BLOQUEADO_DIREITOS", "publicavel": False}
    r = selecionar_ptax_decimal_asof(
        db, corte=gerado_em, moeda=moeda,
        incluir_sinteticos=False, idade_maxima_horas=idade_maxima_horas,
    )
    if r["status"] != "PTAX_DECIMAL_ASOF_CONFERIDA_OFFLINE":
        return r
    classe = (r["tipo_boletim"] if r["tipo_boletim"] is not None
              else "sem tipo informado")
    return {
        "status": "INDICADOR_RAW_PTAX_PREVIA_NAO_HOMOLOGADA",
        "indicador": {
            "fonte_id": "BCB_PTAX", "secao": "CAMBIO",
            "titulo": f"PTAX {moeda}/BRL — {classe}",
            "valor": (f"compra R$ {r['compra_dec4']}; "
                      f"venda R$ {r['venda_dec4']}").replace(".", ","),
            "referencia": r["referencia_em"],
            "fonte": "BCB PTAX; cotação informada, não dólar comercial",
        },
        "evidencia": {
            "dataset_id": "BCB_PTAX", "sha256_original": r["raw_sha256"],
            "ponteiro_json": r["ponteiro_json"],
            "primeira_coleta": r["primeira_coleta_conhecida"],
            "publicacao": None, "tipo_boletim": r["tipo_boletim"],
            "classe": r["origem_tipo"],
            "apto_backtest_por_publicacao": False,
            "natureza": "PTAX_INFORMADA_NAO_DOLAR_COMERCIAL",
        },
        "publicavel": False, "probabilidades_calibradas": None,
    }
