"""Adaptador sob demanda para CONAB Progresso Semanal via agrobr (MIT).

NÃO faz coleta no import; nunca considera média dos estados como Brasil.
Dados do agrobr pertencem à fonte CONAB e requerem direitos por operação.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from urllib.parse import urlsplit


class ErroProgresso(ValueError):
    pass


CAMPOS_PERCENTUAIS = (
    "pct_ano_anterior", "pct_semana_anterior",
    "pct_semana_atual", "pct_media_5_anos",
)
OPERACOES = {"Semeadura", "Colheita"}


def _hora(instante: datetime) -> str:
    if not isinstance(instante, datetime) or instante.tzinfo is None:
        raise ErroProgresso("coleta requer relógio com fuso")
    return instante.astimezone(timezone.utc).isoformat()


def _url_conab(url: str) -> str:
    if not isinstance(url, str):
        raise ErroProgresso("URL de evidência obrigatória")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in
            {"www.gov.br", "www.conab.gov.br", "conab.gov.br"} or
            parts.username or parts.password or parts.port not in (None, 443)):
        raise ErroProgresso("evidência deve ser URL HTTPS oficial CONAB")
    return url


def normalizar_progresso(registros, *, fonte_url: str,
                        coletado_em: datetime, publicado_em: str | None = None) -> list[dict]:
    """Normaliza linhas reais ou sintéticas já adquiridas, sem rede.

    Valores são FRAÇÕES de 0 a 1; publicação não é inferida da semana.
    """
    _url_conab(fonte_url)
    coleta = _hora(coletado_em)
    if publicado_em is not None:
        try:
            pub = datetime.fromisoformat(publicado_em.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ErroProgresso("publicação inválida") from exc
        if pub.tzinfo is None or pub.astimezone(timezone.utc) > coletado_em.astimezone(timezone.utc):
            raise ErroProgresso("publicação futura ou sem fuso")
    if hasattr(registros, "to_dict"):
        registros = registros.to_dict(orient="records")
    if not isinstance(registros, (list, tuple)) or not registros:
        raise ErroProgresso("planilha sem registros")
    saida = []
    chaves = set()
    for r in registros:
        if not isinstance(r, dict):
            raise ErroProgresso("linha inválida")
        cultura, safra, op, uf, semana = (
            str(r.get(k) or "").strip()
            for k in ("cultura", "safra", "operacao", "uf", "semana_atual")
        )
        if not cultura or not safra or op not in OPERACOES:
            raise ErroProgresso("cultura/safra/operação inválida")
        if uf != "MEDIA_ESTADOS" and (len(uf) != 2 or not uf.isalpha() or uf != uf.upper()):
            raise ErroProgresso("UF inválida ou Brasil inferido")
        try:
            datetime.strptime(semana, "%Y-%m-%d")
        except ValueError as exc:
            raise ErroProgresso("semana inválida") from exc
        chave = (cultura, safra, op, uf, semana)
        if chave in chaves:
            raise ErroProgresso("semana/cultura/UF duplicada")
        chaves.add(chave)
        nums = {}
        for k in CAMPOS_PERCENTUAIS:
            v = r.get(k)
            if v is not None:
                try:
                    v = float(v)
                except (ValueError, TypeError) as exc:
                    raise ErroProgresso(k + " não numérico") from exc
                if not 0 <= v <= 1:
                    raise ErroProgresso(k + " deve ser fração [0,1]")
            nums[k] = v
        if not any(v is not None for v in nums.values()):
            raise ErroProgresso("linha sem percentuais")
        cobertura = r.get("cobertura_area_pct")
        if cobertura is not None and not 0 <= float(cobertura) <= 1:
            raise ErroProgresso("cobertura fora da fração")
        saida.append({
            "source_id": "CONAB", "dataset_id": "CONAB_PROGRESSO_SEMANAL",
            "cultura": cultura, "safra": safra, "operacao": op, "uf": uf,
            "competencia": semana, "referencia": semana,
            "publicacao": publicado_em, "coleta": coleta,
            "source_url": fonte_url, "observational_kind": "INFORMADO",
            "revisado": r.get("revisado"),
            "n_estados": r.get("n_estados") if uf == "MEDIA_ESTADOS" else None,
            "cobertura_area_pct": cobertura if uf == "MEDIA_ESTADOS" else None,
            **nums,
        })
    return saida


async def coletar_progresso(*, semana_url: str | None = None,
                             direitos_confirmados: bool = False,
                             capturado_em: datetime | None = None,
                             agrobr_api=None) -> list[dict]:
    """Aquisição real só com autorização EXPLÍCITA externa e proveniência."""
    if direitos_confirmados is not True:
        raise PermissionError("CONAB: consulta/coleta/armazenamento não homologados")
    if semana_url is not None:
        _url_conab(semana_url)
    api = agrobr_api
    if api is None:
        try:
            api = import_module("agrobr").conab
        except ImportError as exc:
            raise RuntimeError("Instale o extra NIVON[agro] para coletar") from exc
    linhas, meta = await api.progresso_safra(
        semana_url=semana_url, return_meta=True,
    )
    # O endereço do arquivo pode vir no metadado do pacote; nunca inventar.
    origem = getattr(meta, "source_url", None) or semana_url
    if not origem:
        raise ErroProgresso("agrobr sem URL de origem comprovável")
    return normalizar_progresso(
        linhas, fonte_url=origem,
        coletado_em=capturado_em or datetime.now(timezone.utc),
        publicado_em=None,
    )


async def descobrir_semanas(*, direitos_confirmados: bool = False,
                            max_pages: int = 4, agrobr_api=None) -> list[dict]:
    if direitos_confirmados is not True:
        raise PermissionError("CONAB: descoberta não autorizada")
    if not isinstance(max_pages,int) or not 1 <= max_pages <= 260:
        raise ErroProgresso("limite de páginas inválido")
    if agrobr_api is None:
        try:
            agrobr_api = import_module("agrobr").conab
        except ImportError as exc:
            raise RuntimeError("Instale NIVON[agro]") from exc
    semanas = await agrobr_api.semanas_disponiveis(max_pages=max_pages)
    if not isinstance(semanas, list):
        raise ErroProgresso("resposta inesperada")
    for entrada in semanas:
        _url_conab(entrada.get("url"))
    return semanas
