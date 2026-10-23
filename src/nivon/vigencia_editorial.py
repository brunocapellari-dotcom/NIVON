"""Validade temporal por edição, vinculada às notícias do preflight.

Edições históricas podem ser auditadas/registradas offline, mas somente
uma edição ainda vigente pode reservar despacho. A fonte da hora de
despacho é o relógio do processo, não o pacote recebido.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone


class ErroVigenciaEditorial(ValueError):
    pass


def _instante(valor: object) -> datetime:
    if not isinstance(valor, str) or "T" not in valor:
        raise ErroVigenciaEditorial("timestamp editorial com hora e fuso obrigatório")
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroVigenciaEditorial("timestamp editorial inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroVigenciaEditorial("timestamp editorial sem fuso")
    return d.astimezone(timezone.utc)


def calcular_vigencia_editorial(gerado_em: str, noticias: list[dict],
                              sha256_editorial: str) -> dict:
    """Calcula limite estrito de 24h desde a publicação MAIS ANTIGA.

    Também limita vigência a 24h desde a geração; notícia sem publicação
    original identificada, futuro e lacuna de notícia bloqueiam a operação.
    Um preflight independente deve ter validado a identidade das matérias.
    """
    gerado = _instante(gerado_em)
    if not isinstance(sha256_editorial, str) or len(sha256_editorial) != 64 or any(
            c not in "0123456789abcdef" for c in sha256_editorial):
        raise ErroVigenciaEditorial("SHA editorial inválido")
    if not isinstance(noticias, list) or not noticias:
        raise ErroVigenciaEditorial("edição sem notícia comprovada")
    instantes = []
    identidades = []
    for noticia in noticias:
        if not isinstance(noticia, dict):
            raise ErroVigenciaEditorial("notícia não estruturada")
        publicado = _instante(noticia.get("publicado_em"))
        if publicado > gerado or gerado - publicado > timedelta(hours=24):
            raise ErroVigenciaEditorial("notícia futura ou vencida na geração")
        fonte, url = noticia.get("fonte_id"), noticia.get("url")
        if not isinstance(fonte, str) or not fonte or not isinstance(url, str) or not url:
            raise ErroVigenciaEditorial("identidade da notícia incompleta")
        instantes.append(publicado)
        identidades.append((fonte, url, publicado.isoformat()))
    mais_antiga = min(instantes)
    valido_ate = min(mais_antiga + timedelta(hours=24), gerado + timedelta(hours=24))
    sha_noticias = hashlib.sha256(json.dumps(
        sorted(identidades), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {
        "gerado_em_utc": gerado.isoformat(),
        "noticia_mais_antiga_utc": mais_antiga.isoformat(),
        "valido_ate_utc": valido_ate.isoformat(),
        "sha256_editorial": sha256_editorial,
        "sha256_noticias": sha_noticias,
    }


def validar_reserva_editorial(vigencia: dict, *, gerado_em: str,
                             sha256_editorial: str, agora: datetime) -> None:
    """Exige edição vigente sob relógio da reserva e metadados imutáveis."""
    if not isinstance(vigencia, dict) or not vigencia:
        raise PermissionError("vigência editorial ausente: não reservar envio")
    if agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroVigenciaEditorial("relógio da reserva sem fuso")
    gerado = _instante(gerado_em)
    registrado = _instante(vigencia.get("gerado_em_utc"))
    limite = _instante(vigencia.get("valido_ate_utc"))
    noticia = _instante(vigencia.get("noticia_mais_antiga_utc"))
    if (gerado != registrado or vigencia.get("sha256_editorial") != sha256_editorial
            or not isinstance(vigencia.get("sha256_noticias"), str)
            or len(vigencia["sha256_noticias"]) != 64):
        raise PermissionError("vigência não vinculada ao SHA ou geração da edição")
    if limite > min(gerado + timedelta(hours=24), noticia + timedelta(hours=24)):
        raise PermissionError("vigência editorial ampliada indevidamente")
    instante = agora.astimezone(timezone.utc)
    if not gerado <= instante < limite:
        raise PermissionError("edição futura ou vencida para a reserva de envio")
