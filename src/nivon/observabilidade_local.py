"""Alertas locais do NIVON: evidência de atraso, não opinião de LLM.

Não conecta rede, não modifica bancos, não revela destinos ou dados de clientes.
Um banco ausente produz COBERTURA_INCOMPLETA, não uma falsa saúde perfeita.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import sqlite3


class ErroObservabilidade(ValueError):
    pass


def _tempo(texto: str) -> datetime:
    try:
        instante=datetime.fromisoformat(texto.replace("Z","+00:00"))
    except (AttributeError,ValueError) as exc:
        raise ErroObservabilidade("timestamp inválido") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroObservabilidade("timestamp sem fuso")
    return instante.astimezone(timezone.utc)


def monitorar_operacao(*, gerado_em: str, conab: sqlite3.Connection | None = None,
                      portos: sqlite3.Connection | None = None,
                      outbox: sqlite3.Connection | None = None,
                      portos_esperados: tuple[str,...] = ()) -> dict:
    agora=_tempo(gerado_em)
    if not isinstance(portos_esperados,tuple) or len(portos_esperados)>45 or len(set(portos_esperados))!=len(portos_esperados):
        raise ErroObservabilidade("portos esperados inválidos")
    if any(not isinstance(x,str) or not 0<len(x)<=80 for x in portos_esperados):
        raise ErroObservabilidade("porto inválido")
    alerts=[]
    cobertura={}
    def emitir(codigo: str, severidade: str, alvo: str, detalhe: str):
        alerts.append({"codigo":codigo,"severidade":severidade,
                       "alvo":alvo,"detalhe":detalhe})
    if conab is None:
        cobertura["conab"]="NAO_CONFIGURADO"
    else:
        try:
            result=conab.execute("SELECT MAX(coletado_utc) FROM progresso_coletas").fetchone()
            timestamp=result[0] if result else None
            cobertura["conab"]="CONSULTADO"
            if not timestamp:
                emitir("CONAB_SEM_COLETA","ALERTA","CONAB","histórico sem captação registrada")
            else:
                idade=agora-_tempo(timestamp)
                if idade<timedelta(0):
                    emitir("CONAB_COLETA_FUTURA","CRITICO","CONAB","captura posterior ao horário de monitoramento")
                elif idade>timedelta(days=9):
                    emitir("CONAB_ATRASADA","ALERTA","CONAB","captura CONAB superior a 9 dias")
        except (sqlite3.Error,ErroObservabilidade):
            cobertura["conab"]="ERRO_BANCO"
            emitir("CONAB_BANCO_INVALIDO","CRITICO","CONAB","erro em leitura do histórico")
    if portos is None:
        cobertura["portos"]="NAO_CONFIGURADO"
    else:
        cobertura["portos"]="CONSULTADO"
        for porto in portos_esperados:
            try:
                row=portos.execute("""
                    SELECT MAX(c.capturado_utc)
                    FROM porto_capturas c JOIN porto_docs d ON c.doc_id=d.id
                    WHERE d.porto=?""",(porto,)).fetchone()
                stamp=row[0] if row else None
                if stamp is None:
                    emitir("PORTO_SEM_COLETA","ALERTA",porto,"sem captura no histórico")
                else:
                    idade=agora-_tempo(stamp)
                    if idade<timedelta(0):
                        emitir("PORTO_COLETA_FUTURA","CRITICO",porto,"captura portuária futura")
                    elif idade>timedelta(hours=72):
                        emitir("PORTO_ATRASADO","ALERTA",porto,"captura portuária superior a 72 horas")
            except (sqlite3.Error,ErroObservabilidade):
                cobertura["portos"]="ERRO_BANCO"
                emitir("PORTO_BANCO_INVALIDO","CRITICO",porto,"erro em histórico portuário")
    if outbox is None:
        cobertura["outbox"]="NAO_CONFIGURADO"
    else:
        try:
            # Não expor HMAC do destinatário, nome, telefone ou ID do provedor.
            r=outbox.execute("""
                SELECT status, agendado_utc, COUNT(*) AS lotes
                FROM briefing_outbox
                WHERE status IN ('PENDING','RESERVED','ACCEPTED')
                GROUP BY status,agendado_utc
                LIMIT 1001""").fetchall()
            cobertura["outbox"]="CONSULTADO"
            if len(r)>1000:
                emitir("OUTBOX_MONITOR_PARCIAL","CRITICO","BRIEFING","mais de 1000 grupos pendentes")
            for item in r[:1000]:
                status,ts,count=item[0],item[1],int(item[2])
                idade=agora-_tempo(ts)
                if idade<timedelta(0):
                    emitir("OUTBOX_AGENDAMENTO_FUTURO","CRITICO","BRIEFING","agendamento posterior à auditoria")
                elif ((status=="PENDING" and idade>timedelta(hours=24)) or
                      (status=="RESERVED" and idade>timedelta(hours=2)) or
                      (status=="ACCEPTED" and idade>timedelta(hours=12))):
                    emitir("OUTBOX_NAO_CONCILIADA","ALERTA","BRIEFING",
                           f"{count} item(ns) em estado {status}; idade desde agendamento excedeu limite")
        except (sqlite3.Error,ErroObservabilidade):
            cobertura["outbox"]="ERRO_BANCO"
            emitir("OUTBOX_BANCO_INVALIDO","CRITICO","BRIEFING","erro de leitura da outbox")
    if not portos_esperados:
        cobertura["portos_monitorados"]=0
    else:
        cobertura["portos_monitorados"]=len(portos_esperados)
    return {
        "estado":"ALERTAS_PRESENTES" if alerts else "SEM_ALERTAS_NA_COBERTURA_LOCAL",
        "cobertura":cobertura,
        "alertas":alerts,
        "execucao":"SOMENTE_LEITURA",
        "coleta_automatica":False,
        "reenvio_automatico":False,
        "prova_de_ausencia_de_incidente":False,
    }
