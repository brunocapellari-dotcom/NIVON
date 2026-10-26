"""NIVON MVP: edição read-only, publicada somente por pacote fechado.

Gate duplo: autorização explícita no ambiente de execução + SHA-256
fixado no MESMO ambiente. Ambos são controles de operador, não
substituem licenciamento, revisão independente nem autenticação IAM.
Nenhuma consulta externa, publicação automática ou envio é feito aqui.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .briefing_composto import montar_briefing
from .briefing_diario import ErroBriefing

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BYTES = 1024 * 1024
_MAX_IDADE = timedelta(hours=1)


class ErroReleaseMVP(ValueError):
    pass


def _pairs_no_dup(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ErroReleaseMVP("chave JSON duplicada")
        out[k] = v
    return out


def _instante(value):
    if type(value) is not str or len(value) > 40:
        raise ErroReleaseMVP("timestamp inválido")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroReleaseMVP("timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroReleaseMVP("timestamp precisa de fuso")
    return d.astimezone(timezone.utc)


def preparar_edicao(*, arquivo: str | Path, sha256_aprovado: str,
                   gerado_ate: datetime) -> dict:
    """Retorna somente edição integralmente elegível e imutavelmente fixada.

    A liberação é feita externamente pela configuração da aplicação,
    nunca por flag fornecida dentro do JSON da própria fonte.
    """
    if type(sha256_aprovado) is not str or not _SHA.fullmatch(sha256_aprovado):
        raise ErroReleaseMVP("SHA fixado no ambiente obrigatório")
    if (not isinstance(gerado_ate, datetime) or gerado_ate.tzinfo is None
            or gerado_ate.utcoffset() is None):
        raise ErroReleaseMVP("horário de consulta inválido")
    agora = gerado_ate.astimezone(timezone.utc)
    path = Path(arquivo)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_BYTES:
        raise ErroReleaseMVP("arquivo ausente, simbólico ou excessivo")
    original = path.read_bytes()
    if len(original) > _MAX_BYTES or hashlib.sha256(original).hexdigest() != sha256_aprovado:
        raise ErroReleaseMVP("conteúdo diferente da edição autorizada")
    try:
        payload = json.loads(original.decode("utf-8"), object_pairs_hook=_pairs_no_dup)
    except (UnicodeError, ValueError) as exc:
        raise ErroReleaseMVP("JSON inválido") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "edicao", "gerado_em", "fontes", "noticias", "indicadores", "fretes",
    } or payload["schema"] != "nivon_mvp_edicao_v1":
        raise ErroReleaseMVP("contrato de edição inválido")
    if type(payload["edicao"]) is not str or not re.fullmatch(
        r"[A-Za-z0-9._-]{6,64}", payload["edicao"]
    ):
        raise ErroReleaseMVP("identificação de edição inválida")
    data = _instante(payload["gerado_em"])
    idade = agora - data
    if idade < timedelta(0) or idade > _MAX_IDADE:
        raise ErroReleaseMVP("edição não gerada na última hora")
    fontes = payload["fontes"]
    noticias = payload["noticias"]
    indicadores = payload["indicadores"]
    fretes = payload["fretes"]
    if (not isinstance(fontes, dict) or len(fontes) > 50 or
            not isinstance(noticias, list) or len(noticias) > 80 or
            not isinstance(indicadores, list) or len(indicadores) > 120 or
            not isinstance(fretes, list) or fretes):
        raise ErroReleaseMVP("entradas inválidas ou fretes ainda não habilitados")
    if not noticias and not indicadores:
        raise ErroReleaseMVP("edição vazia não é publicação")
    # Limite inicial deliberado: fretes dependem de transportadora/ponto de
    # embarque/destino, não podem ser publicados como média ou agregado.
    # Os motores de frete seguem isolados até contrato editorial E2E próprio.
    try:
        resumo = montar_briefing(
            noticias=noticias, fontes=fontes, data=payload["gerado_em"],
            indicadores=indicadores, fretes=[],
        )
    except (ErroBriefing, ValueError, KeyError, TypeError) as exc:
        raise ErroReleaseMVP("briefing reprovado pelos contratos existentes") from exc
    if resumo["rejeicoes"]:
        raise ErroReleaseMVP("edição possui registros recusados; reprovar integralmente")
    if resumo["indicadores_incluidos"] != len(indicadores):
        raise ErroReleaseMVP("indicadores não foram integralmente selecionados")
    if resumo["status"] != "PREPARADO_SEM_ENVIO" or not resumo["texto"]:
        raise ErroReleaseMVP("briefing não consolidado")
    return {
        "schema": "nivon_mvp_resposta_v1",
        "edicao": payload["edicao"],
        "gerado_em": data.isoformat(),
        "integridade_sha256": sha256_aprovado,
        "status": "EDICAO_LOCAL_APROVADA_SEM_ENVIO",
        "briefing_texto": resumo["texto"],
        "briefing_sha256": resumo["sha256"],
        "indicadores": indicadores,
        "indicadores_incluidos": len(indicadores),
        "noticias_informadas": len(noticias),
        "fretes_incluidos": 0,
        "registro_canonico_modificado": False,
        "envio_whatsapp_realizado": False,
        "licencas_externas_atestadas_por_este_servico": False,
        "rejeicoes": [],
    }
