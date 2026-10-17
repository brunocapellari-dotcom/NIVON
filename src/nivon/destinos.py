"""Análise espacial conservadora ANTT × MAPA × terminais.

Recebe registros já obtidos por meios autorizados. Nunca consulta endpoints internos.
NCM identificado é amostra; município com instalação NÃO prova destinatário.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Iterable

NCM_PRODUTO = {"10059010": "MILHO", "12019000": "SOJA"}
CLASSES = ("TRANSBORDO_PROVAVEL", "CONSUMO_POTENCIAL", "AMBIGUO", "SEM_EVIDENCIA")
TIPOS_TERMINAL = frozenset({"PORTO", "FERROVIARIO", "HIDROVIARIO"})


class ErroFluxo(ValueError):
    pass


def normalizar_municipio(nome: str) -> str:
    if not isinstance(nome, str):
        raise ErroFluxo("município sem texto")
    t = unicodedata.normalize("NFKD", nome)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = " ".join(t.upper().split())
    if not t or not re.fullmatch(r"[A-Z0-9 /.'-]+", t):
        raise ErroFluxo("município vazio ou inválido")
    return t


def chave_municipio(uf: str, municipio: str) -> tuple[str, str]:
    if not isinstance(uf, str) or not re.fullmatch(r"[A-Z]{2}", uf.strip().upper()):
        raise ErroFluxo("UF inválida")
    return uf.strip().upper(), normalizar_municipio(municipio)


def mes_referencia(valor: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", valor):
        raise ErroFluxo("período deve ser AAAA-MM")
    return valor


def volume_t(valor: float) -> float:
    if isinstance(valor, bool):
        raise ErroFluxo("volume booleano")
    try:
        n = float(valor)
    except (TypeError, ValueError) as exc:
        raise ErroFluxo("volume não numérico") from exc
    if not isfinite(n) or n < 0:
        raise ErroFluxo("volume nulo, negativo ou não finito")
    return n


@dataclass(frozen=True)
class FabricaMAPA:
    uf: str
    municipio: str
    fabricante: bool
    ativa: bool
    alimentacao_animal: bool
    fonte_id: str

    def __post_init__(self):
        chave_municipio(self.uf, self.municipio)
        if not self.fonte_id.strip():
            raise ErroFluxo("fábrica sem proveniência")
        for campo in ("fabricante", "ativa", "alimentacao_animal"):
            if not isinstance(getattr(self, campo), bool):
                raise ErroFluxo("marcador de fábrica não booleano")

    @property
    def elegivel(self) -> bool:
        return self.fabricante and self.ativa and self.alimentacao_animal


@dataclass(frozen=True)
class Terminal:
    uf: str
    municipio: str
    tipo: str
    produtos: frozenset[str]
    fonte_id: str

    def __post_init__(self):
        chave_municipio(self.uf, self.municipio)
        if self.tipo not in TIPOS_TERMINAL or not self.fonte_id.strip():
            raise ErroFluxo("terminal sem tipo ou proveniência")
        if not self.produtos or not self.produtos <= {"SOJA", "MILHO"}:
            raise ErroFluxo("terminal exige produtos comprovados")


@dataclass(frozen=True)
class FluxoMensal:
    periodo: str
    origem_uf: str
    origem_municipio: str
    destino_uf: str
    destino_municipio: str
    ncm: str
    toneladas: float
    carga_propria: bool
    fonte_id: str

    def __post_init__(self):
        mes_referencia(self.periodo)
        chave_municipio(self.origem_uf, self.origem_municipio)
        chave_municipio(self.destino_uf, self.destino_municipio)
        if not isinstance(self.ncm, str) or not re.fullmatch(r"\d{8}", self.ncm):
            raise ErroFluxo("NCM de oito dígitos é obrigatório; códigos desconhecidos são mantidos fora do recorte")
        volume_t(self.toneladas)
        if not isinstance(self.carga_propria, bool) or not self.fonte_id.strip():
            raise ErroFluxo("tipo de carga ou proveniência inválidos")


def _janela_meses(ultimo: str, tamanho: int) -> frozenset[str]:
    if not 1 <= tamanho <= 36:
        raise ErroFluxo("janela deve ter 1 a 36 meses")
    y, m = map(int, mes_referencia(ultimo).split("-"))
    valores = []
    for _ in range(tamanho):
        valores.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return frozenset(valores)


def analisar_destinos(
    fluxos: Iterable[FluxoMensal],
    fabricas: Iterable[FabricaMAPA],
    terminais: Iterable[Terminal],
    *,
    mes_corte: str,
    janela_meses: int = 12,
    min_meses_recorrentes: int = 3,
) -> dict:
    """Retorna destinos e volumes IDENTIFICADOS na amostra, não consumo efetivo.

    Cada linha é preservada na agregação, inclusive carga própria. Não excluir
    municípios com terminais; classificar e reter AMBIGUO.
    """
    janela = _janela_meses(mes_corte, janela_meses)
    if not 1 <= min_meses_recorrentes <= janela_meses:
        raise ErroFluxo("mínimo de recorrência inválido")
    mapa_fabricas = {chave_municipio(f.uf, f.municipio) for f in fabricas if f.elegivel}
    mapa_terminais: set[tuple[str, str, str]] = set()
    for t in terminais:
        mapa_terminais.update((t.uf.upper(), normalizar_municipio(t.municipio), p) for p in t.produtos)
    agrupado: dict[tuple[str, str, str, str, str], dict] = {}
    ignorados = 0
    entradas = 0
    chaves_mensais: set[tuple[str, ...]] = set()
    for f in fluxos:
        entradas += 1
        if f.periodo not in janela or f.origem_uf.upper() != "MT" or f.destino_uf.upper() == "MT":
            continue
        produto = NCM_PRODUTO.get(f.ncm)
        if not produto:
            ignorados += 1
            continue
        origem = normalizar_municipio(f.origem_municipio)
        destino = normalizar_municipio(f.destino_municipio)
        uf = f.destino_uf.upper()
        chave_mensal = (f.periodo, origem, uf, destino, f.ncm, str(f.carga_propria))
        if chave_mensal in chaves_mensais:
            raise ErroFluxo("linha mensal agregada duplicada; escolher um snapshot/vintage antes de somar")
        chaves_mensais.add(chave_mensal)
        tem_fabrica = (uf, destino) in mapa_fabricas
        tem_terminal = (uf, destino, produto) in mapa_terminais
        classe = ("AMBIGUO" if tem_fabrica and tem_terminal else
                  "TRANSBORDO_PROVAVEL" if tem_terminal else
                  "CONSUMO_POTENCIAL" if tem_fabrica else "SEM_EVIDENCIA")
        chave = (origem, uf, destino, produto, classe)
        item = agrupado.setdefault(chave, {
            "origem_uf": "MT", "origem_municipio": origem,
            "destino_uf": uf, "destino_municipio": destino,
            "produto": produto, "classe": classe,
            "toneladas_identificadas": 0.0, "meses": set(),
            "toneladas_carga_propria": 0.0,
            "toneladas_terceiros": 0.0,
        })
        t = volume_t(f.toneladas)
        item["toneladas_identificadas"] += t
        item["meses"].add(f.periodo)
        item["toneladas_carga_propria" if f.carga_propria else "toneladas_terceiros"] += t
    saida = []
    for item in agrupado.values():
        meses = tuple(sorted(item.pop("meses")))
        item["meses_com_fluxo"] = len(meses)
        item["meses_observados"] = meses
        item["recorrente"] = len(meses) >= min_meses_recorrentes
        saida.append(item)
    saida.sort(key=lambda x: (-x["toneladas_identificadas"], x["produto"], x["destino_uf"], x["destino_municipio"]))
    return {
        "classificacao": "MOVIMENTACAO_AMOSTRAL_IDENTIFICADA_NCM",
        "nao_equivale_consumo_final": True,
        "taxa_cobertura_ncm": None,  # exige denominador independente equivalente da ANTT
        "janela_meses": janela_meses,
        "mes_corte": mes_corte,
        "limiar_recorrencia_meses": min_meses_recorrentes,
        "linhas_entrada": entradas, "linhas_ncm_outros": ignorados,
        "total_t_identificado": sum(i["toneladas_identificadas"] for i in saida),
        "destinos": saida,
    }
