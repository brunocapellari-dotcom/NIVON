"""Adaptador offline BCB PTAX histórico -> indicador CAMBIO do briefing.

Não coleta, não acessa internet e não converte hora da cotação em data de
publicação. Respeita a classe REAL_AUTORIZADO e direitos de publicação derivada.
PTAX é cotação informada pelo BCB, não dólar comercial nem negócio executado.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from math import isfinite

from .indicadores_historicos import _direitos, _instante


class ErroIndicadorPTAX(ValueError):
    pass


def indicador_ptax_sqlite(db: sqlite3.Connection, *, gerado_em: str,
                          fontes: dict, moeda: str = "USD",
                          idade_maxima_horas: int = 168) -> dict:
    """Seleciona último boletim realmente coletado antes do corte.

    A consulta somente lê tabelas construídas no pipeline_api_dados; nunca
    cria schemas, abre rede, habilita licenças nem aceita tipo SINTETICO.
    """
    agora = _instante(gerado_em)
    if moeda not in ("USD", "EUR"):
        raise ErroIndicadorPTAX("moeda não homologada")
    if type(idade_maxima_horas) is not int or not 1 <= idade_maxima_horas <= 336:
        raise ErroIndicadorPTAX("idade limite inválida")
    if not _direitos(fontes, "BCB_PTAX"):
        return {
            "status": "BLOQUEADO_DIREITOS",
            "motivo": "PTAX sem direitos comprovados de leitura e publicação derivada",
        }
    try:
        dados = db.execute("""
           SELECT o.observacao_json, s.sha256, c.coletado_utc
           FROM nivon_observacoes_api o
           JOIN nivon_snapshots s ON s.id=o.snapshot_id
           JOIN nivon_coletas c ON c.snapshot_id=s.id
           WHERE s.dataset_id='BCB_PTAX'
             AND s.tipo='REAL_AUTORIZADO'
             AND c.coletado_utc<=?
           ORDER BY c.coletado_utc DESC, s.sha256 DESC
           LIMIT 10001
        """, (agora.isoformat(),)).fetchall()
    except sqlite3.Error:
        return {"status": "BANCO_INDISPONIVEL", "motivo": "histórico PTAX indisponível"}
    if len(dados) > 10000:
        return {"status": "HISTORICO_EXCESSIVO", "motivo": "exige janela/indexação temporal"}
    candidatos = []
    for registro in dados:
        try:
            obs = json.loads(registro[0])
            if not isinstance(obs, dict) or obs.get("moeda") != moeda:
                continue
            ref = _instante(obs["referencia_data_hora_utc"])
            coletado = _instante(registro[2])
            if ref > agora or coletado > agora or ref > coletado:
                raise ErroIndicadorPTAX("cotação posterior à coleta ou corte")
            compra = obs["cotacao_compra_brl_por_moeda"]
            venda = obs["cotacao_venda_brl_por_moeda"]
            if any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                   for v in (compra, venda)) or compra > venda:
                raise ErroIndicadorPTAX("taxas inválidas")
            classe = obs.get("tipo_boletim")
            if classe is not None and (not isinstance(classe, str) or len(classe) > 80):
                raise ErroIndicadorPTAX("tipo de boletim inválido")
            candidatos.append((ref, coletado, str(registro[1]),
                               float(compra), float(venda), classe))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            if isinstance(exc, ErroIndicadorPTAX):
                raise
            raise ErroIndicadorPTAX("vintage PTAX real com observação inválida") from exc
    if not candidatos:
        return {"status": "SEM_OBSERVACAO_REAL", "motivo": "nenhuma PTAX real autorizada até o corte"}
    # Não substituir 'Fechamento' por Intermediário quando ambos coexistem.
    fechamentos = [x for x in candidatos if isinstance(x[5], str)
                    and x[5].strip().casefold() == "fechamento"]
    comparaveis = fechamentos if fechamentos else candidatos
    last_ref = max(x[0] for x in comparaveis)
    same_ref = [x for x in comparaveis if x[0] == last_ref]
    # Uma revisão verdadeira é possível, mas as taxas divergentes no mesmo
    # horário só são aceitáveis com contrato de revisão auditada.
    taxas = {(x[3], x[4], x[5]) for x in same_ref}
    if len(taxas) != 1:
        return {
            "status": "VINTAGES_CONFLITANTES",
            "motivo": "mesmo horário de referência com múltiplas versões incompatíveis",
        }
    selecao = max(same_ref, key=lambda x: (x[1], x[2]))
    ref, coleta, sha, compra, venda, classe = selecao
    if agora - ref > timedelta(hours=idade_maxima_horas):
        return {"status": "DADO_VENCIDO", "motivo": "boletim PTAX fora da janela"}
    label = "Fechamento" if fechamentos else (
        "Boletim " + classe.strip() if isinstance(classe, str) else "Boletim sem tipo informado"
    )
    status = "FECHAMENTO" if fechamentos else "OUTRO_BOLETIM"
    titulo = f"PTAX {moeda}/BRL — {label}"
    return {
        "status": "INDICADOR_VERIFICADO_TEMPO",
        "indicador": {
            "fonte_id": "BCB_PTAX",
            "secao": "CAMBIO",
            "titulo": titulo,
            "valor": (f"compra R$ {compra:.4f}; venda R$ {venda:.4f}").replace(".", ","),
            "referencia": ref.isoformat(),
            "fonte": "BCB PTAX; taxas informadas, não dólar comercial",
        },
        "evidencia": {
            "dataset_id": "BCB_PTAX",
            "sha256_original": sha,
            "coleta": coleta.isoformat(),
            "data_hora_cotacao": ref.isoformat(),
            "publicacao": None,
            "tipo_boletim": classe,
            "tipo_selecionado": status,
            "classe": "REAL_AUTORIZADO",
            "apto_backtest_por_publicacao": False,
            "natureza": "PTAX_INFORMADA_NAO_DOLAR_COMERCIAL",
        },
    }
