"""Comprovantes 100% sintéticos de cinco emissores para testes.

Nunca usar chaves ou IDs deste módulo em ambiente real.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from nivon.provas_externas_envio import TIPOS, canonicalizar_prova


def provas_sinteticas(documento: dict) -> tuple[list[dict], dict]:
    now = datetime.now(timezone.utc)
    expira = min(
        datetime.fromisoformat(documento["valido_ate"]),
        now + timedelta(minutes=45)
    )
    emissores = {}
    provas = []
    for tipo, campo in TIPOS.items():
        emissor = f"EMISSOR_{tipo}_SINTETICO"
        chave = ("chave_independente_de_teste_" + tipo + "_20261021").encode()
        emissores[emissor] = {"tipo": tipo, "chave": chave, "ativo": True}
        prova = {
            "tipo": tipo,
            "evidencia_id": documento[campo],
            "emissor_id": emissor,
            "edicao": documento["edicao"],
            "idempotency_key": documento["idempotency_key"],
            "sha256_editorial": documento["sha256_editorial"],
            "destinatario_hmac": documento["destinatario_hmac"],
            "payload_sha256": documento["payload_sha256"],
            "emitido_em": (now - timedelta(seconds=30)).isoformat(),
            "valido_ate": expira.isoformat(),
            "estado": "APROVADA",
        }
        prova["assinatura"] = "sha256=" + hmac.new(
            chave, canonicalizar_prova(prova), hashlib.sha256).hexdigest()
        provas.append(prova)
    return provas, emissores
