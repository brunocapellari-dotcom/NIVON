"""Catálogo OFFLINE de páginas de levantamentos CONAB, NÃO de dados da safra.

Metadados publicados pelo portal podem ter sido alterados depois do corte.
Nenhum URL, carimbo ou HTML presente é prova independente de vintage anterior.
A função não acessa rede, não abre planilhas e não fornece números agrícolas.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit


class ErroCatalogoLevantamentosConab(ValueError):
    pass


_CAMPOS = frozenset({
    "fonte_id", "safra", "numero_levantamento", "pagina_url",
    "publicado_portal_em", "atualizado_portal_em", "inspecionado_dia",
})
_SAFRA = re.compile(r"(20\d{2})/(\d{2})\Z")
_RAIZ = ("/conab/pt-br/atuacao/informacoes-agropecuarias/safras/"
         "safra-de-graos/boletim-da-safra-de-graos/")


def _instante(valor: object, rotulo: str) -> datetime:
    if not isinstance(valor, str) or "T" not in valor:
        raise ErroCatalogoLevantamentosConab(rotulo + ": ISO com fuso obrigatório")
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroCatalogoLevantamentosConab(rotulo + ": carimbo inválido") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroCatalogoLevantamentosConab(rotulo + ": fuso ausente")
    return instante.astimezone(timezone.utc)


def _validar_linha(linha: dict) -> dict:
    if not isinstance(linha, dict) or set(linha) != _CAMPOS:
        raise ErroCatalogoLevantamentosConab("campos de candidato inconsistentes")
    if linha["fonte_id"] != "CONAB":
        raise ErroCatalogoLevantamentosConab("candidato não tem origem CONAB")
    m = _SAFRA.fullmatch(linha["safra"]) if isinstance(linha["safra"], str) else None
    if not m or (int(m[1]) + 1) % 100 != int(m[2]):
        raise ErroCatalogoLevantamentosConab("safra comercial inválida")
    n = linha["numero_levantamento"]
    if type(n) is not int or not 1 <= n <= 12:
        raise ErroCatalogoLevantamentosConab("número de levantamento fora do contrato")
    url = linha["pagina_url"]
    if not isinstance(url, str):
        raise ErroCatalogoLevantamentosConab("URL oficial ausente")
    p = urlsplit(url)
    suffix = p.path.removeprefix(_RAIZ)
    y = m[1]
    y2 = str(int(y) + 1)
    short = y2[-2:]
    slugs = (f"{n}o-levantamento-safra-{y}-{short}",
             f"{n}o-levantamento-safra-{y}-{y2}")
    if (p.scheme != "https" or p.netloc != "www.gov.br" or
            not p.path.startswith(_RAIZ) or suffix not in slugs or
            p.query or p.fragment or p.username or p.password):
        raise ErroCatalogoLevantamentosConab("URL não é página de levantamento compatível")
    pub = _instante(linha["publicado_portal_em"], "publicado_portal_em")
    mod = _instante(linha["atualizado_portal_em"], "atualizado_portal_em")
    try:
        dia = date.fromisoformat(linha["inspecionado_dia"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", linha["inspecionado_dia"]):
            raise ValueError("data precisa")
    except (ValueError, TypeError) as exc:
        raise ErroCatalogoLevantamentosConab("dia da leitura do portal inválido") from exc
    # Limite superior generoso: metadado declarado na data de consulta,
    # jamais ler alterações posteriores a um dia de captura alegado.
    fim = datetime.combine(dia, time.max, tzinfo=timezone.utc)
    if max(pub, mod) > fim:
        raise ErroCatalogoLevantamentosConab(
            "carimbos do portal posteriores ao dia declarado de consulta"
        )
    return {"linha": dict(linha), "publicado": pub, "modificado": mod}


def auditar_candidatos_levantamentos_conab(
    *, registros: list[dict], instante_decisao: str,
) -> dict:
    """Inventário de candidatos oficiais, sem declarar dado disponível as-of.

    Se atualizado_portal_em for posterior ao corte, a página atual é ainda
    menos apropriada como evidência do documento visto naquele passado.
    Mesmo sem alteração posterior conhecida, não afirmar RAW/vintage original.
    """
    corte = _instante(instante_decisao, "instante_decisao")
    if not isinstance(registros, list) or not 1 <= len(registros) <= 150:
        raise ErroCatalogoLevantamentosConab("quantidade de candidatos inválida")
    vistos = set()
    candidatos = []
    for linha in registros:
        d = _validar_linha(linha)
        key = (linha["safra"], linha["numero_levantamento"])
        if key in vistos:
            raise ErroCatalogoLevantamentosConab("edição de levantamento duplicada")
        vistos.add(key)
        pub, mod = d["publicado"], d["modificado"]
        if pub > corte:
            estado = "PUBLICACAO_PORTAL_POSTERIOR_AO_CORTE"
        elif mod > corte:
            estado = "PAGINA_PORTAL_MODIFICADA_APOS_CORTE"
        else:
            estado = "SOMENTE_METADADOS_ATUAIS_SEM_RAW_HISTORICO"
        candidatos.append({
            **d["linha"],
            "estado_no_corte": estado,
            "revisao_portal_posterior_publicacao": mod > pub,
            "publicado_utc": pub.isoformat(),
            "modificado_utc": mod.isoformat(),
            "prova_raw_sha256": None,
            "disponibilidade_historica_verificada": False,
            "pode_extrair_numero_historico": False,
            "habilita_backtest": False,
            "habilita_treino": False,
            "habilita_publicacao": False,
        })
    candidatos.sort(key=lambda x: (x["safra"], x["numero_levantamento"]))
    canonical = json.dumps(
        registros, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {
        "estado": "INVENTARIO_CANDIDATOS_COM_METADADOS_DO_PORTAL",
        "fonte_id": "CONAB",
        "cutoff_utc": corte.isoformat(),
        "sha256_catalogo_curado_nao_raw": sha256(canonical).hexdigest(),
        "total": len(candidatos), "candidatos": candidatos,
        "evidencia_raw_confirmada": False,
        "disponibilidade_historica_comprovada": False,
        "habilita_backtest": False, "habilita_treino": False,
        "habilita_publicacao": False,
        "nota": ("A data de publicação do portal não autentica os bytes da edição "
                 "passada; atualização posterior invalida o uso da página atual "
                 "como retrato daquele corte."),
    }
