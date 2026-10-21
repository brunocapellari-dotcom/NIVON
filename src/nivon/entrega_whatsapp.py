"""Canal WhatsApp Cloud API isolado do NIVON e do projeto WhatsApp AI.

Gera payload de template APROVADO, com opt-in demonstrado. Sem envio implícito.
O texto longo completo precisa ser disponibilizado em URL autorizada; template
não é licença para envio de mensagens livres fora da janela de atendimento.
"""
from __future__ import annotations

import hashlib
import re

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
                     permitir_cobranca_e_envio: bool = False, abridor=None) -> dict:
    """Caminho de rede legado desativado até integração com outbox durável.

    O parâmetro de envio é insuficiente para provar reserva de uma única
    tentativa, revisão da edição, direitos de uso, consentimento e orçamento.
    Somente um adaptador futuro sob despachar_registrado poderá executar POST,
    após auditoria e homologação específicas. Nenhuma rede é chamada aqui.
    """
    if not permitir_cobranca_e_envio:
        raise PermissionError("envio bloqueado por padrão; requer autorização comercial")
    raise PermissionError("envio Cloud API direto sem outbox transacional é proibido")
