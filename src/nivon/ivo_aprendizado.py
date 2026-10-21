"""IVO: contratos offline de aprendizado de conhecimento e de modelos.

Este módulo não utiliza rede, LLM, banco ou credenciais; nunca publica, treina
em produção ou promove uma proposta autonomamente. Cada resultado é evidência
para revisão independente na Knowledge Factory e no fluxo de melhorias Hermes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from hashlib import sha256
from math import isfinite


class ErroAprendizado(ValueError):
    """Candidato sem rastreabilidade, válido temporalmente ou consistente."""


def _instante(valor: datetime, nome: str) -> datetime:
    if not isinstance(valor, datetime) or valor.tzinfo is None or valor.utcoffset() is None:
        raise ErroAprendizado(f"{nome}: instante com fuso horário obrigatório")
    return valor


def _texto(valor: str, nome: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErroAprendizado(f"{nome}: texto obrigatório")
    return valor.strip()


def _numero(valor: float, nome: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not isfinite(valor):
        raise ErroAprendizado(f"{nome}: número finito obrigatório")
    return float(valor)


@dataclass(frozen=True)
class EvidenciaConhecimento:
    fonte_id: str
    organizacao_id: str
    sha256_documento: str
    publicado_em: datetime
    coletado_em: datetime
    fonte_primaria: bool
    direitos_validos: bool

    def validar(self, *, corte: datetime) -> None:
        _texto(self.fonte_id, "fonte_id")
        _texto(self.organizacao_id, "organizacao_id")
        if (not isinstance(self.sha256_documento, str)
                or len(self.sha256_documento) != 64
                or any(c not in "0123456789abcdef" for c in self.sha256_documento)):
            raise ErroAprendizado("hash SHA-256 inválido")
        if not isinstance(self.fonte_primaria, bool) or not isinstance(self.direitos_validos, bool):
            raise ErroAprendizado("status de direitos e origem devem ser booleanos")
        publicado = _instante(self.publicado_em, "publicado_em")
        coletado = _instante(self.coletado_em, "coletado_em")
        if publicado > coletado or coletado > corte:
            raise ErroAprendizado("evidência indisponível na data de corte (look-ahead)")
        if not self.direitos_validos:
            raise ErroAprendizado("evidência sem direitos aprovados para operação solicitada")


@dataclass(frozen=True)
class CandidatoConhecimento:
    afirmacao: str
    dominio: str
    corte: datetime
    evidencias: tuple[EvidenciaConhecimento, ...]
    contradicao_nao_resolvida: bool = False


def avaliar_conhecimento(candidato: CandidatoConhecimento) -> dict:
    """Verifica elegibilidade para auditoria, não promove conhecimento canônico."""
    if not isinstance(candidato, CandidatoConhecimento):
        raise ErroAprendizado("candidato inválido")
    corte = _instante(candidato.corte, "corte")
    afirmacao = _texto(candidato.afirmacao, "afirmacao")
    dominio = _texto(candidato.dominio, "dominio")
    if not isinstance(candidato.contradicao_nao_resolvida, bool):
        raise ErroAprendizado("contradição deve ser booleana")
    if not isinstance(candidato.evidencias, tuple) or not candidato.evidencias:
        raise ErroAprendizado("nenhuma evidência")
    chaves = set()
    organizacoes = set()
    primaria = False
    for evidencia in candidato.evidencias:
        evidencia.validar(corte=corte)
        if evidencia.fonte_id in chaves:
            raise ErroAprendizado("mesma fonte duplicada não é validação cruzada")
        chaves.add(evidencia.fonte_id)
        organizacoes.add(evidencia.organizacao_id)
        primaria |= evidencia.fonte_primaria
    pronta = len(organizacoes) >= 2 and primaria and not candidato.contradicao_nao_resolvida
    return {
        "tipo": "CANDIDATO_CONHECIMENTO",
        "dominio": dominio,
        "corte": corte.isoformat(),
        "id_afirmacao": sha256(afirmacao.encode("utf-8")).hexdigest(),
        "fontes_distintas": len(chaves),
        "organizacoes_independentes": len(organizacoes),
        "tem_fonte_primaria": primaria,
        "contradicao_nao_resolvida": candidato.contradicao_nao_resolvida,
        "estado": "PRONTO_PARA_AUDITORIA" if pronta else "QUARENTENA",
        "promovido_canonico": False,
        "motivo": "Conhecimento só é promovido por fluxo externo independente; nunca por este motor.",
    }


@dataclass(frozen=True)
class PontoPrevisao:
    periodo: str
    emitida_em: datetime
    publicado_observado_em: datetime
    observado: float
    previsto: float
    baseline: float


def avaliar_modelo(
    pontos: tuple[PontoPrevisao, ...], *,
    modelo_id: str, dados_reais_homologados: bool = False,
    minimo_folds: int = 6, melhoria_minima: float = 0.05,
) -> dict:
    """Backtest temporal imutável, pontual, com baseline e veto a promoção.

    Os pontos precisam ter sido produzidos por backtest fora da amostra; isto
    NÃO treina modelo nem certifica independência dos dados, vintages ou folds.
    """
    _texto(modelo_id, "modelo_id")
    if type(dados_reais_homologados) is not bool:
        raise ErroAprendizado("dados_reais_homologados inválido")
    if type(minimo_folds) is not int or minimo_folds < 3:
        raise ErroAprendizado("mínimo de folds insuficiente")
    melhoria = _numero(melhoria_minima, "melhoria_minima")
    if not 0 <= melhoria < 1:
        raise ErroAprendizado("melhoria mínima fora do intervalo")
    if not isinstance(pontos, tuple) or len(pontos) < minimo_folds:
        raise ErroAprendizado("backtest temporal insuficiente")
    periodos = set()
    erro_modelo = 0.0
    erro_baseline = 0.0
    soma_reais = 0.0
    for ponto in pontos:
        if not isinstance(ponto, PontoPrevisao):
            raise ErroAprendizado("fold inválido")
        periodo = _texto(ponto.periodo, "periodo")
        if periodo in periodos:
            raise ErroAprendizado("fold duplicado")
        periodos.add(periodo)
        try:
            alvo = date.fromisoformat(periodo + "-01")
            if alvo.strftime("%Y-%m") != periodo:
                raise ValueError("formato não canônico")
        except (ValueError, TypeError) as exc:
            raise ErroAprendizado("período esperado: AAAA-MM") from exc
        emitida = _instante(ponto.emitida_em, "emitida_em")
        observada_em = _instante(ponto.publicado_observado_em, "publicado_observado_em")
        if emitida.date() >= alvo:
            raise ErroAprendizado("previsão mensal deve ser emitida antes do início do mês previsto")
        if emitida >= observada_em or observada_em.date() <= alvo:
            raise ErroAprendizado("previsão emitida após divulgação ou observado publicado antes do período")
        real = _numero(ponto.observado, "observado")
        previsto = _numero(ponto.previsto, "previsto")
        base = _numero(ponto.baseline, "baseline")
        if min(real, previsto, base) < 0:
            raise ErroAprendizado("volume/preço negativo")
        erro_modelo += abs(real - previsto)
        erro_baseline += abs(real - base)
        soma_reais += abs(real)
    mae_modelo = erro_modelo / len(pontos)
    mae_baseline = erro_baseline / len(pontos)
    ganho = ((erro_baseline - erro_modelo) / erro_baseline) if erro_baseline else None
    supera = ganho is not None and ganho >= melhoria
    return {
        "tipo": "CANDIDATO_MODELO",
        "modelo_id": modelo_id,
        "folds": len(pontos),
        "mae_modelo": mae_modelo,
        "mae_baseline": mae_baseline,
        "wape_modelo": erro_modelo / soma_reais if soma_reais else None,
        "wape_baseline": erro_baseline / soma_reais if soma_reais else None,
        "melhoria_relativa_sobre_baseline": ganho,
        "supera_baseline": supera,
        "estado": "PRONTO_PARA_AUDITORIA" if supera and dados_reais_homologados else "NAO_HOMOLOGADO",
        "promovido_operacional": False,
        "motivo": "Backtest não prova causalidade, calibração de probabilidades nem autorização de produção; exige avaliação independente, dados as-of e aprovação externa.",
    }
