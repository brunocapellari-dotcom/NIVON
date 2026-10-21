"""Canal WhatsApp Cloud API isolado do NIVON e do projeto WhatsApp AI.

Gera payload de template APROVADO, com opt-in demonstrado. Sem envio implícito.
O texto longo completo precisa ser disponibilizado em URL autorizada; template
não é licença para envio de mensagens livres fora da janela de atendimento.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import hmac
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .lineup_nacional import instante
from .outbox_unificada import _schema as _controle_esquema


class ErroEnvio(ValueError):
    pass


def preparar_template(
    *, destino: str, template: str, resumo: str, link: str,
    gerado_em: str, opt_in_registrado: bool, template_aprovado: bool,
) -> dict:
    if not opt_in_registrado or not template_aprovado:
        raise ErroEnvio("opt-in e template aprovado obrigatórios")
    if not re.fullmatch(r"\d{10,15}", destino):
        raise ErroEnvio("destino em formato internacional numérico")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,100}", template):
        raise ErroEnvio("nome de template inválido")
    if not isinstance(resumo, str) or not 10 <= len(resumo.strip()) <= 500:
        raise ErroEnvio("resumo excede tamanho aprovado para template")
    if not isinstance(link, str) or not link.startswith("https://") or "@" in link or len(link) > 700:
        raise ErroEnvio("link do briefing HTTPS inválido")
    ts = instante(gerado_em)
    payload = {
        "messaging_product": "whatsapp", "to": destino, "type": "template",
        "template": {
            "name": template, "language": {"code": "pt_BR"},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": resumo.strip()},
                {"type": "text", "text": link},
            ]}],
        },
    }
    # Escopo idempotente: mesma edição/destino não pode ganhar segundo ID.
    chave = "|".join((destino, template, ts.isoformat(), resumo.strip(), link))
    return {"idempotency_key": hashlib.sha256(chave.encode()).hexdigest(),
            "payload": payload, "estado": "PREPARADO_NAO_ENVIADO",
            "gerado_em": ts.isoformat(),
            "aviso": "Template deve corresponder EXATAMENTE aos componentes aprovados pela Meta."}


def enviar_cloud_api(preparado: dict, *, phone_number_id: str,
                     permitir_cobranca_e_envio: bool = False, abridor=None,
                     outbox_db: sqlite3.Connection | None = None,
                     chave_destinatario: bytes | None = None,
                     edicao: str | None = None) -> dict:
    """Gateway Cloud API: exige reserva única consumida ANTES do HTTP POST.

    Uma execução que deu timeout continua consumida. Apenas transporte
    explícito e homologado pode abrir a conexão; nenhum redirect implícito.
    """
    if not permitir_cobranca_e_envio:
        raise PermissionError("envio bloqueado por padrão; requer autorização comercial")
    if outbox_db is None or not isinstance(outbox_db, sqlite3.Connection):
        raise PermissionError("OUTBOX_UNICA_OBRIGATORIA: conexão não fornecida")
    from .outbox_whatsapp import _revisar_preparado, _fingerprint
    destino, _, chave = _revisar_preparado(preparado)
    if not isinstance(chave_destinatario, bytes) or len(chave_destinatario) < 24:
        raise PermissionError("chave de destinatário do ledger não configurada")
    if not isinstance(edicao, str):
        raise PermissionError("edição diária ausente")
    destino_hmac=hmac.new(chave_destinatario,destino.encode(),hashlib.sha256).hexdigest()
    configurado=os.environ.get("NIVON_OUTBOX_PATH")
    arquivo=next((row[2] for row in outbox_db.execute("PRAGMA database_list")
                  if row[1]=="main"),"")
    if (not configurado or not Path(configurado).is_absolute()
            or not arquivo or Path(configurado).resolve()!=Path(arquivo).resolve()):
        raise PermissionError("OUTBOX_UNICA_OBRIGATORIA: banco diferente ou em memória")
    if abridor is None:
        raise PermissionError("EGRESS_WHATSAPP_NAO_HOMOLOGADO: transporte explícito necessário")
    token = os.environ.get("NIVON_WHATSAPP_ACCESS_TOKEN")
    if not token or not re.fullmatch(r"\d{5,30}", phone_number_id):
        raise ErroEnvio("credenciais Cloud API ausentes ou id de telefone inválido")
    versao = os.environ.get("NIVON_WHATSAPP_GRAPH_VERSION", "v24.0")
    if not re.fullmatch(r"v\d{1,2}\.\d{1,2}", versao):
        raise ErroEnvio("versão Graph API inválida")

    # O envio direto não pode contornar despachar_registrado. A reserva do
    # gateway é única e durable, mesmo que haja timeout ou erro do provedor.
    _controle_esquema(outbox_db)
    outbox_db.execute("""CREATE TABLE IF NOT EXISTS nivon_api_dispatch (
        idempotency_key TEXT PRIMARY KEY, 
        chamado_utc TEXT NOT NULL
    )""")
    outbox_db.execute("BEGIN IMMEDIATE")
    try:
        row=outbox_db.execute("""SELECT e.estado,e.tentativas,e.edicao,
            e.destinatario_hmac,e.payload_sha256,
            c.estado,r.estado,r.canal,r.intencao_id
            FROM nivon_envios e
            JOIN nivon_consentimentos c ON c.destinatario_hmac=e.destinatario_hmac
            JOIN nivon_reservas_canonicas r
                ON r.dia_local=e.edicao AND r.destinatario_hmac=e.destinatario_hmac
            WHERE e.idempotency_key=?""",(chave,)).fetchone()
        if (row is None or row[0]!="ENVIO_INDETERMINADO" or row[1]!=1
                or row[2]!=edicao or row[3]!=destino_hmac
                or row[4]!=_fingerprint(preparado["payload"])
                or row[5]!="CONCEDIDO" or row[6]!="RESERVADA"
                or row[7]!="WHATSAPP" or row[8]!=chave):
            raise PermissionError("consentimento, estado ou reserva central ausentes")
        outbox_db.execute(
            "INSERT INTO nivon_api_dispatch (idempotency_key,chamado_utc) VALUES (?,?)",
            (chave,datetime.now(timezone.utc).isoformat()),
        )
        outbox_db.commit()
    except sqlite3.IntegrityError as exc:
        outbox_db.rollback()
        raise PermissionError("POST WhatsApp já reservado, sem segunda tentativa") from exc
    except Exception:
        outbox_db.rollback()
        raise

    url = f"https://graph.facebook.com/{versao}/{phone_number_id}/messages"
    req = Request(url, method="POST",
                  headers={"Authorization": "Bearer " + token,
                           "Content-Type": "application/json"},
                  data=json.dumps(preparado["payload"], ensure_ascii=False).encode("utf-8"))
    try:
        with abridor(req, timeout=15) as response:
            if response.status not in (200, 201) or response.geturl()!=url:
                raise ErroEnvio("resposta WhatsApp ou redirect não aceito")
            dados = json.loads(response.read(20000))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ErroEnvio("resultado envio indeterminado: consultar provedor antes de retry") from exc
    mensagens = dados.get("messages", []) if isinstance(dados,dict) else []
    if not isinstance(mensagens, list) or not mensagens or not mensagens[0].get("id"):
        raise ErroEnvio("resposta não contém message_id, estado indeterminado")
    return {"idempotency_key": preparado["idempotency_key"],
            "provider_message_id": mensagens[0]["id"],
            "estado": "ACEITO_PELO_PROVEDOR_AGUARDANDO_WEBHOOK_DE_ENTREGA"}
