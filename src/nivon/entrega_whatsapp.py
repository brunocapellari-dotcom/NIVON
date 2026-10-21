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
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .lineup_nacional import instante


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
                     permitir_cobranca_e_envio: bool = False, abridor=urlopen) -> dict:
    """Envio síncrono explícito, sem retries: timeout não significa falha não cobrada.

    Host fixo evita egress arbitrário; token exclusivamente por variável de ambiente.
    Retorno traz message_id do provedor, que NÃO comprova entrega ao aparelho.
    """
    if not permitir_cobranca_e_envio:
        raise PermissionError("envio bloqueado por padrão; requer autorização comercial")
    token = os.environ.get("NIVON_WHATSAPP_ACCESS_TOKEN")
    if not token or not re.fullmatch(r"\d{5,30}", phone_number_id):
        raise ErroEnvio("credenciais Cloud API ausentes ou id de telefone inválido")
    if preparado.get("estado") != "PREPARADO_NAO_ENVIADO":
        raise ErroEnvio("payload não preparado")
    versao = os.environ.get("NIVON_WHATSAPP_GRAPH_VERSION", "v24.0")
    if not re.fullmatch(r"v\d{1,2}\.\d{1,2}", versao):
        raise ErroEnvio("versão Graph API inválida")
    url = f"https://graph.facebook.com/{versao}/{phone_number_id}/messages"
    req = Request(url, method="POST",
                  headers={"Authorization": "Bearer " + token,
                           "Content-Type": "application/json"},
                  data=json.dumps(preparado["payload"], ensure_ascii=False).encode("utf-8"))
    try:
        with abridor(req, timeout=15) as response:
            if response.status not in (200, 201):
                raise ErroEnvio("resposta WhatsApp não aceita")
            dados = json.loads(response.read(20000))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ErroEnvio("resultado envio indeterminado: consultar provedor antes de retry") from exc
    mensagens = dados.get("messages", [])
    if not isinstance(mensagens, list) or not mensagens or not mensagens[0].get("id"):
        raise ErroEnvio("resposta não contém message_id, estado indeterminado")
    return {"idempotency_key": preparado["idempotency_key"],
            "provider_message_id": mensagens[0]["id"],
            "estado": "ACEITO_PELO_PROVEDOR_AGUARDANDO_WEBHOOK_DE_ENTREGA"}
