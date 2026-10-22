"""Conciliação OFFLINE de previsões de FRETE ANUNCIADO previamente arquivadas.

Aceita compromisso HMAC gerado por serviço EXTERNO com chave independente.
A assinatura confere a integridade da declaração, NÃO prova relógio externo,
custódia da chave, origem do RAW ou que a previsão existiu de fato à época.
Nunca cria forecasts a partir de preços realizados. Mede DESLOCAMENTO de
frete BASE por pares fixos disponíveis na emissão e no alvo em D+H dias.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
from math import sqrt, fsum, isfinite
from statistics import median
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from .fretes_atestacoes import serializacao_canonica
from .fretes_painel_pr30 import preparar_painel_pr30
from .fretes_registros import OfertaFrete, ErroRegistroFrete


class ErroAvaliacaoFrete(ErroRegistroFrete):
    """Previsão arquivada, identidade ou proveniência incompatível."""


MT = ZoneInfo("America/Cuiaba")
DOMINIO = b"NIVON_FRETE_PREVISAO_ARQUIVADA_V1\x00"
CAMPOS = frozenset({
    "previsao_id", "modelo_versao", "emissor_id", "fonte_id",
    "origem_ibge", "destino_ibge", "descarga_entity_id",
    "produto", "equipamento", "regime", "pedagio",
    "data_origem", "data_alvo", "horizonte_dias_corridos",
    "emitido_em", "registrado_em", "treinado_ate",
    "delta_previsto_brl_t", "base_snapshot_sha256",
    "assinatura_hmac_sha256",
})


def _hora(value: object, campo: str) -> datetime:
    if not isinstance(value, str) or len(value) > 50:
        raise ErroAvaliacaoFrete(f"{campo}: horário ISO com fuso obrigatório")
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroAvaliacaoFrete(f"{campo}: horário inválido") from exc
    if v.tzinfo is None or v.utcoffset() is None:
        raise ErroAvaliacaoFrete(f"{campo}: fuso obrigatório")
    return v.astimezone(timezone.utc)


def _id(value: object, campo: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or value.strip() != value:
        raise ErroAvaliacaoFrete(f"{campo}: ID inválido")
    return value


def _dia(value: object, campo: str) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ErroAvaliacaoFrete(f"{campo}: data ISO não canônica")
    try:
        v = date.fromisoformat(value)
    except ValueError as exc:
        raise ErroAvaliacaoFrete(f"{campo}: data inválida") from exc
    if v.isoformat() != value:
        raise ErroAvaliacaoFrete(f"{campo}: data não canônica")
    return v


def _delta(value: object) -> Decimal:
    if type(value) is not str or len(value) > 40:
        raise ErroAvaliacaoFrete("delta_previsto_brl_t: Decimal textual obrigatório")
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise ErroAvaliacaoFrete("delta previsto inválido") from exc
    if not d.is_finite() or len(d.as_tuple().digits) > 16 or abs(d) > 1000000:
        raise ErroAvaliacaoFrete("delta fora dos limites econômicos")
    return d


def _digest(value: object, campo: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(x not in "0123456789abcdef" for x in value):
        raise ErroAvaliacaoFrete(f"{campo}: SHA256 inválido")
    return value


def _painel_dia(ofertas: Sequence[OfertaFrete], *, dia: date, corte: datetime, params: Mapping) -> dict:
    filtradas = [x for x in ofertas if isinstance(x, OfertaFrete)
                 and x.data_referencia == dia and x.data_coleta <= corte]
    if not filtradas:
        return {}
    painel = preparar_painel_pr30(filtradas, as_of=corte, **params)
    por_id = {x.registro_id: x for x in filtradas}
    linhas = {}
    for row in painel["observacoes"]:
        evento = por_id[row["lote_id"]]
        chave = (row["pickup_entity_id"], row["transportadora_id"])
        linhas[chave] = {
            **row, "publicacao_em": evento.data_publicacao.astimezone(timezone.utc).isoformat(),
            "coleta_em": evento.data_coleta.astimezone(timezone.utc).isoformat(),
        }
    return linhas


def _assinatura_painel(painel: Mapping) -> str:
    conteudo = [
        [list(k), x["edicao_sha256"], x["preco_rs_t"], x["fonte_id"],
         x["publicacao_em"], x["coleta_em"]]
        for k, x in sorted(painel.items())
    ]
    return sha256(serializacao_canonica({"versao": 1, "pares_base": conteudo})).hexdigest()


def preparar_compromisso_base_frete(
    ofertas: Sequence[OfertaFrete], *, data_origem: str, emitido_em: str,
    origem_ibge: str, destino_ibge: str, descarga_entity_id: str,
    produto: str, equipamento: str, regime: str, pedagio: str,
) -> dict:
    """Retorna hash do snapshot disponível NA EMISSÃO, sem assinar previsões.

    O emissor externo é responsável por guardá-lo ao emitir a previsão.
    O mesmo hash deve ser conferido contra o histórico na avaliação.
    """
    dia, emissao = _dia(data_origem, "data_origem"), _hora(emitido_em, "emitido_em")
    if emissao.astimezone(MT).date() != dia:
        raise ErroAvaliacaoFrete("emissão não pertence ao dia comercial de origem")
    params = dict(origem_ibge=origem_ibge, destino_ibge=destino_ibge,
                  descarga_entity_id=descarga_entity_id, produto=produto,
                  equipamento=equipamento, regime=regime, pedagio=pedagio)
    painel = _painel_dia(ofertas, dia=dia, corte=emissao, params=params)
    if len(painel) < 2:
        raise ErroAvaliacaoFrete("snapshot da emissão tem menos de dois pares")
    return {
        "data_origem": dia.isoformat(),
        "emitido_em": emissao.isoformat(),
        "pares_base": len(painel),
        "base_snapshot_sha256": _assinatura_painel(painel),
        "prova_de_relógio_independente": False,
        "publicavel": False,
    }


def avaliar_previsoes_arquivadas_frete(
    ofertas: Sequence[OfertaFrete], previsoes: Sequence[Mapping], *,
    origem_ibge: str, destino_ibge: str, descarga_entity_id: str,
    produto: str, equipamento: str, regime: str, pedagio: str,
    fonte_id: str, modelo_versao: str, horizonte_dias_corridos: int,
    as_of: datetime, chave_verificacao: bytes, emissor_esperado: str,
    minimo_pares: int = 2, minimo_previsoes: int = 5,
) -> dict:
    """Calcula erros de declarações assinadas e compara com delta ZERO.

    Não admite mistura de rota, modelo, fonte, horizonte, condições nem uma
    previsão não assinada. Não permite seleção silenciosa dos folds; falta de
    pares no alvo bloqueia o lote, não vira amostra descartada conveniente.
    """
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ErroAvaliacaoFrete("as_of timezone-aware obrigatório")
    corte = as_of.astimezone(timezone.utc)
    if (not isinstance(chave_verificacao, bytes) or len(chave_verificacao) < 32
            or type(horizonte_dias_corridos) is not int
            or not 1 <= horizonte_dias_corridos <= 365
            or type(minimo_pares) is not int or not 2 <= minimo_pares <= 100
            or type(minimo_previsoes) is not int or not 5 <= minimo_previsoes <= 10000):
        raise ErroAvaliacaoFrete("configuração de avaliação insegura")
    for k,v in {"fonte_id":fonte_id, "modelo_versao":modelo_versao,
                "emissor_esperado":emissor_esperado}.items():
        _id(v,k)
    if (not isinstance(ofertas, (list,tuple)) or not 1 <= len(ofertas) <= 10000
            or any(not isinstance(x,OfertaFrete) for x in ofertas)
            or not isinstance(previsoes,(list,tuple))
            or not minimo_previsoes <= len(previsoes) <= 10000):
        raise ErroAvaliacaoFrete("histórico ou quantidade de previsões inválidos")

    params = dict(origem_ibge=origem_ibge, destino_ibge=destino_ibge,
                  descarga_entity_id=descarga_entity_id, produto=produto,
                  equipamento=equipamento, regime=regime, pedagio=pedagio)
    # Primeiro valida TODO o histórico para impedir seleção de preço conveniente.
    preparar_painel_pr30(ofertas, as_of=corte, **params)
    vistos, folds = set(), []
    for p in previsoes:
        if not isinstance(p, Mapping) or set(p) != CAMPOS:
            raise ErroAvaliacaoFrete("esquema exato de previsão arquivada obrigatório")
        if any(p.get(k) != v for k,v in {
            **params, "fonte_id":fonte_id, "modelo_versao":modelo_versao,
            "emissor_id":emissor_esperado,
            "horizonte_dias_corridos":horizonte_dias_corridos,
        }.items()):
            raise ErroAvaliacaoFrete("mistura de séries, modelo, fonte, condições ou horizonte")
        ident = _id(p["previsao_id"], "previsao_id")
        if ident in vistos:
            raise ErroAvaliacaoFrete("previsao_id duplicado")
        vistos.add(ident)
        origem, alvo = _dia(p["data_origem"], "data_origem"), _dia(p["data_alvo"], "data_alvo")
        emitido = _hora(p["emitido_em"], "emitido_em")
        registrado = _hora(p["registrado_em"], "registrado_em")
        treinado = _hora(p["treinado_ate"], "treinado_ate")
        if (alvo != origem + timedelta(days=horizonte_dias_corridos)
                or emitido.astimezone(MT).date() != origem
                or not treinado <= emitido <= registrado < datetime.combine(alvo, datetime.min.time(), MT).astimezone(timezone.utc)
                or registrado > corte or alvo > corte.astimezone(MT).date()):
            raise ErroAvaliacaoFrete("previsão registrada após alvo, fora da origem ou sem corte point-in-time")
        previsto = _delta(p["delta_previsto_brl_t"])
        assinatura = _digest(p["assinatura_hmac_sha256"], "assinatura_hmac_sha256")
        _digest(p["base_snapshot_sha256"], "base_snapshot_sha256")
        corpo = dict(p)
        del corpo["assinatura_hmac_sha256"]
        esperada = hmac.new(chave_verificacao, DOMINIO + serializacao_canonica(corpo), sha256).hexdigest()
        if not hmac.compare_digest(assinatura, esperada):
            raise ErroAvaliacaoFrete("assinatura HMAC divergente ou atestador não confiável")
        base = _painel_dia(ofertas, dia=origem, corte=emitido, params=params)
        if len(base) < minimo_pares:
            raise ErroAvaliacaoFrete("painel de origem insuficiente na emissão")
        if _assinatura_painel(base) != p["base_snapshot_sha256"]:
            raise ErroAvaliacaoFrete("snapshot disponível na emissão diverge do compromisso assinado")
        alvo_painel = _painel_dia(ofertas, dia=alvo, corte=corte, params=params)
        mesmos = sorted(base.keys() & alvo_painel.keys())
        if len(mesmos) < minimo_pares:
            raise ErroAvaliacaoFrete("alvo sem pares comparáveis; não descartar fold silenciosamente")
        if any(base[k]["fonte_id"] != fonte_id or alvo_painel[k]["fonte_id"] != fonte_id for k in mesmos):
            raise ErroAvaliacaoFrete("fonte econômica mudou entre origem e alvo")
        if any(_hora(alvo_painel[k]["coleta_em"], "coleta alvo") <= emitido
               for k in mesmos):
            raise ErroAvaliacaoFrete("alvo pode ter sido conhecido antes da emissão")
        # O alvo diário é observação posterior, de forma alguma preço realizado contratado.
        realizado = median(
            Decimal(alvo_painel[k]["preco_rs_t"]) - Decimal(base[k]["preco_rs_t"])
            for k in mesmos
        )
        erro = previsto - realizado
        folds.append({
            "previsao_id": ident, "data_origem": origem.isoformat(),
            "data_alvo": alvo.isoformat(),
            "horizonte_dias_corridos": horizonte_dias_corridos,
            "pares_comparaveis": len(mesmos),
            "delta_previsto_brl_t": str(previsto),
            "delta_observado_anunciado_brl_t": str(realizado),
            "erro_modelo_brl_t": str(erro),
            "erro_baseline_zero_brl_t": str(-realizado),
            "base_snapshot_sha256": p["base_snapshot_sha256"],
            "assinatura_hmac_conferida": True,
        })
    # Evita viés de apresentação: deduplicações por data de origem/alvo.
    chaves = [(x["data_origem"], x["data_alvo"]) for x in folds]
    if len(chaves) != len(set(chaves)):
        raise ErroAvaliacaoFrete("mais de uma previsão sobre mesma origem/alvo; separar modelos")
    folds.sort(key=lambda x:x["data_origem"])
    e = [float(Decimal(x["erro_modelo_brl_t"])) for x in folds]
    eb = [float(Decimal(x["erro_baseline_zero_brl_t"])) for x in folds]
    n = len(folds)
    mae, mae_b = fsum(abs(v) for v in e)/n, fsum(abs(v) for v in eb)/n
    rmse, rmse_b = sqrt(fsum(v*v for v in e)/n),sqrt(fsum(v*v for v in eb)/n)
    if any(not isfinite(v) for v in (mae,mae_b,rmse,rmse_b)):
        raise ErroAvaliacaoFrete("métricas com overflow")
    return {
        "status": "AVALIACAO_DECLARADA_COM_HMAC_OFFLINE_NAO_HOMOLOGADA",
        "orientacao": "AVALIACAO_RETROSPECTIVA_DECLARADA",
        "horizonte_dias_corridos": horizonte_dias_corridos,
        "modelo_versao": modelo_versao,
        "n_previsoes_declaradas": n,
        "unidade": "BRL/T_DESLOCAMENTO_DE_OFERTA_BASE",
        "mae_brl_t": mae, "rmse_brl_t": rmse,
        "mae_baseline_zero_brl_t": mae_b, "rmse_baseline_zero_brl_t": rmse_b,
        "ganho_mae_vs_zero": None if mae_b == 0 else 1-mae/mae_b,
        "ganho_rmse_vs_zero": None if rmse_b == 0 else 1-rmse/rmse_b,
        "folds": folds,
        "hmac_conferido": True,
        "carimbo_temporal_externo_comprovado": False,
        "integridade_raw_provedor_comprovada": False,
        "licenca_de_uso_comprovada": False,
        "vies_de_sobrevivencia_do_painel_avaliado": True,
        "independencia_entre_folds_comprovada": False,
        "habilitado_para_producao": False,
        "probabilidades_calibradas": None,
        "publicavel": False,
        "limitacao": (
            "Resultados numéricos para arquivo declarado assinado, NÃO habilidade "
            "preditiva real homologada. Custódia da chave, emissão em relógio "
            "confiável externo, prova de RAW/consentimento, independência, seleção "
            "dos pares e amostra holdout exigem auditoria adicional."
        ),
    }
