"""Ciclo SHADOW local: conferir ofertas -> gerar baseline -> assinar -> ledger -> recibo.

Executor exclusivo para treinamento/integração OFFLINE. As chaves HMAC e
relógio do processo NÃO são testemunha independente. Nenhuma habilidade de
previsão foi homologada. O receipt de disco fica fora do arquivo SQLite,
mas não prova origem remota ou imutabilidade WORM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import sqlite3
from pathlib import Path

from .fretes_atestacoes import serializacao_canonica
from .fretes_baseline_shadow import preparar_intencoes_baseline_frete
from .fretes_ledger_persistente import (
    ErroLedgerFrete, verificar_ledger_frete, anexar_lote_previsoes_frete,
)
from .fretes_ofertas_store import verificar_store_ofertas_frete
from .fretes_previsoes_arquivadas import DOMINIO, ErroAvaliacaoFrete
from .fretes_recibos_ancora import (
    criar_recibo_local_frete, salvar_recibo_em_diretorio_local,
    ErroReciboFrete,
)
from .fretes_registros import OfertaFrete


class ErroCicloShadowFrete(ErroAvaliacaoFrete):
    """Bloqueio de execução shadow insegura ou de entrada incompatível."""


def _ofertas_rota(rows, *, fonte_id, condicoes):
    retorno=[]
    for x in rows:
        if not isinstance(x,OfertaFrete):
            raise ErroCicloShadowFrete("histórico inválido")
        ped="ADICIONAL" if x.pedagio_brl_t is not None else "NAO_INFORMADO"
        if (x.municipio_ibge==condicoes["origem_ibge"]
                and x.destino_ibge==condicoes["destino_ibge"]
                and x.descarga_entity_id==condicoes["descarga_entity_id"]
                and x.produto==condicoes["produto"]
                and x.equipamento==condicoes["equipamento"]
                and x.regime==condicoes["regime"]
                and ped==condicoes["pedagio"]
                and x.fonte_id==fonte_id):
            retorno.append(x)
    return retorno


def executar_ciclo_shadow_frete_local(
    con: sqlite3.Connection, *, recebido_em: datetime,
    cabeca_ofertas_esperada: str, cabeca_previsoes_esperada: str,
    condicoes: dict, fonte_id: str, emissor_previsao: str,
    chave_previsao: bytes, emissor_recibo: str, chave_recibo: bytes,
    diretorio_recibos: str | Path,
    horizontes_dias: tuple[int,...] = (7,30,90),
) -> dict:
    """Grava 3 previsões assinadas LOCALMENTE e devolve recibo separado.

    Se recibo pós-commit falhar, devolve a nova cabeça e status
    SEM_RECIBO para recuperação explícita, NUNCA sucesso silencioso.
    Cabeças anteriores devem vir do controlador de evidências, não
    do próprio banco; o protótipo não prova essa separação.
    """
    if not isinstance(con,sqlite3.Connection) or con.in_transaction:
        raise ErroCicloShadowFrete("SQLite disponível sem transação externa obrigatório")
    if (not isinstance(recebido_em,datetime) or recebido_em.tzinfo is None
            or recebido_em.utcoffset() is None):
        raise ErroCicloShadowFrete("tempo de emissão exige timezone")
    if (not isinstance(condicoes,dict) or set(condicoes)!={
            "origem_ibge","destino_ibge","descarga_entity_id",
            "produto","equipamento","regime","pedagio"
        } or any(not isinstance(v,str) or not v for v in condicoes.values())):
        raise ErroCicloShadowFrete("identidade econômica incompleta")
    if (not isinstance(chave_previsao,bytes) or len(chave_previsao)<32
            or not isinstance(chave_recibo,bytes) or len(chave_recibo)<32
            or chave_previsao==chave_recibo):
        raise ErroCicloShadowFrete("chaves de previsão e recibo devem ser distintas")
    agora=recebido_em.astimezone(timezone.utc)
    origens=verificar_store_ofertas_frete(
        con,cabeca_esperada_sha256=cabeca_ofertas_esperada
    )
    antiga=verificar_ledger_frete(
        con,cabeca_esperada_sha256=cabeca_previsoes_esperada,
        chave_verificacao=chave_previsao,
        emissor_esperado=emissor_previsao,
    )
    rows=_ofertas_rota(
        origens["ofertas"],fonte_id=fonte_id,condicoes=condicoes
    )
    if any(x.data_coleta.astimezone(timezone.utc)>agora for x in rows):
        raise ErroCicloShadowFrete("histórico contém dados posteriores ao instante de emissão")
    propostas=preparar_intencoes_baseline_frete(
        rows,emitido_em=agora,fonte_id=fonte_id,
        emissor_id=emissor_previsao,horizontes_dias=horizontes_dias,
        **condicoes,
    )
    from .fretes_previsoes_arquivadas import MT
    hoje=agora.astimezone(MT).date().isoformat()
    # Dia/modelo/horizonte não pode ser reemitido sob mesmo modelo e rota.
    for antiga_prev in antiga["previsoes"]:
        if (antiga_prev["data_origem"]==hoje
                and antiga_prev["modelo_versao"]==propostas["modelo_versao"]
                and antiga_prev["fonte_id"]==fonte_id
                and all(antiga_prev.get(k)==v for k,v in condicoes.items())
                and antiga_prev["horizonte_dias_corridos"] in horizontes_dias):
            raise ErroCicloShadowFrete("previsão shadow já foi emitida neste dia/rota")
    previsoes=[]
    for p in propostas["previsoes_para_assinatura_externa"]:
        dados={**p,"registrado_em":agora.isoformat()}
        # MOCK DE INTEGRAÇÃO: a assinatura local não comprova emissão
        # por serviço independente nem vinculação a relógio remoto.
        digest=hmac.new(
            chave_previsao,DOMINIO+serializacao_canonica(dados),sha256
        ).hexdigest()
        previsoes.append({**dados,"assinatura_hmac_sha256":digest})
    atual=anexar_lote_previsoes_frete(
        con,previsoes,recebimentos=[agora]*len(previsoes),
        cabeca_anterior_sha256=cabeca_previsoes_esperada,
        chave_verificacao=chave_previsao,
        emissor_esperado=emissor_previsao,
    )
    comprovante={
        "status":"PREVISOES_SHADOW_LOCAIS_GRAVADAS",
        "ofertas_cabeca_sha256":origens["cabeca_sha256"],
        "previsoes_cabeca_sha256":atual["cabeca_sha256"],
        "previsoes_gravadas":atual["adicionados"],
        "previsoes_total":atual["total"],
        "modelo_versao":propostas["modelo_versao"],
        "horizontes_dias_corridos":list(horizontes_dias),
        "previsoes_assinadas_por_servico_independente":False,
        "timestamp_independente_comprovado":False,
        "armazenamento_recibo_cloud_worm":False,
        "previsao_homologada":False,
        "publicavel":False,
    }
    # Ledger JÁ foi commitado; tentativa de recibo nunca desfaz o ledger.
    try:
        recibo=criar_recibo_local_frete(
            tipo_ledger="PREVISOES",emissor_id=emissor_recibo,
            cabeca_sha256=atual["cabeca_sha256"],
            sequencia=atual["total"],assinado_em=agora,
            chave_recibo=chave_recibo,
        )
        salvamento=salvar_recibo_em_diretorio_local(
            recibo,diretorio_privado=diretorio_recibos,
        )
    except (ErroReciboFrete,OSError,ValueError) as exc:
        return {
            **comprovante,
            "status":"PREVISOES_GRAVADAS_SEM_RECIBO_LOCAL",
            "recibo_local_emitido":False,
            "recuperacao_necessaria":True,
        }
    return {
        **comprovante,
        "status":"SHADOW_GRAVADO_COM_RECIBO_LOCAL_NAO_INDEPENDENTE",
        "recibo_local_emitido":True,
        "recibo_local_sha256":salvamento["sha256"],
        "recibo_local_caminho":salvamento["caminho_local"],
        "recuperacao_necessaria":False,
    }
