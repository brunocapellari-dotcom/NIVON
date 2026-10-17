"""Mapeamentos EXPLÍCITOS para linhas CSV já lidas de arquivos autorizados.

Não presume o cabeçalho real do SIPEAGRO ou de exportações do BI da ANTT.
Mapeamento e códigos de domínio precisam ser conferidos com a edição da fonte.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Mapping

from .destinos import ErroFluxo, FabricaMAPA, FluxoMensal, Terminal


class ErroMapeamento(ValueError):
    pass


def _normalizar(valor: object) -> str:
    if valor is None:
        return ""
    t = unicodedata.normalize("NFKD", str(valor))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _validar_mapeamento(mapa: Mapping[str, str], exigidos: set[str]) -> None:
    if not exigidos <= set(mapa) or any(not isinstance(mapa[k], str) or not mapa[k].strip()
                                       for k in exigidos):
        raise ErroMapeamento("mapeamento incompleto")
    if len({mapa[k] for k in exigidos}) != len(exigidos):
        raise ErroMapeamento("mesma coluna usada para conceitos distintos")


def _campo(linha: Mapping[str, object], mapa: Mapping[str, str], canonico: str) -> str:
    nome = mapa[canonico]
    if nome not in linha:
        raise ErroMapeamento(f"coluna exigida ausente: {nome}")
    valor = linha[nome]
    if valor is None or not str(valor).strip():
        raise ErroMapeamento(f"valor obrigatório vazio: {nome}")
    return str(valor).strip()


def decimal_ptbr(valor: str) -> float:
    """Interpretar '1.234,56' como 1234.56, nunca inferir padrão estrangeiro."""
    v = str(valor).strip()
    padrao = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"
    if not re.fullmatch(padrao, v):
        raise ErroMapeamento("número fora do contrato decimal pt-BR")
    return float(v.replace(".", "").replace(",", "."))


def mapear_fabricas(
    linhas: Iterable[Mapping[str, object]],
    mapa: Mapping[str, str],
    *,
    fonte_id: str,
    situacoes_ativas: frozenset[str],
    situacoes_inativas: frozenset[str],
    atividades_fabricante: frozenset[str],
    atividades_nao_fabricante: frozenset[str],
    areas_alimentacao_animal: frozenset[str],
    areas_nao_alimentacao_animal: frozenset[str],
) -> list[FabricaMAPA]:
    """A ausência de domínio conhecido é ERRO, não classificação adivinhada."""
    exigidos = {"uf", "municipio", "situacao", "atividade", "area"}
    _validar_mapeamento(mapa, exigidos)
    grupos = (
        (situacoes_ativas, situacoes_inativas),
        (atividades_fabricante, atividades_nao_fabricante),
        (areas_alimentacao_animal, areas_nao_alimentacao_animal),
    )
    for sim, nao in grupos:
        if not sim or not nao or {_normalizar(v) for v in sim} & {_normalizar(v) for v in nao}:
            raise ErroMapeamento("domínio incompleto ou ambíguo")
    dominio = [({_normalizar(x) for x in sim}, {_normalizar(x) for x in nao})
               for sim, nao in grupos]

    def interpretar(valor: str, i: int) -> bool:
        texto = _normalizar(valor)
        if texto in dominio[i][0]:
            return True
        if texto in dominio[i][1]:
            return False
        raise ErroMapeamento(f"valor de domínio não homologado: {valor}")

    resultados = []
    for linha in linhas:
        resultados.append(FabricaMAPA(
            uf=_campo(linha, mapa, "uf"),
            municipio=_campo(linha, mapa, "municipio"),
            ativa=interpretar(_campo(linha, mapa, "situacao"), 0),
            fabricante=interpretar(_campo(linha, mapa, "atividade"), 1),
            alimentacao_animal=interpretar(_campo(linha, mapa, "area"), 2),
            fonte_id=fonte_id,
        ))
    return resultados


def mapear_fluxos(
    linhas: Iterable[Mapping[str, object]],
    mapa: Mapping[str, str],
    *,
    fonte_id: str,
    cargas_proprias: frozenset[str] = frozenset({"S", "SIM"}),
    cargas_terceiros: frozenset[str] = frozenset({"N", "NAO"}),
) -> dict:
    """NCM ausente é reportado à parte; não atribuir a soja/milho por inferência."""
    exigidos = {"periodo", "origem_uf", "origem_municipio", "destino_uf",
                "destino_municipio", "toneladas", "carga_propria"}
    _validar_mapeamento(mapa, exigidos)
    if "ncm" not in mapa or not mapa["ncm"]:
        raise ErroMapeamento("NCM obrigatório no contrato, mesmo quando falta na linha")
    propria = {_normalizar(x) for x in cargas_proprias}
    terceiros = {_normalizar(x) for x in cargas_terceiros}
    if not propria or not terceiros or propria & terceiros:
        raise ErroMapeamento("domínio carga própria inválido")
    saida = []
    sem_ncm_linhas = 0
    sem_ncm_t = 0.0
    fora_produtos_linhas = 0
    for linha in linhas:
        toneladas = decimal_ptbr(_campo(linha, mapa, "toneladas"))
        raw = linha.get(mapa["ncm"])
        if raw is None or not str(raw).strip():
            sem_ncm_linhas += 1
            sem_ncm_t += toneladas
            continue
        ncm = re.sub(r"[^0-9]", "", str(raw))
        if not re.fullmatch(r"\d{8}", ncm):
            raise ErroMapeamento("NCM malformado")
        if ncm not in {"10059010", "12019000"}:
            fora_produtos_linhas += 1
            continue
        tipo = _normalizar(_campo(linha, mapa, "carga_propria"))
        if tipo not in propria | terceiros:
            raise ErroMapeamento("tipo de carga própria desconhecido")
        try:
            saida.append(FluxoMensal(
                periodo=_campo(linha, mapa, "periodo"),
                origem_uf=_campo(linha, mapa, "origem_uf"),
                origem_municipio=_campo(linha, mapa, "origem_municipio"),
                destino_uf=_campo(linha, mapa, "destino_uf"),
                destino_municipio=_campo(linha, mapa, "destino_municipio"),
                ncm=ncm, toneladas=toneladas, carga_propria=tipo in propria,
                fonte_id=fonte_id,
            ))
        except ErroFluxo as exc:
            raise ErroMapeamento(f"registro ANTT incompatível: {exc}") from exc
    return {
        "fluxos": saida,
        "linhas_ncm_ausente": sem_ncm_linhas,
        "toneladas_sem_ncm_t": sem_ncm_t,
        "linhas_outros_produtos": fora_produtos_linhas,
        "interpretacao": "NCM AUSENTE NAO E MILHO NEM SOJA",
    }
