"""Auditoria OFFLINE de comparabilidade CONAB séries históricas versus IBGE PAM.

A fonte CONAB inclui estimativas/revisões de safras comerciais; a PAM é
estatística anual municipal. Produção comparável NÃO torna estimativas iguais,
nem prova vintages point-in-time; CONAB AREA não vira área colhida IBGE.
Nenhuma saída autoriza treino, publicação ou predição.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re

from .conab_series import ARQUIVOS
from .agregacao_pam_ibge import C81_PAM_POR_CULTURA, _PRODUTOS, _UFS


class ErroConciliacaoSafra(ValueError):
    pass


# Codificação oficial de todas as UFs brasileiras; comparar contra o dicionário
# municipal da PAM impede que um mapeamento parcial produza falsa equivalência.
UF_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15",
    "AP": "16", "TO": "17", "MA": "21", "PI": "22", "CE": "23",
    "RN": "24", "PB": "25", "PE": "26", "AL": "27", "SE": "28",
    "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35",
    "PR": "41", "SC": "42", "RS": "43", "MS": "50", "MT": "51",
    "GO": "52", "DF": "53",
}
if {int(x) for x in UF_IBGE.values()} != _UFS or len(UF_IBGE) != len(_UFS):
    raise RuntimeError("mapa de UFs da CONAB diverge do contrato IBGE PAM")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SAFRA = re.compile(r"((?:19|20)[0-9]{2})/((?:19|20)[0-9]{2})\Z")
_CONAB_CLASSES = {"PROJETADO_CONAB", "INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO"}
# Nomes de produtos e códigos C81 sempre vêm do adaptador canônico SIDRA,
# nunca de mapeamentos mantidos em paralelo.
_PAM_MAP = {cultura: _PRODUTOS[cultura] for cultura in ("SOJA", "MILHO")}
_IDENTIDADES = {("SOJA", "TOTAL"), ("MILHO", "TOTAL"),
                ("MILHO", "PRIMEIRA"), ("MILHO", "SEGUNDA"), ("MILHO", "TERCEIRA")}


def _numero(value: object, field: str, *, zero: bool = True) -> Decimal:
    if type(value) not in (int, str, float, Decimal):
        raise ErroConciliacaoSafra(field + ": número inválido")
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise ErroConciliacaoSafra(field + ": número inválido") from exc
    if not d.is_finite() or d < 0 or (not zero and d == 0) or d > Decimal("1e15"):
        raise ErroConciliacaoSafra(field + ": fora do domínio")
    return d


def _instante(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ErroConciliacaoSafra(field + ": timestamp com fuso obrigatório")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroConciliacaoSafra(field + ": timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroConciliacaoSafra(field + ": sem fuso")
    return d.astimezone(timezone.utc)


def _prova_temporal(meta: dict, cutoff: datetime) -> bool:
    """Prova DECLARADA no payload, sem presumir verificação independente."""
    campos = {"fonte_id", "edicao_id", "raw_sha256", "publicado_em",
              "disponivel_em", "coletado_em", "prova_disponibilidade_sha256",
              "disponibilidade_verificada"}
    if not isinstance(meta, dict) or set(meta) != campos:
        raise ErroConciliacaoSafra("metadados temporais incompletos")
    for key in ("fonte_id", "edicao_id"):
        if not isinstance(meta[key], str) or not meta[key].strip():
            raise ErroConciliacaoSafra(key + ": ID obrigatório")
    for key in ("raw_sha256", "prova_disponibilidade_sha256"):
        value = meta[key]
        if value is not None and (not isinstance(value, str) or not _HASH.fullmatch(value)):
            raise ErroConciliacaoSafra(key + ": hash inválido")
    if meta["raw_sha256"] is None:
        raise ErroConciliacaoSafra("raw_sha256 obrigatório")
    if type(meta["disponibilidade_verificada"]) is not bool:
        raise ErroConciliacaoSafra("disponibilidade_verificada exige booleano")
    p = _instante(meta["publicado_em"], "publicado_em")
    d = _instante(meta["disponivel_em"], "disponivel_em")
    c = _instante(meta["coletado_em"], "coletado_em")
    if not p <= d <= c:
        raise ErroConciliacaoSafra("ordem de publicação/disponibilidade/coleta inválida")
    if meta["disponibilidade_verificada"] and not meta["prova_disponibilidade_sha256"]:
        raise ErroConciliacaoSafra("prova temporal marcada verificada sem hash")
    if not meta["disponibilidade_verificada"] and meta["prova_disponibilidade_sha256"] is not None:
        raise ErroConciliacaoSafra("hash de prova sem verificação declarada")
    return c <= cutoff and meta["disponibilidade_verificada"]


def preparar_tripla_conab(*, linhas: list[dict], uf: str, cultura: str,
                          subdivisao: str, safra: str, snapshot_meta: dict,
                          emitido_em: str) -> dict:
    """Normalização da tripla AREA, PRODUTIVIDADE e PRODUCAO já coletada.

    Entrada vem do conab_series.normalizar_livro e tem unidade canônica;
    NÃO transforma AREA declarada da CONAB em AREA_COLHIDA observada.
    """
    cutoff = _instante(emitido_em, "emitido_em")
    if (cultura, subdivisao) not in _IDENTIDADES:
        raise ErroConciliacaoSafra("cultura ou safra incompatível")
    if uf not in UF_IBGE:
        raise ErroConciliacaoSafra("UF fora do adaptador explícito")
    sm = _SAFRA.fullmatch(safra) if isinstance(safra, str) else None
    if not sm or int(sm[2]) != int(sm[1]) + 1:
        raise ErroConciliacaoSafra("safra comercial inválida")
    if not isinstance(linhas, list) or len(linhas) != 3:
        raise ErroConciliacaoSafra("CONAB exige exatamente três indicadores")
    if not isinstance(snapshot_meta, dict) or snapshot_meta.get("fonte_id") != "CONAB":
        raise ErroConciliacaoSafra("origem CONAB incompatível")
    elegivel = _prova_temporal(snapshot_meta, cutoff)
    esperado = {"AREA": "HA", "PRODUTIVIDADE": "KG_HA", "PRODUCAO": "T"}
    vistos, valores, classes, arquivo = set(), {}, set(), None
    for row in linhas:
        if not isinstance(row, dict):
            raise ErroConciliacaoSafra("linha de indicador não é objeto")
        indicador = row.get("indicador")
        if indicador not in esperado or indicador in vistos:
            raise ErroConciliacaoSafra("indicador CONAB duplicado ou desconhecido")
        vistos.add(indicador)
        if any((row.get("produto") != cultura,
                row.get("subdivisao_safra") != subdivisao,
                row.get("regiao_uf") != uf, row.get("safra") != safra,
                row.get("fonte") != "CONAB",
                row.get("unidade") != esperado[indicador],
                row.get("origem_sha256") != snapshot_meta["raw_sha256"])):
            raise ErroConciliacaoSafra("mistura de safra, UF, fonte, unidade ou RAW")
        nome = row.get("arquivo")
        if nome not in ARQUIVOS or ARQUIVOS[nome] != (cultura, subdivisao):
            raise ErroConciliacaoSafra("arquivo CONAB incompatível com a cultura")
        if arquivo is None:
            arquivo = nome
        elif arquivo != nome:
            raise ErroConciliacaoSafra("indicadores oriundos de arquivos distintos")
        if _instante(row.get("coletado_em"), "linha.coletado_em") != _instante(
                snapshot_meta["coletado_em"], "coletado_em"):
            raise ErroConciliacaoSafra("linha CONAB não corresponde à coleta do snapshot")
        classe = row.get("classificacao")
        if classe not in _CONAB_CLASSES:
            raise ErroConciliacaoSafra("CONAB revisão/previsão com estado não mapeado")
        classes.add(classe)
        valores[indicador] = _numero(row.get("valor"), indicador, zero=indicador != "AREA")
    if len(classes) != 1:
        raise ErroConciliacaoSafra("tripla da CONAB mistura previsão e dados informados")
    with localcontext() as ctx:
        ctx.prec = 36
        area, produtividade, producao = (valores[key] for key in
                                         ("AREA", "PRODUTIVIDADE", "PRODUCAO"))
        calculada = area * produtividade / 1000
        delta = producao - calculada
        # Desvio é diagnóstico: valores podem ser revisados ou arredondados.
        taxa = abs(delta) / producao if producao else (Decimal(0) if delta == 0 else None)
    return {
        "estado": "TRIPLA_CONAB_ASOF_DECLARADA" if elegivel else "TRIPLA_CONAB_SEM_PROVA_ASOF",
        "fonte": "CONAB", "uf": uf, "cultura": cultura,
        "subdivisao": subdivisao, "safra": safra,
        "arquivo": arquivo, "raw_sha256": snapshot_meta["raw_sha256"],
        "classificacao": classes.pop(), "cutoff": cutoff.isoformat(),
        "competencia": safra, "data_referencia": None,
        "data_publicacao": _instante(snapshot_meta["publicado_em"], "publicado_em").isoformat(),
        "data_coleta": _instante(snapshot_meta["coletado_em"], "coletado_em").isoformat(),
        "edicao_id": snapshot_meta["edicao_id"],
        "prova_disponibilidade_sha256": snapshot_meta["prova_disponibilidade_sha256"],
        "area_informada_conab_ha": str(area),
        "produtividade_informada_kg_ha": str(produtividade),
        "producao_informada_conab_t": str(producao),
        "producao_calculada_t": str(calculada),
        "residuo_fisico_t": str(delta),
        "desvio_relativo": None if taxa is None else str(taxa),
        "area_colhida_ha": None,  # nunca inferir a partir de AREA CONAB
        "habilita_treino": False, "habilita_publicacao": False,
    }


def confrontar_conab_pam(*, pacote_conab: dict, agregado_pam: dict,
                         meta_pam: dict, ano_civil_pam: int,
                         conversao_temporal: dict, cobertura_pam: dict,
                         emitido_em: str) -> dict:
    """Confronto DESCRITIVO, não identidade de população estatística.

    Sem prova de equivalência da safra comercial com ano civil e cobertura
    territorial PAM, retornar apenas status, jamais calcular delta numérico.
    """
    cutoff = _instante(emitido_em, "emitido_em")
    if not isinstance(pacote_conab, dict) or pacote_conab.get("fonte") != "CONAB":
        raise ErroConciliacaoSafra("pacote CONAB inválido")
    if pacote_conab.get("estado") not in (
            "TRIPLA_CONAB_ASOF_DECLARADA", "TRIPLA_CONAB_SEM_PROVA_ASOF"):
        raise ErroConciliacaoSafra("pacote CONAB fora do contrato")
    if _instante(pacote_conab.get("cutoff"), "cutoff CONAB") != cutoff:
        raise ErroConciliacaoSafra("pacote CONAB emitido em outro corte")
    if not isinstance(agregado_pam, dict) or agregado_pam.get("dataset_id") != "IBGE_PAM":
        raise ErroConciliacaoSafra("agregado PAM inválido")
    if type(ano_civil_pam) is not int or agregado_pam.get("ano") != ano_civil_pam:
        raise ErroConciliacaoSafra("competência PAM divergente")
    cultura = pacote_conab["cultura"]
    if cultura not in _PAM_MAP or agregado_pam.get("cultura") != cultura:
        raise ErroConciliacaoSafra("cultura PAM divergente")
    if agregado_pam.get("produto_ibge") != _PAM_MAP[cultura]:
        raise ErroConciliacaoSafra("produto PAM/CONAB fisicamente incompatível")
    if cultura == "MILHO" and pacote_conab.get("subdivisao") != "TOTAL":
        raise ErroConciliacaoSafra("PAM 1612 milho total não corresponde à safrinha isolada")
    if pacote_conab.get("subdivisao") != "TOTAL":
        raise ErroConciliacaoSafra("comparador exige total da cultura")
    uf_conab = pacote_conab.get("uf")
    if uf_conab not in UF_IBGE or agregado_pam.get("uf_ibge") != int(UF_IBGE[uf_conab]):
        raise ErroConciliacaoSafra("geografia CONAB/PAM divergente")
    if not isinstance(meta_pam, dict):
        raise ErroConciliacaoSafra("snapshot IBGE PAM ausente")
    if meta_pam.get("fonte_id") != "IBGE" or meta_pam.get("raw_sha256") != agregado_pam.get("raw_sha256"):

        raise ErroConciliacaoSafra("RAW PAM e snapshot de origem incompatíveis")
    if agregado_pam.get("edicao_id") != meta_pam.get("edicao_id"):
        raise ErroConciliacaoSafra("edição PAM agregada diverge do snapshot")
    esperada_c81 = C81_PAM_POR_CULTURA[cultura]
    if agregado_pam.get("codigo_categoria_c81") != esperada_c81:
        raise ErroConciliacaoSafra("identidade C81 PAM incompatível com cultura")
    if not isinstance(conversao_temporal, dict) or set(conversao_temporal) != {
            "safra_conab", "ano_pam", "metodo", "prova_sha256"}:
        raise ErroConciliacaoSafra("mapeamento temporal explícito obrigatório")
    if conversao_temporal["safra_conab"] != pacote_conab["safra"] or (
            type(conversao_temporal["ano_pam"]) is not int or
            conversao_temporal["ano_pam"] != ano_civil_pam):
        raise ErroConciliacaoSafra("safra comercial e ano civil sem equivalência")
    if conversao_temporal["metodo"] != "CALENDARIO_REGIONAL_DOCUMENTADO" or (
            not isinstance(conversao_temporal["prova_sha256"], str) or
            not _HASH.fullmatch(conversao_temporal["prova_sha256"])):
        raise ErroConciliacaoSafra("prova de calendário não documentada")
    if not isinstance(cobertura_pam, dict) or set(cobertura_pam) != {
            "municipios_cobertos", "municipios_universo",
            "cobertura_integral_auditada", "prova_sha256"}:
        raise ErroConciliacaoSafra("prova de cobertura PAM incompleta")
    n, universo = cobertura_pam["municipios_cobertos"], cobertura_pam["municipios_universo"]
    if (type(n) is not int or type(universo) is not int or n < 0 or
            universo < 1 or n > universo or n != agregado_pam.get("municipios_no_lote")):
        raise ErroConciliacaoSafra("contagem municipal PAM inconsistente")
    if type(cobertura_pam["cobertura_integral_auditada"]) is not bool:
        raise ErroConciliacaoSafra("cobertura exige booleano")
    if cobertura_pam["prova_sha256"] is not None and (
            not isinstance(cobertura_pam["prova_sha256"], str) or
            not _HASH.fullmatch(cobertura_pam["prova_sha256"])):
        raise ErroConciliacaoSafra("hash de cobertura inválido")
    if cobertura_pam["cobertura_integral_auditada"] and (
            n != universo or not cobertura_pam["prova_sha256"]):
        raise ErroConciliacaoSafra("cobertura completa alegada sem universo e prova")
    elegivel_pam = _prova_temporal(meta_pam, cutoff)
    reasons = []
    if pacote_conab["estado"] != "TRIPLA_CONAB_ASOF_DECLARADA":
        reasons.append("CONAB_SEM_PROVA_ASOF")
    if not elegivel_pam:
        reasons.append("PAM_SEM_PROVA_ASOF")
    if (not cobertura_pam["cobertura_integral_auditada"] or n != universo or
            agregado_pam.get("municipios_reprovados_arredondamento")):
        reasons.append("COBERTURA_OU_QUALIDADE_PAM_NAO_COMPROVADA")
    if agregado_pam.get("status") != "AGREGACAO_PARCIAL_SEM_PROVA_COBERTURA":
        raise ErroConciliacaoSafra("status PAM inesperado")
    if reasons:
        return {
            "estado": "NAO_COMPARAVEL_SEM_EVIDENCIAS",
            "motivos": reasons, "diferenca_producao_t": None,
            "habilita_treino": False, "habilita_publicacao": False,
        }
    # Mesmo com declarações, estimativas CONAB x PAM não são populações
    # idênticas. O resultado é só diagnóstico; NÃO publicar como acurácia.
    conab = _numero(pacote_conab["producao_informada_conab_t"],
                    "producao CONAB")
    pam = _numero(agregado_pam.get("producao_total_t"), "producao PAM")
    return {
        "estado": "DIFERENCA_DESCRITIVA_SEM_EQUIVALENCIA_ESTATISTICA",
        "cultura": cultura, "uf": uf_conab, "safra_conab": pacote_conab["safra"],
        "ano_pam": ano_civil_pam, "producao_conab_t": str(conab),
        "producao_pam_t": str(pam),
        "diferenca_producao_t": str(conab - pam),
        "area_colhida_pam_ha": str(_numero(agregado_pam.get("area_colhida_ha"),
                                         "area colhida PAM")),
        "area_colhida_conab_ha": None,
        "comparacao_de_acuracia": False,
        "habilita_treino": False, "habilita_publicacao": False,
        "limitacao": "CONAB edição e PAM ano civil não são estimandos idênticos.",
    }
