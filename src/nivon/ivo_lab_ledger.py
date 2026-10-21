"""Ponte experimental IVO: resultados do laboratório -> ledger SQLite.

Opera apenas com fixtures sintéticas e autorização explícita. Nunca registra
backtests como LIVE, não coleta nem publica valores reais ou modelos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from .ivo_previsao_ledger import (
    ErroLedger, LedgerPrevisoes, ObservacaoPublicada, PrevisaoRegistrada
)


def _identidade(partes: tuple[str, ...]) -> str:
    return sha256("|".join(partes).encode("utf-8")).hexdigest()


def arquivar_replay_sintetico(relatorio: dict, *, ledger: LedgerPrevisoes,
                              autorizado: bool = False, fixture_sintetica_confirmada: bool = False,
                              versao: str = "LAB_V1") -> dict:
    if autorizado is not True or fixture_sintetica_confirmada is not True:
        raise PermissionError("replay exige autorização e confirmação explícita de dados sintéticos")
    if not isinstance(ledger, LedgerPrevisoes) or not isinstance(relatorio, dict):
        raise ErroLedger("ledger ou relatório inválido")
    if relatorio.get("estado") != "BACKTEST_OFFLINE_NAO_HOMOLOGADO" or relatorio.get("promocao_automatica") is not False:
        raise ErroLedger("somente replay sem homologação é aceito")
    if not isinstance(versao, str) or not versao or len(versao) > 40:
        raise ErroLedger("versão do laboratório inválida")
    campos = ("fonte", "variavel", "produto", "regiao", "unidade")
    if any(not isinstance(relatorio.get(k), str) or not relatorio[k] for k in campos):
        raise ErroLedger("eixos canônicos ausentes")
    folds = relatorio.get("folds")
    if not isinstance(folds, list) or not folds or len(folds) > 121:
        raise ErroLedger("folds ausentes ou excessivos")
    previstos, verdades = [], []
    ids = set()
    for f in folds:
        if not isinstance(f, dict):
            raise ErroLedger("fold inválido")
        periodo = f["periodo"]
        if periodo in ids:
            raise ErroLedger("competência duplicada")
        ids.add(periodo)
        versao_id = "IVO_BLENDED_SEASONAL_" + relatorio["produto"]
        src = relatorio["fonte"]
        eixo = (versao_id, versao, src, relatorio["variavel"],
                relatorio["produto"], relatorio["regiao"], relatorio["unidade"], periodo)
        issue = datetime.fromisoformat(f["emitida_em"])
        # Evidência de features deve ter sido coletada até o instante da previsão.
        coleta = datetime.fromisoformat(f["ultima_coleta_de_features"])
        pub = datetime.fromisoformat(f["observacao_publicada_em"]+"T00:00:00+00:00")
        obs_coleta = datetime.fromisoformat(f["observacao_coletada_em"])
        codigo_previsao = _identidade(eixo)
        prev = PrevisaoRegistrada(
            id=codigo_previsao, modelo_id=versao_id,
            versao_modelo=versao, indicador=relatorio["variavel"],
            geografia=relatorio["regiao"], unidade=relatorio["unidade"],
            periodo=periodo, fonte_verdade=src,
            emitida_em=issue, disponivel_ate=coleta, registrada_em=issue,
            estimativa=f["previsto"], baseline=f["baseline"],
            evidencia_sha256=f["checksum_evidencia"], modo="BACKTEST",
        )
        if coleta > issue:
            raise ErroLedger("features registradas depois da emissão")
        prev.validar()
        observacao = ObservacaoPublicada(
            id=_identidade(("OBSERVACAO", src, relatorio["variavel"],
                            relatorio["regiao"], relatorio["unidade"],
                            periodo, pub.isoformat(), obs_coleta.isoformat())),
            fonte_id=src, indicador=relatorio["variavel"],
            geografia=relatorio["regiao"], unidade=relatorio["unidade"],
            periodo=periodo, publicada_em=pub, registrada_em=obs_coleta,
            valor=f["observado"],
            evidencia_sha256=_identidade((src, periodo,
                                         str(f["observado"]), pub.isoformat(),
                                         obs_coleta.isoformat())),
        )
        observacao.validar()
        previstos.append(prev)
        verdades.append(observacao)

    # Validação integral antes de persistir reduz risco de gravações parciais.
    np, no = 0, 0
    for p, o in zip(previstos, verdades):
        np += ledger.registrar_previsao(p) == "REGISTRADO"
        no += ledger.registrar_observacao(o) == "REGISTRADO"
    return {
        "estado": "REPLAY_SINTETICO_ARQUIVADO_SEM_PROMOCAO",
        "folds": len(previstos), "previsoes_novas": np,
        "observacoes_novas": no, "modelos_homologados": 0,
        "modo": "BACKTEST",
    }
