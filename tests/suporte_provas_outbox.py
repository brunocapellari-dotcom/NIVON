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


# Chave de testes, fora de qualquer serviço ou configuração real.
RAIZ_SINTETICA = b"raiz_administrativa_ficticia_nivon_20261022_mais_de_32_bytes"


def manifesto_teste(emissores: dict) -> dict:
    return {
        "operacao": "PROVISIONAR", "versao": 1,
        "emissores": sorted((
            {"emissor_id": nome, "tipo": info["tipo"],
             "key_fingerprint": hashlib.sha256(info["chave"]).hexdigest()}
            for nome, info in emissores.items()
        ), key=lambda x: x["tipo"])
    }


def assinatura_administrativa(obj: dict) -> str:
    import json
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    return "sha256=" + hmac.new(RAIZ_SINTETICA, raw, hashlib.sha256).hexdigest()


def provisionar_teste(con, emissores: dict) -> None:
    from nivon.registry_emissores import provisionar_registro, resumo_registry
    if resumo_registry(con)["provisionado"]:
        return
    m = manifesto_teste(emissores)
    provisionar_registro(
        con, manifesto=m, assinatura=assinatura_administrativa(m),
        chave_raiz=RAIZ_SINTETICA,
    )
