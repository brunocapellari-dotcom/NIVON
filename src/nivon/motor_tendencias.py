"""Motor transversal NIVON: tendência observada != projeção probabilística.

API pura, determinística e offline. Não adquire dados, não autoriza publicação,
não assume que tendências de estoque, preços ou clima são intercambiáveis.
Limiares são parâmetros por INDICADOR/UNIDADE, não constantes universais.
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from statistics import median
from typing import Mapping, Sequence


class ErroTendencia(ValueError):
    """Contrato ou proveniência de série inválida."""


CLASSES = ("ALTA", "BAIXA", "ESTABILIDADE")
FREQUENCIAS = ("DIARIA", "SEMANAL", "SESSOES", "MENSAL", "ANUAL")


def _numero(valor: object, nome: str, *, nao_negativo: bool = False) -> float:
    if type(valor) not in (float, int) or not isfinite(valor):
        raise ErroTendencia(f"{nome}: número finito obrigatório")
    v = float(valor)
    if nao_negativo and v < 0:
        raise ErroTendencia(f"{nome}: negativo proibido")
    return v


def _data(valor: object, nome: str) -> date:
    if not isinstance(valor, str):
        raise ErroTendencia(f"{nome}: AAAA-MM-DD obrigatório")
    try:
        d = date.fromisoformat(valor)
    except ValueError as exc:
        raise ErroTendencia(f"{nome}: data inválida") from exc
    if d.isoformat() != valor:
        raise ErroTendencia(f"{nome}: data não canônica")
    return d


def _fonte(valor: object) -> str:
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 100:
        raise ErroTendencia("fonte_id obrigatória")
    return valor.strip()


def _metadados(obs: Mapping, *, asof: date, fonte_id: str, nao_negativo: bool) -> tuple[date, float]:
    if not isinstance(obs, Mapping):
        raise ErroTendencia("observação precisa ser objeto")
    try:
        ref = _data(obs["periodo"], "periodo")
        pub = _data(obs["publicacao"], "publicacao")
        coleta = _data(obs["coleta"], "coleta")
        valor = _numero(obs["valor"], "valor", nao_negativo=nao_negativo)
        fonte = _fonte(obs["fonte_id"])
        sha = obs["edicao_sha256"]
    except KeyError as exc:
        raise ErroTendencia(f"observação sem campo: {exc.args[0]}") from exc
    if fonte != fonte_id:
        raise ErroTendencia("mistura de fontes sem reconciliação")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ErroTendencia("edicao_sha256 inválido")
    if not (ref <= pub <= coleta <= asof):
        raise ErroTendencia("vazamento temporal ou cronologia inválida")
    return ref, valor


def _intervalo_anual(a: date, b: date) -> bool:
    return a.month == b.month == 1 and a.day == b.day == 1 and b.year == a.year + 1


def _consecutivo(a: date, b: date, frequencia: str) -> bool:
    if frequencia == "DIARIA":
        return (b - a).days == 1
    if frequencia == "SEMANAL":
        return (b - a).days == 7
    if frequencia == "SESSOES":
        # Pregões/sessões não acontecem todo dia; calendário de feriados é QC externo.
        return 1 <= (b - a).days <= 10
    if frequencia == "MENSAL":
        return a.day == b.day == 1 and b.year * 12 + b.month == a.year * 12 + a.month + 1
    if frequencia == "ANUAL":
        return _intervalo_anual(a, b)
    return False


def _limiar(tolerancia_absoluta: object, tolerancia_relativa: object, referencia: float) -> float:
    a = _numero(tolerancia_absoluta, "tolerancia_absoluta", nao_negativo=True)
    r = _numero(tolerancia_relativa, "tolerancia_relativa", nao_negativo=True)
    if r >= 1 or (a == 0 and r == 0):
        raise ErroTendencia("limiar deve ser positivo e percentual inferior a 1")
    return a + r * abs(referencia)


def _intensidade(deslocamento: float, limiar: float) -> str | None:
    if limiar <= 0:
        return None
    razao = abs(deslocamento) / limiar
    return "FORTE" if razao >= 4 else ("MODERADA" if razao >= 2 else "LEVE")


def _voto(delta: float, limiar: float) -> str:
    if delta > limiar:
        return "ALTA"
    if delta < -limiar:
        return "BAIXA"
    return "ESTABILIDADE"


def tendencia_observada(
    serie: Sequence[Mapping], *, as_of: str, fonte_id: str, unidade: str,
    frequencia: str, janela: int = 6, sazonalidade: int = 0,
    tolerancia_absoluta: float = 0.0, tolerancia_relativa: float = 0.0,
    nao_negativo: bool = True,
) -> dict:
    """Classifica movimento descritivo, sem extrapolar para o futuro.

    Não sazonal: inclinação robusta de Theil-Sen em janela regular.
    Mensal sazonal: mediana das últimas 'janela' diferenças interanuais.
    Para safras cumulativas, analise RITMO/variação de avanço, não o nível.
    """
    corte = _data(as_of, "as_of")
    fonte_id = _fonte(fonte_id)
    if not isinstance(unidade, str) or not unidade.strip():
        raise ErroTendencia("unidade obrigatória")
    if frequencia not in FREQUENCIAS:
        raise ErroTendencia("frequencia inválida")
    if type(janela) is not int or not 4 <= janela <= 48:
        raise ErroTendencia("janela deve ter 4 a 48 observações")
    if type(sazonalidade) is not int or sazonalidade not in (0, 12) or (sazonalidade and frequencia != "MENSAL"):
        raise ErroTendencia("sazonalidade=12 somente para série mensal")
    if not isinstance(serie, (tuple, list)) or len(serie) > 240:
        raise ErroTendencia("série inválida ou excessiva")
    if len(serie) < janela + sazonalidade:
        return {"status": "DADOS_INSUFICIENTES", "tendencia": "INDETERMINADA",
                "publicavel": False, "necessarias": janela + sazonalidade, "disponiveis": len(serie)}
    linhas = [_metadados(row, asof=corte, fonte_id=fonte_id, nao_negativo=nao_negativo) for row in serie]
    datas = [x[0] for x in linhas]
    if len(set(datas)) != len(datas):
        raise ErroTendencia("período duplicado: selecione a edição as-of antes do cálculo")
    if any(not _consecutivo(a, b, frequencia) for a, b in zip(datas, datas[1:])):
        raise ErroTendencia("série fora de ordem, incompleta ou em frequência incompatível")
    valores = [v for _, v in linhas]
    recentes = valores[-janela:]
    referencia = median(recentes)
    limiar = _limiar(tolerancia_absoluta, tolerancia_relativa, referencia)
    if sazonalidade:
        mudancas = [valores[i] - valores[i-12] for i in range(len(valores)-janela, len(valores))]
        deslocamento = median(mudancas)
        # Direção relativa ao mesmo mês do ano anterior; não é inclinação mensal.
        metodo = "MEDIANA_VARIACOES_INTERANUAIS"
        variabilidade = max(mudancas) - min(mudancas)
        sinais = mudancas
    else:
        inclinacoes = [(recentes[j] - recentes[i]) / (j-i)
                        for i in range(janela) for j in range(i+1, janela)]
        inclinacao = median(inclinacoes)
        deslocamento = inclinacao * (janela-1)
        metodo = "THEIL_SEN_JANELA"
        variabilidade = max(recentes) - min(recentes)
        sinais = inclinacoes
    voto = _voto(deslocamento, limiar)
    if voto == "ESTABILIDADE":
        # Estabilidade é faixa pequena E ausência de oscilação material.
        tendencia = "ESTABILIDADE" if variabilidade <= 2 * limiar else "INDETERMINADA"
        consistencia = None
    else:
        suporte = sum(1 for v in sinais if (v > 0 if voto == "ALTA" else v < 0))
        consistencia = suporte / len(sinais)
        tendencia = voto if consistencia >= 0.65 else "INDETERMINADA"
    return {
        "status": "DESCRITIVO_OFFLINE_NAO_HOMOLOGADO",
        "orientacao": "OBSERVADA", "tendencia": tendencia,
        "intensidade": _intensidade(deslocamento, limiar) if tendencia in ("ALTA", "BAIXA") else None,
        "metodo": metodo, "frequencia": frequencia, "sazonalidade": sazonalidade,
        "janela_observacoes": janela, "periodo_inicial": datas[-janela].isoformat(),
        "periodo_final": datas[-1].isoformat(), "as_of": as_of,
        "deslocamento_descritivo": deslocamento, "limiar_unidade": limiar,
        "variabilidade_unidade": variabilidade, "suporte_direcional": consistencia,
        "unidade": unidade, "fonte_id": fonte_id,
        "probabilidades_calibradas": None, "publicavel": False,
        "limitacao": "Classificação descritiva; sem previsão, teste de significância, ajuste de sazonalidade automático ou validação com séries reais.",
    }


def tendencia_projetada(
    base: Mapping, cenarios: Sequence[Mapping], *, as_of: str, fonte_id: str, unidade: str,
    tolerancia_absoluta: float = 0.0, tolerancia_relativa: float = 0.0,
    nao_negativo: bool = True,
) -> dict:
    """Consenso de CENÁRIOS futuros; pesos NÃO são probabilidades calibradas.

    Cada cenário declara: modelo_id, valor, peso, emitido_em, alvo_periodo.
    Todos devem ser emitidos até o corte e apontar para o MESMO alvo futuro.
    """
    corte = _data(as_of, "as_of")
    fonte_id = _fonte(fonte_id)
    if not isinstance(unidade, str) or not unidade.strip():
        raise ErroTendencia("unidade obrigatória")
    _, atual = _metadados(base, asof=corte, fonte_id=fonte_id, nao_negativo=nao_negativo)
    limiar = _limiar(tolerancia_absoluta, tolerancia_relativa, atual)
    if not isinstance(cenarios, (tuple, list)) or not 3 <= len(cenarios) <= 100:
        raise ErroTendencia("mínimo 3 e máximo 100 cenários")
    total = 0.0
    alvo = None
    modelos = set()
    votos = {classe: 0.0 for classe in CLASSES}
    for c in cenarios:
        if not isinstance(c, Mapping):
            raise ErroTendencia("cenário inválido")
        try:
            modelo = c["modelo_id"]
            meta = _data(c["alvo_periodo"], "alvo_periodo")
            emitido = _data(c["emitido_em"], "emitido_em")
            valor = _numero(c["valor"], "valor_projetado", nao_negativo=nao_negativo)
            peso = _numero(c["peso"], "peso", nao_negativo=True)
        except KeyError as exc:
            raise ErroTendencia(f"cenário sem campo: {exc.args[0]}") from exc
        if not isinstance(modelo, str) or not modelo.strip() or modelo in modelos:
            raise ErroTendencia("identidade de modelo ausente ou repetida")
        modelos.add(modelo)
        if not (emitido <= corte < meta) or meta <= _data(base["periodo"], "periodo"):
            raise ErroTendencia("cenário extemporâneo ou alvo não futuro")
        if alvo is not None and meta != alvo:
            raise ErroTendencia("cenários de horizontes diferentes não são agregáveis")
        alvo = meta
        total += peso
        votos[_voto(valor-atual, limiar)] += peso
    if abs(total-1.0) > 1e-6:
        raise ErroTendencia("pesos de cenários precisam somar 1")
    votos = {k: v/total for k, v in votos.items()}
    ordenados = sorted(votos.items(), key=lambda x: x[1], reverse=True)
    classe = ordenados[0][0] if ordenados[0][1] >= 0.60 and ordenados[0][1]-ordenados[1][1] >= 0.20 else "INDETERMINADA"
    return {
        "status": "CONSENSO_CENARIOS_NAO_CALIBRADO", "orientacao": "PROJETADA",
        "tendencia": classe, "intensidade": None, "data_alvo": alvo.isoformat(),
        "base_periodo": base["periodo"], "as_of": as_of, "valor_base": atual,
        "limiar_unidade": limiar, "unidade": unidade, "fonte_id": fonte_id,
        "quantidade_cenarios": len(cenarios), "participacao_ponderada_cenarios": votos,
        "probabilidades_calibradas": None, "publicavel": False,
        "limitacao": "Pesos/consenso não equivalem a probabilidade; requer backtest point-in-time, skill, calibração, regime e licença antes de publicar.",
    }
