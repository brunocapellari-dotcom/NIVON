"""Auditoria SOMENTE LEITURA das três camadas de outbox NIVON.

Detecta divergências sem inferir que status legado constitui entrega real.
Nenhuma função envia, muda o banco, consulta rede ou homologa opt-in.
Devolve SOMENTE contagens, nunca destinatário, telefone, ID de provider ou texto.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from .outbox_unificada import ErroControleEnvio

MAX_LINHAS=200_000
ATIVOS=frozenset({"RESERVED","ACCEPTED","DELIVERED"})
WHATSAPP_POS=frozenset({"ENVIO_INDETERMINADO","ACEITO_PROVEDOR","ENVIADO",
                        "ENTREGUE","LIDO","FALHOU"})
COM_RECIBO_WPP=frozenset({"ACEITO_PROVEDOR","ENVIADO","ENTREGUE","LIDO"})
ESTADOS_WPP=frozenset({"PREPARADO","ENVIO_INDETERMINADO","ACEITO_PROVEDOR",
                       "ENVIADO","ENTREGUE","LIDO","FALHOU"})


def _has(db: sqlite3.Connection,nome: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (nome,)).fetchone() is not None


def _rows(db: sqlite3.Connection, table: str, sql: str) -> list:
    if not _has(db,table):
        return []
    rows=db.execute(sql).fetchmany(MAX_LINHAS+1)
    if len(rows)>MAX_LINHAS:
        raise ErroControleEnvio("auditoria excede limite; usar varredura paginada")
    return rows


def auditar_integridade_envios(db: sqlite3.Connection) -> dict:
    """Relatório determinístico read-only, inclusive em base legado incompleta."""
    if db.in_transaction:
        raise ErroControleEnvio("auditoria exige snapshot sem transação de escrita aberta")
    flag=Counter()
    counts=Counter()
    # Presença dos quatro esquemas é requisito, não credencial/consentimento.
    required=("briefing_outbox","nivon_envios","nivon_consentimentos",
              "nivon_reservas_canonicas","nivon_recibos_canonicos")
    for table in required:
        if not _has(db,table):
            flag["TABELA_AUSENTE"]+=1
    consent=dict(_rows(db,"nivon_consentimentos",
                      "SELECT destinatario_hmac,estado FROM nivon_consentimentos"))
    slots={}
    for d,h,canal,intencao,estado in _rows(db,"nivon_reservas_canonicas",
        "SELECT dia_local,destinatario_hmac,canal,intencao_id,estado FROM nivon_reservas_canonicas"):
        counts["reservas"]+=1
        slots[(d,h)]=(canal,str(intencao),estado)
        if consent.get(h) is None:
            flag["RESERVA_SEM_CONSENTIMENTO"]+=1
        elif consent[h]=="REVOGADO" and estado=="RESERVADA":
            flag["RESERVA_ATIVA_COM_OPTOUT"]+=1
    legacy={}
    by_day=defaultdict(list)
    providers=defaultdict(list)
    for id_,day,h,status,pid in _rows(db,"briefing_outbox",
        "SELECT id,dia_local,destinatario_hmac,status,provider_message_id FROM briefing_outbox"):
        counts["briefings"]+=1
        k=(day,h); ident=("BRIEFING",str(id_))
        legacy[ident]=(k,status,pid)
        by_day[k].append(ident)
        if pid: providers[pid].append(ident)
        slot=slots.get(k)
        if status in ATIVOS and (slot is None or slot[0]!="BRIEFING" or slot[1]!=str(id_)):
            flag["LEGADO_SEM_RESERVA_CORRESPONDENTE"]+=1
        if status in {"ACCEPTED","DELIVERED"} and not pid:
            flag["LEGADO_CONFIRMADO_SEM_PROVIDER"]+=1
        if status=="PENDING" and slot is not None and slot[:2]==ident:
            flag["PENDENTE_COM_RESERVA"]+=1
    for chave,day,h,status,pid in _rows(db,"nivon_envios",
        "SELECT idempotency_key,edicao,destinatario_hmac,estado,provider_message_id FROM nivon_envios"):
        counts["whatsapp"]+=1
        k=(day,h); ident=("WHATSAPP",chave)
        legacy[ident]=(k,status,pid)
        by_day[k].append(ident)
        if pid: providers[pid].append(ident)
        slot=slots.get(k)
        if status not in ESTADOS_WPP:
            flag["ESTADO_LEGADO_DESCONHECIDO"]+=1
        if status in WHATSAPP_POS and (slot is None or slot[0]!="WHATSAPP" or slot[1]!=chave):
            flag["LEGADO_SEM_RESERVA_CORRESPONDENTE"]+=1
        if status in COM_RECIBO_WPP and not pid:
            flag["LEGADO_CONFIRMADO_SEM_PROVIDER"]+=1
        if status=="PREPARADO" and slot is not None and slot[:2]==ident:
            flag["PENDENTE_COM_RESERVA"]+=1
    for _,c in by_day.items():
        if c and len(c)>1:
            flag["MULTIPLAS_INTENCOES_DIA_DESTINATARIO"]+=len(c)
    for _,c in providers.items():
        if len(c)>1:
            flag["PROVIDER_REUTILIZADO"]+=len(c)
    for k,slot in slots.items():
        if (slot[0],slot[1]) not in legacy:
            flag["RESERVA_SEM_LEGADO"]+=1
    canon_by_provider={}
    for day,h,canal,intencao,pid,estado,entregue in _rows(db,"nivon_recibos_canonicos",
        "SELECT dia_local,destinatario_hmac,canal,intencao_id,provider_message_id,estado,entregue_utc FROM nivon_recibos_canonicos"):
        counts["recibos"]+=1
        k=(day,h)
        canon_by_provider[pid]=(canal,str(intencao),estado)
        if slots.get(k) is None or slots[k][:2]!=(canal,str(intencao)):
            flag["RECIBO_SEM_RESERVA_CORRESPONDENTE"]+=1
        row=legacy.get((canal,str(intencao)))
        if row is None or row[0]!=k or row[2]!=pid:
            flag["RECIBO_SEM_LEGADO_CORRESPONDENTE"]+=1
        else:
            atual=row[1]
            expected={"ACCEPTED":"ACEITO_PROVEDOR","DELIVERED":"ENTREGUE"}.get(atual,atual)
            if expected!=estado:
                flag["ESTADO_LEGADO_CANONICO_DIVERGENTE"]+=1
        if estado in {"ENTREGUE","LIDO"} and not entregue:
            # Um 'read' direto pode vir sem comprovante 'delivered'.
            # É lacuna de evidência, não licença para inventar timestamp.
            flag["ENTREGA_SEM_TIMESTAMP"]+=1
        if estado not in {"ENTREGUE","LIDO"} and entregue:
            flag["TIMESTAMP_ENTREGA_INCOMPATIVEL"]+=1
    for pid,refs in providers.items():
        # Um ACK sem recibo canônico NÃO comprova entrega operacional.
        if pid not in canon_by_provider:
            flag["ACK_SEM_RECIBO_CANONICO"]+=len(refs)
    # Quarentena mantém trilha de registros sem promoção automática.
    if _has(db,"nivon_quarentena_legado"):
        quarantined=_rows(db,"nivon_quarentena_legado",
                          "SELECT registro_sha256 FROM nivon_quarentena_legado")
        counts["quarentena"]+=len(quarantined)
    status="SEM_DIVERGENCIAS_ESTRUTURAIS" if not flag else "DIVERGENCIAS_A_RECONCILIAR"
    return {"situacao":status,"contagens":dict(sorted(counts.items())),
            "anomalias":dict(sorted(flag.items())),
            "total_anomalias":sum(flag.values()),"somente_leitura":True,
            "homologacao_externa_verificada":False,
            "envio_autorizado":False,"promocao_automatica":False}
