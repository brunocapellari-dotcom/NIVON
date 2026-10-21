"""Índice Madden-Julian (RMM) recebido externamente, sem coleta nem previsão.

Interpreta snapshots históricos Wheeler-Hendon informados pelo provedor (BOM),
sem atribuir impacto agrícola à fase. A coluna de fase é observada NO ÍNDICE,
não inferida por um LLM. Dados históricos baixados hoje não provam que
estavam disponíveis na data histórica (as-of).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from math import hypot, isfinite


class RMMInvalido(ValueError):
    """Snapshot incompatível com processamento meteorológico seguro."""


def _instante(valor, nome):
    if not isinstance(valor, str) or "T" not in valor:
        raise RMMInvalido(nome + ": ISO 8601 completo é obrigatório")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RMMInvalido(nome + ": timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise RMMInvalido(nome + ": fuso obrigatório")
    return dt.astimezone(timezone.utc)


def _inteiro(valor, nome):
    try:
        if not valor.isdecimal():
            raise ValueError("não decimal")
        return int(valor)
    except (ValueError, AttributeError, TypeError) as exc:
        raise RMMInvalido(nome + ": inteiro inválido") from exc


def _real(valor, nome):
    try:
        numero = float(valor)
    except (ValueError, TypeError) as exc:
        raise RMMInvalido(nome + ": número inválido") from exc
    if not isfinite(numero):
        raise RMMInvalido(nome + ": número não finito")
    return numero


def normalizar_rmm_bom(*, texto, coletado_em, publicado_em=None,
                       fonte_id="BOM_RMM", licenca_verificada=False):
    """Lê snapshot BOM rmm.74toRealtime.txt de entrada fornecida.

    Nunca busca URL, publica ou grava bytes. Um valor sentinela (>=900 ou <=-900)
    é descartado com contagem. Para backtest histórico sem vazamento de informação
    é necessário guardar snapshots realmente observados na época.
    """
    if not isinstance(texto, str) or not 1 <= len(texto) <= 4_000_000:
        raise RMMInvalido("snapshot textual ausente ou excessivo")
    if fonte_id != "BOM_RMM":
        raise RMMInvalido("mistura entre índices e provedores proibida")
    if type(licenca_verificada) is not bool:
        raise RMMInvalido("licença exige avaliação explícita")
    captura = _instante(coletado_em, "coleta")
    publicado = _instante(publicado_em, "publicação") if publicado_em else None
    if publicado is not None and publicado > captura:
        raise RMMInvalido("publicação posterior à captura")

    observacoes = []
    datas = set()
    ausentes = 0
    comecou = False
    anterior = None

    for numero_linha, linha in enumerate(texto.splitlines(), start=1):
        campos = linha.strip().split()
        if not campos or linha.lstrip().startswith("#"):
            continue
        if not campos[0].isdecimal():
            if comecou:
                raise RMMInvalido("linha não estruturada após dados: " + str(numero_linha))
            continue  # cabeçalho BOM
        comecou = True
        if len(campos) not in (7, 8):
            raise RMMInvalido("esperados 7 ou 8 campos: linha " + str(numero_linha))
        ano, mes, dia = [_inteiro(v, "data") for v in campos[:3]]
        try:
            data = date(ano, mes, dia)
        except ValueError as exc:
            raise RMMInvalido("data de RMM inválida") from exc
        if data.year < 1974 or data > captura.date():
            raise RMMInvalido("data incompatível com histórico/coleta")
        if data in datas or (anterior is not None and data <= anterior):
            raise RMMInvalido("data repetida ou fora de ordem")
        datas.add(data)
        anterior = data

        valores = [_real(v, "índice RMM") for v in campos[3:7]]
        if any(abs(x) >= 900 for x in valores):
            ausentes += 1
            continue
        rmm1, rmm2, fase_bruta, amplitude = valores
        if not (abs(rmm1) <= 20 and abs(rmm2) <= 20
                and 0 <= amplitude <= 30):
            raise RMMInvalido("índice fora dos limites de plausibilidade")
        fase = int(fase_bruta)
        if fase_bruta != fase or fase not in range(1, 9):
            raise RMMInvalido("fase RMM não pertence a 1–8")
        calculada = hypot(rmm1, rmm2)
        if abs(calculada - amplitude) > 0.06:
            raise RMMInvalido("amplitude diverge de sqrt(RMM1²+RMM2²)")
        observacoes.append({
            "data": data.isoformat(),
            "rmm1": rmm1, "rmm2": rmm2, "fase_fonte": fase,
            "amplitude": amplitude, "sinal": "ATIVO" if amplitude >= 1 else "FRACO",
            "classe": "INDICE_DERIVADO_DE_OBSERVACOES",
            "situacao": "HISTORICO_NAO_HOMOLOGADO",
        })

    if not observacoes:
        raise RMMInvalido("snapshot sem dados válidos")
    return {
        "fonte_id": fonte_id, "coletado_em": captura.isoformat(),
        "publicado_em": publicado.isoformat() if publicado else None,
        "publicacao_confirmada": publicado is not None,
        "licenca_verificada": licenca_verificada,
        "hash_sha256": sha256(texto.encode("utf-8")).hexdigest(),
        "observacoes": observacoes, "linhas_ausentes": ausentes,
        "operacional": False,
        "nota": (
            "A publicação do snapshot não comprova disponibilidade histórica por dia; "
            "não usar retroativamente como feature as-of. Fase isolada não prevê "
            "chuva municipal, geada, preço ou produtividade."
        ),
    }


def ultimo_rmm_ate(*, snapshot, corte_em):
    """Consulta estrita: captura e publicação comprovadas até o corte.

    Evita usar retrospectivamente download atual como previsão passada.
    Não fornece fase futuramente prevista, só diagnóstico derivado.
    """
    corte = _instante(corte_em, "corte")
    if not isinstance(snapshot, dict) or snapshot.get("fonte_id") != "BOM_RMM":
        raise RMMInvalido("snapshot não canônico")
    coleta = _instante(snapshot.get("coletado_em"), "coleta")
    publicado = snapshot.get("publicado_em")
    if not publicado:
        return None  # sem data de publicação conhecida não existe as-of confiável
    if coleta > corte or _instante(publicado, "publicação") > corte:
        return None
    valores = snapshot.get("observacoes")
    if not isinstance(valores, list):
        raise RMMInvalido("observações inválidas")
    elegiveis = [
        linha for linha in valores
        if isinstance(linha, dict) and isinstance(linha.get("data"), str)
        and linha["data"] <= corte.date().isoformat()
    ]
    return max(elegiveis, key=lambda r: r["data"]).copy() if elegiveis else None
