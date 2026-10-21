"""IVO — intervalos empíricos de erro, com calibração estritamente as-of.

Implementação ilustrativa de quantil conformal sobre erros absolutos disponíveis
antes da emissão. Não promete cobertura frequentista em séries dependentes, nem
faz promoção/treino/consulta externa. Usa exclusivamente saídas do ledger IVO.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil, isfinite

from .ivo_previsao_ledger import ErroLedger, PrevisaoRegistrada


def _utc(valor: str) -> datetime:
    try:
        d = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as exc:
        raise ErroLedger("data histórica não ISO") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroLedger("data histórica exige fuso")
    return d.astimezone(timezone.utc)


def intervalo_empirico_asof(
    previsao: PrevisaoRegistrada,
    avaliacao: dict,
    *,
    confianca_nominal: float = 0.8,
    minimo_folds: int = 12,
    max_folds: int = 60,
) -> dict:
    """Retorna intervalo conservador somente se rótulos já estavam conhecidos.

    Relatórios BACKTEST são mantidos como BACKTEST, nunca confundidos com LIVE.
    A avaliação pode ter sido obtida em data posterior à emissão: todas as linhas
    posteriores são removidas pelo instante publicado/coletado, sem look-ahead.
    """
    if not isinstance(previsao, PrevisaoRegistrada):
        raise ErroLedger("previsão canônica obrigatória")
    horizonte = previsao.validar()
    if not isinstance(avaliacao, dict) or avaliacao.get("status") != "AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA":
        raise ErroLedger("avaliação homogênea de ledger necessária")
    if avaliacao.get("agregacao_comparavel") is not True:
        raise ErroLedger("folds de medidas distintas não são comparáveis")
    if avaliacao.get("modo") != previsao.modo:
        raise ErroLedger("LIVE e BACKTEST não podem fornecer calibração cruzada")
    if avaliacao.get("verdade") != "PRIMEIRA_PUBLICACAO":
        raise ErroLedger("calibração exige primeira publicação, não revisão mais recente")
    if type(minimo_folds) is not int or type(max_folds) is not int or not 5 <= minimo_folds <= max_folds <= 500:
        raise ErroLedger("tamanho de calibração inválido")
    if isinstance(confianca_nominal, bool) or not isinstance(confianca_nominal, (int, float)):
        raise ErroLedger("confiança nominal inválida")
    if not isfinite(confianca_nominal) or not .5 <= confianca_nominal <= .99:
        raise ErroLedger("confiança nominal fora do intervalo")
    if not isinstance(avaliacao.get("avaliacoes"), list):
        raise ErroLedger("folds ausentes")
    emitida = previsao.emitida_em.astimezone(timezone.utc)
    vistos = set()
    validos = []
    for item in avaliacao["avaliacoes"]:
        if not isinstance(item, dict):
            raise ErroLedger("fold inválido")
        if (item.get("modelo_id"), item.get("versao_modelo"),
            item.get("indicador"), item.get("geografia"),
            item.get("unidade"), item.get("fonte_verdade"),
            item.get("horizonte_meses")) != (
            previsao.modelo_id, previsao.versao_modelo,
            previsao.indicador, previsao.geografia,
            previsao.unidade, previsao.fonte_verdade, horizonte
        ):
            continue
        p_id = item.get("previsao_id")
        o_id = item.get("observacao_id")
        if not isinstance(p_id, str) or not p_id or not isinstance(o_id, str) or not o_id:
            raise ErroLedger("IDs de evidência ausentes")
        if p_id in vistos:
            raise ErroLedger("previsão histórica duplicada na calibração")
        vistos.add(p_id)
        publicada = _utc(item.get("vintage_publicada_em"))
        registrada = _utc(item.get("observacao_registrada_em"))
        emissao_historica = _utc(item.get("previsao_emitida_em"))
        registro_historico = _utc(item.get("previsao_registrada_em"))
        if registrada < publicada or registro_historico < emissao_historica:
            raise ErroLedger("evidência com ordem temporal impossível")
        if (registrada >= emitida or publicada >= emitida or
                registro_historico >= publicada):
            # Evidência futura ou backtest registrado depois do resultado:
            # no BACKTEST a emissão pode ser histórica; o aviso explicita
            # que a emissão foi reconstruída, sem fingir emissão LIVE.
            continue
        if emissao_historica >= emitida or item.get("periodo", "") >= previsao.periodo:
            continue
        erro = item.get("erro_absoluto")
        if isinstance(erro, bool) or not isinstance(erro, (int, float)) or not isfinite(erro) or erro < 0:
            raise ErroLedger("erro histórico ausente, negativo ou não finito")
        validos.append((registrada, p_id, o_id, float(erro)))
    validos.sort(key=lambda x: (x[0], x[1]))
    amostra = validos[-max_folds:]
    n = len(amostra)
    resultado = {
        "modelo_id": previsao.modelo_id,
        "versao_modelo": previsao.versao_modelo,
        "indicador": previsao.indicador,
        "geografia": previsao.geografia,
        "unidade": previsao.unidade,
        "periodo": previsao.periodo,
        "horizonte_meses": horizonte,
        "modo": previsao.modo,
        "nominal": float(confianca_nominal),
        "corte_asof": emitida.isoformat(),
        "candidatos_elegiveis": n,
        "intervalo_homologado": False,
        "promocao_automatica": False,
        "evidencias": [{"previsao_id": v[1], "observacao_id": v[2]} for v in amostra],
        "aviso": ("Quantil conformal empírico sobre erros passados; a dependência temporal, "
                  "quebras de regime e o histórico retrospectivo impedem afirmar "
                  "garantia de cobertura estatística sem validação adicional."),
    }
    if n < minimo_folds:
        return dict(resultado, status="AMOSTRA_INSUFICIENTE", limite_inferior=None,
                    limite_superior=None, raio_erro=None)
    posicao = ceil((n+1) * float(confianca_nominal) - 1e-12)
    if posicao > n:
        return dict(resultado, status="NIVEL_NAO_CALIBRAVEL_COM_AMOSTRA_ATUAL",
                    limite_inferior=None, limite_superior=None, raio_erro=None)
    q = sorted(x[3] for x in amostra)[posicao-1]
    return dict(
        resultado, status="INTERVALO_EXPERIMENTAL_NAO_HOMOLOGADO",
        raio_erro=q, limite_inferior=max(0., float(previsao.estimativa)-q),
        limite_superior=float(previsao.estimativa)+q,
        quantil_ordem=posicao,
    )
