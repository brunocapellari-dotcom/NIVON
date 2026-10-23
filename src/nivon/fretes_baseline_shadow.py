"""Preparador de previsões BASELINE em shadow para fretes anunciados R01.

Somente cria INTENÇÕES não assinadas em D para D+7/30/90 dias corridos.
Valor previsto do deslocamento BRL/t = ZERO (persistência); não extrapola
tendência nem usa qualquer dado publicado/coletado após a emissão.

A assinatura e o carimbo confiável de registro pertencem a serviço externo.
A função nunca finge ter arquivado dados ou concluído avaliação OOS.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Sequence

from .fretes_atestacoes import serializacao_canonica
from .fretes_painel_pr30 import preparar_painel_pr30
from .fretes_previsoes_arquivadas import (
    MT, ErroAvaliacaoFrete, preparar_compromisso_base_frete,
)
from .fretes_registros import OfertaFrete

MODELO_BASELINE_ZERO="BASELINE_PERSISTENCIA_DELTA_ZERO_V1"


def preparar_intencoes_baseline_frete(
    ofertas: Sequence[OfertaFrete], *,
    emitido_em: datetime, origem_ibge: str, destino_ibge: str,
    descarga_entity_id: str, produto: str, equipamento: str,
    regime: str, pedagio: str, fonte_id: str, emissor_id: str,
    horizontes_dias: tuple[int,...]=(7,30,90),
    minimo_pares: int=2,
) -> dict:
    """Fornece contratos incompletos para SIGNER EXTERNO (sem HMAC nem DB).

    O signer externo deve anexar registrado_em, usar relógio independente,
    validar o hash e assinar toda a previsão sob o contrato HMAC previsto.
    Nenhuma previsão é admitida no ledger antes desses passos.
    """
    if (not isinstance(emitido_em,datetime) or emitido_em.tzinfo is None
            or emitido_em.utcoffset() is None):
        raise ErroAvaliacaoFrete("emissão exige instante timezone-aware")
    instante=emitido_em.astimezone(timezone.utc)
    if (not isinstance(ofertas,(list,tuple)) or not 2<=len(ofertas)<=10000
            or any(not isinstance(x,OfertaFrete) for x in ofertas)):
        raise ErroAvaliacaoFrete("ofertas canônicas obrigatórias")
    if (not isinstance(horizontes_dias,tuple)
            or not 1<=len(horizontes_dias)<=8
            or any(type(h) is not int or not 1<=h<=365 for h in horizontes_dias)
            or list(horizontes_dias)!=sorted(set(horizontes_dias))):
        raise ErroAvaliacaoFrete("horizontes distintos e ordenados em dias corridos")
    if type(minimo_pares) is not int or not 2<=minimo_pares<=100:
        raise ErroAvaliacaoFrete("mínimo de pares inválido")
    if (not isinstance(fonte_id,str) or not fonte_id.strip() or len(fonte_id)>120
            or not isinstance(emissor_id,str) or not emissor_id.strip()
            or len(emissor_id)>120):
        raise ErroAvaliacaoFrete("fonte e emissor confiáveis obrigatórios")
    # CRÍTICO: em hipótese alguma transformar retrospectivamente dados futuros
    # em previsão supostamente emitida no passado.
    if any(x.data_publicacao > instante or x.data_coleta > instante for x in ofertas):
        raise ErroAvaliacaoFrete("histórico contém dados posteriores à emissão")
    if any(x.fonte_id!=fonte_id for x in ofertas):
        raise ErroAvaliacaoFrete("mistura de fontes na série do emissor")
    econ=dict(
        origem_ibge=origem_ibge,destino_ibge=destino_ibge,
        descarga_entity_id=descarga_entity_id,produto=produto,
        equipamento=equipamento,regime=regime,pedagio=pedagio,
    )
    prep=preparar_painel_pr30(ofertas,as_of=instante,**econ)
    local=instante.astimezone(MT).date()
    atual=[row for row in prep["observacoes"] if row["periodo"]==local.isoformat()]
    pares={(r["pickup_entity_id"],r["transportadora_id"]) for r in atual}
    if len(pares)<minimo_pares:
        raise ErroAvaliacaoFrete("dia de emissão não tem pares comparáveis suficientes")
    snapshot=preparar_compromisso_base_frete(
        ofertas,data_origem=local.isoformat(),
        emitido_em=instante.isoformat(),**econ,
    )
    if snapshot["pares_base"]!=len(pares):
        raise ErroAvaliacaoFrete("snapshot inconsistente com a série preparada")
    # O baseline de persistência não tem treinamento estatístico, mas só pode
    # referenciar a coleta observacional no instante de emissão, nunca alvo.
    disponivel_ate=max(x.data_coleta.astimezone(timezone.utc)
                      for x in ofertas if x.data_referencia==local)
    if disponivel_ate>instante:
        raise ErroAvaliacaoFrete("dados de origem indisponíveis na emissão")
    propostas=[]
    for horizonte in horizontes_dias:
        target=local+timedelta(days=horizonte)
        identidade={
            **econ, "fonte_id":fonte_id,
            "modelo_versao":MODELO_BASELINE_ZERO,
            "data_origem":local.isoformat(),
            "horizonte_dias_corridos":horizonte,
            "base_snapshot_sha256":snapshot["base_snapshot_sha256"],
        }
        digest=sha256(serializacao_canonica(identidade)).hexdigest()
        propostas.append({
            **econ,"fonte_id":fonte_id,
            "previsao_id":"baseline:"+digest,
            "modelo_versao":MODELO_BASELINE_ZERO,
            "emissor_id":emissor_id,
            "data_origem":local.isoformat(),
            "data_alvo":target.isoformat(),
            "horizonte_dias_corridos":horizonte,
            "emitido_em":instante.isoformat(),
            "treinado_ate":disponivel_ate.isoformat(),
            "delta_previsto_brl_t":"0",
            "base_snapshot_sha256":snapshot["base_snapshot_sha256"],
        })
    return {
        "status":"INTENCOES_BASELINE_SHADOW_NAO_ASSINADAS",
        "modelo_versao":MODELO_BASELINE_ZERO,
        "origem":local.isoformat(),
        "horizontes_dias_corridos":list(horizontes_dias),
        "pares_origem":len(pares),
        "previsoes_para_assinatura_externa":propostas,
        "registrado_em":None,
        "assinaturas_criadas":False,
        "persistencia_realizada":False,
        "desempenho_historico_comprovado":False,
        "publicavel":False,
        "probabilidades_calibradas":None,
        "proxima_etapa":"ASSINATURA_E_REGISTRO_IMEDIATOS_EM_SERVICO_EXTERNO",
    }
