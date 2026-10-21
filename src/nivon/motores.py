"""Motores determinísticos iniciais do NIVON. Somente dados autorizados e explícitos.

Sem acesso à rede, dependências pagas, estado global, inferências escondidas ou bases privadas.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Iterable


class DadoInvalido(ValueError):
    """Entrada insuficiente ou inconsistente; jamais substituir por zero."""


class ClasseDestino(str, Enum):
    TRANSBORDO_PROVAVEL = "TRANSBORDO_PROVAVEL"
    CONSUMO_POTENCIAL = "CONSUMO_POTENCIAL"
    AMBIGUO = "AMBIGUO"
    SEM_EVIDENCIA = "SEM_EVIDENCIA"


def numero_positivo(valor: float | int | None, nome: str, *, aceita_zero: bool = False) -> float:
    if valor is None or isinstance(valor, bool):
        raise DadoInvalido(f"{nome}: nulo ou inválido")
    try:
        v = float(valor)
    except (ValueError, TypeError) as exc:
        raise DadoInvalido(f"{nome}: não numérico") from exc
    if not isfinite(v) or v < 0 or (not aceita_zero and v == 0):
        raise DadoInvalido(f"{nome}: valor não permitido")
    return v


def projetar_consumo(historico: dict[int, float], horizonte: int = 2, janela: int = 3) -> dict:
    """CAGR 3–5 anos principal; última variação apenas sensibilidade.

    Retorna cenários e nunca reivindica precisão preditiva fora da amostra.
    """
    if janela not in (3, 4, 5) or not 1 <= horizonte <= 2:
        raise DadoInvalido("janela deve ser 3–5 e horizonte 1–2 anos")
    anos = sorted(historico)
    if len(anos) < janela + 1 or anos != list(range(anos[0], anos[-1] + 1)):
        raise DadoInvalido("histórico anual insuficiente ou com lacunas")
    for ano, valor in historico.items():
        numero_positivo(valor, f"consumo_{ano}")
    ultimo = float(historico[anos[-1]])
    inicial = float(historico[anos[-1] - janela])
    anterior = float(historico[anos[-1] - 1])
    taxa_cagr = (ultimo / inicial) ** (1 / janela) - 1
    taxa_ultimo = ultimo / anterior - 1
    return {
        "classificacao": "PROJETADO_CENARIO",
        "ano_base": anos[-1],
        "janela_anos": janela,
        "taxa_padrao": taxa_cagr,
        "taxa_ultima_variacao": taxa_ultimo,
        "projecoes": [
            {"ano": anos[-1] + h,
             "cenario_principal": ultimo * (1 + taxa_cagr) ** h,
             "sensibilidade_ultima_taxa": ultimo * (1 + taxa_ultimo) ** h}
            for h in range(1, horizonte + 1)
        ],
    }


@dataclass(frozen=True)
class CoeficientesMargem:
    fonte: str = "CEPEA/ESALQ, estudo de margens, 2026"
    etanol_l_por_t: float = 440.0
    ddg_kg_por_t: float = 331.0
    oleo_l_por_t: float = 20.4
    tipo_etanol: str = "NAO_ESPECIFICADO"
    finalidade: str = "MARGEM_ECONOMICA_NAO_BALANCO_FISICO"


CEPEA = CoeficientesMargem()


def verificar_teto_materia_seca(
    *, umidade_milho: float, umidade_ddg: float,
    tipo_etanol: str, densidade_oleo_kg_l: float = 0.92,
    densidade_anidro_kg_l: float = 0.7893,
    densidade_hidratado_kg_l: float = 0.809,
    fracao_etanol_hidratado: float = 0.935,
    coeficientes: CoeficientesMargem = CEPEA,
) -> dict:
    """Teste conservador de matéria seca, NÃO validação completa da usina.

    O teste serve para rejeitar conjuntos impossíveis nas hipóteses informadas.
    """
    if tipo_etanol not in ("ANIDRO", "HIDRATADO"):
        raise DadoInvalido("tipo_etanol obrigatório: ANIDRO ou HIDRATADO")
    for nome, v in (("umidade_milho", umidade_milho), ("umidade_ddg", umidade_ddg)):
        v = numero_positivo(v, nome, aceita_zero=True)
        if v >= 1:
            raise DadoInvalido(f"{nome} deve ser fração [0,1)")
    for nome, v in (("densidade_oleo", densidade_oleo_kg_l),
                    ("densidade_anidro", densidade_anidro_kg_l),
                    ("densidade_hidratado", densidade_hidratado_kg_l),
                    ("fracao_hidratado", fracao_etanol_hidratado)):
        numero_positivo(v, nome)
    if fracao_etanol_hidratado > 1:
        raise DadoInvalido("fração de etanol não pode exceder 1")
    etanol_puro_kg = coeficientes.etanol_l_por_t * (
        densidade_anidro_kg_l if tipo_etanol == "ANIDRO"
        else densidade_hidratado_kg_l * fracao_etanol_hidratado
    )
    massa_seca_disponivel = 1000 * (1 - umidade_milho) - etanol_puro_kg / (1.111 * 0.5114)
    coprodutos_secos = (coeficientes.ddg_kg_por_t * (1 - umidade_ddg)
                        + coeficientes.oleo_l_por_t * densidade_oleo_kg_l)
    status = "SUSPEITO_BALANCO" if coprodutos_secos > massa_seca_disponivel + 1e-9 else "PASSA_TETO_NAO_HOMOLOGADO"
    return {"status": status, "teto_materia_seca_kg": massa_seca_disponivel,
            "coprodutos_materia_seca_kg": coprodutos_secos,
            "excesso_kg": max(0.0, coprodutos_secos - massa_seca_disponivel),
            "classificacao": "TESTE_DE_HIPOTESES"}


def estimar_milho_por_etanol(*, litros_etanol: float, rendimento_l_t: float | None,
                             tipo_etanol: str | None, materia_prima: str | None,
                             fonte_rendimento: str | None) -> dict:
    """Cálculo inverso só com etanol comprovadamente de milho e base explicitada."""
    if materia_prima != "MILHO":
        raise DadoInvalido("NAO_IDENTIFICAVEL: etanol sem separação por matéria-prima")
    if tipo_etanol not in ("ANIDRO", "HIDRATADO"):
        raise DadoInvalido("NAO_IDENTIFICAVEL: tipo de etanol não informado")
    if not fonte_rendimento or not fonte_rendimento.strip():
        raise DadoInvalido("rendimento não tem proveniência")
    return {"milho_estimado_t": numero_positivo(litros_etanol, "litros_etanol") /
            numero_positivo(rendimento_l_t, "rendimento_l_t"),
            "classificacao": "ESTIMADO", "fonte_rendimento": fonte_rendimento,
            "tipo_etanol": tipo_etanol}


def classificar_destino(*, tem_terminal: bool, tem_consumidor: bool) -> ClasseDestino:
    if not isinstance(tem_terminal, bool) or not isinstance(tem_consumidor, bool):
        raise DadoInvalido("marcadores de terminal e consumidor devem ser booleanos")
    if tem_terminal and tem_consumidor:
        return ClasseDestino.AMBIGUO
    if tem_terminal:
        return ClasseDestino.TRANSBORDO_PROVAVEL
    if tem_consumidor:
        return ClasseDestino.CONSUMO_POTENCIAL
    return ClasseDestino.SEM_EVIDENCIA


@dataclass(frozen=True)
class FluxoANTT:
    uf_origem: str
    uf_destino: str
    municipio_destino: str
    ncm: str
    volume_t: float
    carga_propria: bool

    def __post_init__(self):
        if not isinstance(self.ncm, str) or not self.ncm.isdigit() or len(self.ncm) != 8:
            raise DadoInvalido("NCM precisa ter oito dígitos preservados")
        if not self.municipio_destino.strip():
            raise DadoInvalido("município de destino vazio")
        numero_positivo(self.volume_t, "volume_t", aceita_zero=True)
        if not isinstance(self.carga_propria, bool):
            raise DadoInvalido("carga_propria deve ser booleana")


def resumir_fluxos_mt(fluxos: Iterable[FluxoANTT],
                       cidades_terminal: set[tuple[str, str]],
                       cidades_fabrica: set[tuple[str, str]]) -> dict:
    """Classifica amostra identificada por NCM, sem inflá-la como total da ANTT.

    A chave geográfica usa (UF, município normalizado por fonte cadastral). Não deduz
    destinatário por empresa; nunca descarta municípios ambíguos.
    """
    por_classe: dict[str, float] = {c.value: 0.0 for c in ClasseDestino}
    ignorados: list[str] = []
    total = 0.0
    por_produto = {"MILHO": 0.0, "SOJA": 0.0}
    for fluxo in fluxos:
        if fluxo.uf_origem != "MT" or fluxo.uf_destino == "MT":
            continue
        produto = {"10059010": "MILHO", "12019000": "SOJA"}.get(fluxo.ncm)
        if not produto:
            ignorados.append(fluxo.ncm)
            continue
        key = (fluxo.uf_destino.upper(), fluxo.municipio_destino.strip().upper())
        classe = classificar_destino(tem_terminal=key in cidades_terminal,
                                    tem_consumidor=key in cidades_fabrica)
        valor = numero_positivo(fluxo.volume_t, "volume_t", aceita_zero=True)
        total += valor
        por_classe[classe.value] += valor
        por_produto[produto] += valor
    return {"classificacao": "OBSERVADO_AMOSTRAL_NCM", "total_identificado_t": total,
            "por_classe_t": por_classe, "por_produto_t": por_produto,
            "ncm_nao_e_total": True, "ncms_ignorados": sorted(set(ignorados))}


def cobertura_ncm(*, volume_total_painel_t: float, volume_com_ncm_t: float) -> dict:
    total = numero_positivo(volume_total_painel_t, "volume_total_painel_t")
    ncm = numero_positivo(volume_com_ncm_t, "volume_com_ncm_t", aceita_zero=True)
    if ncm > total:
        raise DadoInvalido("volume com NCM excede total do painel")
    return {"taxa_cobertura_ncm": ncm / total, "volume_total_painel_t": total,
            "volume_com_ncm_t": ncm, "classificacao": "COBERTURA_AMOSTRAL"}


def validar_fonte(*, status: str, operacao: str, operacoes_autorizadas: set[str]) -> None:
    """Bloqueio por padrão por fonte *e operação*. Nenhum fetch ocorre aqui."""
    if status != "APROVADA" or operacao not in operacoes_autorizadas:
        raise PermissionError(f"FONTE_BLOQUEADA: {status}/{operacao}")
