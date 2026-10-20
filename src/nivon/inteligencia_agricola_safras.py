"""Baseline agrícola point-in-time por cultura, produto e safra comercial.

Estimativa condicional da produção AINDA NÃO COLHIDA, sem treino, rede
ou qualificação como previsão probabilística. Quantis históricos são cenários,
NÃO intervalos de confiança nem probabilidades calibradas.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re


class ErroCenarioSafra(ValueError):
    """Violação de unidade, produto, tempo ou balanço agrícola."""


# Domínios distintos impedem somar milho TOTAL com 1ª/2ª/3ª safra,
# confundir algodão em caroço e pluma e usar cana plantada como área colhível.
SEGMENTOS = {
    "SOJA": frozenset({"SOJA"}),
    "MILHO": frozenset({"MILHO_1", "MILHO_2", "MILHO_3", "MILHO_TOTAL"}),
    "ALGODAO": frozenset({"ALGODAO"}),
    "TRIGO": frozenset({"TRIGO"}),
    "SORGO": frozenset({"SORGO"}),
    "CANA": frozenset({"CANA"}),
    "GERGELIM": frozenset({"GERGELIM"}),
}
PRODUTOS = {
    "SOJA": frozenset({"SOJA_GRAO"}),
    "MILHO": frozenset({"MILHO_GRAO"}),
    "ALGODAO": frozenset({"ALGODAO_EM_CAROCO", "ALGODAO_PLUMA"}),
    "TRIGO": frozenset({"TRIGO_GRAO"}),
    "SORGO": frozenset({"SORGO_GRAO"}),
    "CANA": frozenset({"CANA_COLMOS"}),
    "GERGELIM": frozenset({"GERGELIM_SEMENTE"}),
}
# Limites de triagem (não tetos biológicos ou parâmetros agronômicos calibrados).
LIMITES_TRIAGEM_KG_HA = {
    "SOJA": Decimal("12000"), "MILHO": Decimal("25000"),
    "ALGODAO": Decimal("20000"), "TRIGO": Decimal("14000"),
    "SORGO": Decimal("20000"), "CANA": Decimal("250000"),
    "GERGELIM": Decimal("10000"),
}
_UFS = frozenset({11,12,13,14,15,16,17,21,22,23,24,25,26,27,28,29,
                 31,32,33,35,41,42,43,50,51,52,53})
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_HIST_CAMPOS = frozenset({
    "ano_safra", "cultura", "segmento", "produto_fisico", "regiao_ibge",
    "competencia", "data_referencia", "area_colhida_ha", "producao_t",
    "publicado_em", "disponivel_em", "coletado_em",
    "fonte_id", "edicao_id", "raw_sha256",
})


def _instante(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ErroCenarioSafra(field + ": timestamp ISO com fuso obrigatório")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroCenarioSafra(field + ": data inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroCenarioSafra(field + ": fuso obrigatório")
    return dt.astimezone(timezone.utc)


def _decimal(value, field: str, *, positivo: bool = False) -> Decimal:
    if type(value) not in (str, int, float, Decimal):
        raise ErroCenarioSafra(field + ": decimal obrigatório (bool proibido)")
    try:
        v = Decimal(str(value))
    except InvalidOperation as exc:
        raise ErroCenarioSafra(field + ": valor inválido") from exc
    if not v.is_finite() or v < 0 or (positivo and v == 0) or v > Decimal("1e14"):
        raise ErroCenarioSafra(field + ": fora do domínio")
    return v


def _prova(row: dict, cutoff: datetime) -> bool:
    for key in ("fonte_id", "edicao_id"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ErroCenarioSafra(key + ": fonte/edição obrigatória")
    h = row.get("raw_sha256")
    if not isinstance(h, str) or not _SHA.fullmatch(h):
        raise ErroCenarioSafra("raw_sha256 ausente ou inválido")
    comp = row.get("competencia")
    if not isinstance(comp, str) or not re.fullmatch(r"20[0-9]{2}(?:/[0-9]{2})?", comp):
        raise ErroCenarioSafra("competencia: safra comercial inválida")
    raw_ref = row.get("data_referencia")
    if not isinstance(raw_ref, str):
        raise ErroCenarioSafra("data_referencia: data ISO obrigatória")
    try:
        ref = date.fromisoformat(raw_ref)
    except ValueError as exc:
        raise ErroCenarioSafra("data_referencia: data inválida") from exc
    p = _instante(row.get("publicado_em"), "publicado_em")
    d = _instante(row.get("disponivel_em"), "disponivel_em")
    c = _instante(row.get("coletado_em"), "coletado_em")
    if ref > datetime.fromisoformat(row["publicado_em"].replace("Z", "+00:00")).date():
        raise ErroCenarioSafra("referência posterior à publicação")
    if not p <= d <= c:
        raise ErroCenarioSafra("publicação/disponibilidade/coleta cronologicamente inconsistentes")
    return c <= cutoff


def _rend(area_ha: Decimal, toneladas: Decimal, cultura: str) -> Decimal | None:
    if area_ha == 0:
        if toneladas != 0:
            raise ErroCenarioSafra("produção positiva com área colhida zero")
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        valor = toneladas * 1000 / area_ha
    if valor > LIMITES_TRIAGEM_KG_HA[cultura]:
        raise ErroCenarioSafra("rendimento acima do limite de triagem: revisão manual")
    return valor


def _quantil(vs: list[Decimal], p: Decimal) -> Decimal:
    """Interpolação linear (método tipo 7) sobre amostra histórica; NÃO IC."""
    n = len(vs)
    h = Decimal(n - 1) * p
    i = int(h)
    j = min(i + 1, n - 1)
    return vs[i] + (vs[j] - vs[i]) * (h - i)


def estimar_oferta_remanescente(
    *, cultura: str, segmento: str, produto_fisico: str, regiao_ibge: str,
    ano_safra: int, emitido_em: str, observacao_atual: dict,
    historico: list[dict], minimo_anos: int = 5,
) -> dict:
    """Cenários Q10/Q50/Q90 de rendimento histórico para área ainda por colher.

    observacao_atual: identidade da cultura/segmento/produto/região + area_alvo_colheita_ha (projeção de área final),
      area_colhida_ha, producao_colhida_t + metadados de proveniência.
    historico: mesmas chaves canônicas; uma observação por safra ANTERIOR do mesmo segmento/produto/região,
      com area_colhida_ha, producao_t e metadados de publicação/captura.
    Nenhum valor pode ser tratado como predição validada ou volume realizado.
    """
    if cultura not in SEGMENTOS or segmento not in SEGMENTOS[cultura] or produto_fisico not in PRODUTOS[cultura]:
        raise ErroCenarioSafra("cultura/segmento/produto físico incompatíveis")
    if (not isinstance(regiao_ibge, str) or
        not re.fullmatch(r"[0-9]{2}(?:[0-9]{5})?", regiao_ibge) or
        int(regiao_ibge[:2]) not in _UFS):
        raise ErroCenarioSafra("região exige código IBGE UF ou município")
    if type(ano_safra) is not int or not 1970 <= ano_safra <= 2100:
        raise ErroCenarioSafra("ano_safra inválido")
    if type(minimo_anos) is not int or not 5 <= minimo_anos <= 30:
        raise ErroCenarioSafra("mínimo histórico exige 5 a 30 safras")
    corte = _instante(emitido_em, "emitido_em")
    if not isinstance(observacao_atual, dict) or not isinstance(historico, list):
        raise ErroCenarioSafra("observação e histórico obrigatórios")
    atuais = frozenset({"cultura", "segmento", "produto_fisico", "regiao_ibge",
                       "competencia", "data_referencia",
                       "area_alvo_colheita_ha", "area_colhida_ha", "producao_colhida_t",
                       "publicado_em", "disponivel_em", "coletado_em", "fonte_id",
                       "edicao_id", "raw_sha256"})
    if set(observacao_atual) != atuais:
        raise ErroCenarioSafra("contrato de observação atual incompleto ou alterado")
    ids = (cultura, segmento, produto_fisico, regiao_ibge)
    if tuple(observacao_atual[k] for k in ("cultura", "segmento", "produto_fisico", "regiao_ibge")) != ids:
        raise ErroCenarioSafra("identidade de cultura/safra/produto/região atual divergente")
    if not observacao_atual["competencia"].startswith(str(ano_safra)):
        raise ErroCenarioSafra("competência atual divergente da safra")
    if not _prova(observacao_atual, corte):
        raise ErroCenarioSafra("observação atual ainda indisponível no cutoff")
    area_alvo = _decimal(observacao_atual["area_alvo_colheita_ha"], "area_alvo_colheita_ha", positivo=True)
    colhida = _decimal(observacao_atual["area_colhida_ha"], "area_colhida_ha")
    realizado = _decimal(observacao_atual["producao_colhida_t"], "producao_colhida_t")
    if colhida > area_alvo:
        raise ErroCenarioSafra("área colhida superior à área alvo de colheita")
    rendimento_atual = _rend(colhida, realizado, cultura)
    if not isinstance(historico, list) or len(historico) > 300:
        raise ErroCenarioSafra("histórico inválido ou excessivo")
    vistos = set()
    candidatos = []
    excluidos = []
    for row in historico:
        if not isinstance(row, dict) or set(row) != _HIST_CAMPOS:
            raise ErroCenarioSafra("contrato histórico incompleto ou alterado")
        if tuple(row[k] for k in ("cultura", "segmento", "produto_fisico", "regiao_ibge")) != ids:
            raise ErroCenarioSafra("mistura histórica de cultura, safra, produto físico ou região")
        y = row["ano_safra"]
        if type(y) is not int or not 1970 <= y < ano_safra or y in vistos:
            raise ErroCenarioSafra("safra futura, duplicada ou inválida")
        vistos.add(y)
        elegivel = _prova(row, corte)
        # Validar também dados não elegíveis para não tolerar conteúdos malformados.
        area = _decimal(row["area_colhida_ha"], "area_colhida_ha")
        ton = _decimal(row["producao_t"], "producao_t")
        rendimento = _rend(area, ton, cultura)
        if not elegivel:
            excluidos.append(y)
        elif rendimento is None:
            excluidos.append(y)
        else:
            candidatos.append((y, rendimento))
    if len(candidatos) < minimo_anos:
        return {
            "estado": "HISTORICO_ASOF_INSUFICIENTE",
            "cultura": cultura, "segmento": segmento, "produto_fisico": produto_fisico,
            "regiao_ibge": regiao_ibge, "ano_safra": ano_safra,
            "safras_elegiveis": len(candidatos), "minimo_exigido": minimo_anos,
            "safras_excluidas": sorted(excluidos), "cenarios": None,
            "habilita_previsao": False, "habilita_publicacao": False,
        }
    with localcontext() as ctx:
        ctx.prec = 40
        restante = area_alvo - colhida
        rendimentos = sorted(r for _, r in candidatos)
        cenarios = {}
        for nome, fracao in (("Q10", Decimal("0.1")), ("Q50", Decimal("0.5")),
                             ("Q90", Decimal("0.9"))):
            kg_ha = _quantil(rendimentos, fracao)
            total = realizado + restante * kg_ha / Decimal(1000)
            cenarios[nome] = {
                "rendimento_area_remanescente_kg_ha": str(kg_ha),
                "producao_final_condicional_t": str(total),
                "producao_ainda_nao_colhida_cenario_t": str(total - realizado),
            }
        return {
            "estado": "BASELINE_HISTORICO_CONDICIONAL_NAO_CALIBRADO",
            "cultura": cultura, "segmento": segmento, "produto_fisico": produto_fisico,
            "regiao_ibge": regiao_ibge, "ano_safra": ano_safra,
            "cutoff": corte.isoformat(), "origem_atual_sha256": observacao_atual["raw_sha256"],
            "safras_elegiveis": len(candidatos), "anos_treinamento": sorted(y for y, _ in candidatos),
            "safras_excluidas": sorted(excluidos), "area_alvo_colheita_ha": str(area_alvo),
            "area_colhida_ha": str(colhida), "area_remanescente_ha": str(restante),
            "producao_colhida_t": str(realizado),
            "rendimento_area_colhida_kg_ha": None if rendimento_atual is None else str(rendimento_atual),
            "cenarios": cenarios, "metodo": "QUANTIS_EMPIRICOS_HISTORICOS_TIPO7",
            "limitacoes": [
                "Quantis de rendimento NÃO são probabilidades calibradas nem intervalos preditivos.",
                "Área alvo de colheita é hipótese; NÃO equivale à área plantada.",
                "Não há ajuste para seletividade de talhões colhidos, clima, solo ou fenologia.",
                "Sem prova externa de vintage, licença e qualidade dos RAW, proibida publicação.",
            ],
            "habilita_previsao": False, "habilita_publicacao": False,
        }
