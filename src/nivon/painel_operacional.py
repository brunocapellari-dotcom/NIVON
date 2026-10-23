"""NIVON: leitura conjunta de logistica, filas portuarias e tendencias.

Motor puro: sem HTTP, credenciais, SQL, efeito colateral ou promocao editorial.
Consome snapshots versionados dos coletores existentes e da consulta historica BQ.
Nao une tonelagens entre modais nem confunde lineup, AIS e operacao concluida.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any


CLASSES_PRECO = {"FRETE_ANUNCIADO", "CBOT", "PRECO_FISICO"}
CONTRATO_SERIE = (
    "produto", "origem", "destino", "transportadora", "equipamento",
    "regime", "terminal", "contrato", "modal", "ponto_embarque",
    "pedagio", "tipo_preco", "mercado", "praca",
)


class ErroMotor(ValueError):
    """Entrada inconsistente: nao produzir indicador numerico."""


def _tempo(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ErroMotor("timestamp ISO com timezone obrigatorio")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroMotor("timestamp ISO invalido") from exc
    if parsed.utcoffset() is None:
        raise ErroMotor("timestamp sem timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, *, positivo: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ErroMotor("numero ausente ou invalido")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ErroMotor("numero invalido") from exc
    if not d.is_finite() or d < 0 or (positivo and d == 0):
        raise ErroMotor("numero negativo, zero proibido ou nao-finito")
    return d


def _inteiro(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ErroMotor("contagem deve ser inteiro nao negativo")
    return value


def _quantil(valores: list[Decimal], p: Decimal) -> Decimal | None:
    if not valores:
        return None
    ordered = sorted(valores)
    indice = (len(ordered) - 1) * p
    baixo = int(indice)
    alto = min(baixo + 1, len(ordered) - 1)
    return ordered[baixo] + (ordered[alto] - ordered[baixo]) * (indice - baixo)


def _bloqueio(motivo: str, **campos: Any) -> dict:
    return {"status": "DADOS_INSUFICIENTES", "publicavel": False,
            "motivos": [motivo], **campos}


def tendencia_precos(
    observacoes: list[dict], *, classe: str, serie_id: str, as_of: str,
    minimo_dias: int = 6, variacao_minima_pct: str = "2",
) -> dict:
    """Tendencia por mediana de metades cronologicas, apenas mesma serie/condicoes.

    Para divulgacoes da MESMA transportadora e condicoes, mais de um preco
    anunciado num dia usa o maior valor; nenhum e considerado negociado.
    Data de publicacao E de coleta devem existir e anteceder as_of.
    """
    momento = _tempo(as_of)
    if classe not in CLASSES_PRECO or not isinstance(serie_id, str) or not serie_id.strip():
        raise ErroMotor("classe ou serie_id invalido")
    if not isinstance(observacoes, list) or len(observacoes) > 10000:
        raise ErroMotor("lote invalido ou grande demais")
    if type(minimo_dias) is not int or not 6 <= minimo_dias <= 90:
        raise ErroMotor("minimo_dias fora de 6..90")
    limite = _decimal(variacao_minima_pct, positivo=True)
    if limite > 100:
        raise ErroMotor("limiar de tendencia invalido")
    revisoes: dict[tuple[str, str], tuple[datetime, Decimal]] = {}
    contrato = None
    unidade = None
    excluidos = 0
    for obs in observacoes:
        if not isinstance(obs, dict) or not isinstance(obs.get("campos"), dict):
            raise ErroMotor("observacao e campos devem ser objetos")
        c = obs["campos"]
        if c.get("serie_id") != serie_id or c.get("classe") != classe:
            raise ErroMotor("mistura de serie ou classe de indicador")
        chave = tuple(c.get(f) for f in CONTRATO_SERIE)
        if any(x is not None and not isinstance(x, str) for x in chave):
            raise ErroMotor("condicoes de contrato invalidas")
        if contrato is None:
            contrato = chave
        elif contrato != chave:
            raise ErroMotor("mistura de transportadora, contrato ou condicoes comerciais")
        if not c.get("produto") or (classe == "FRETE_ANUNCIADO" and
            any(not c.get(f) for f in ("origem", "destino", "transportadora",
                                       "regime", "equipamento", "ponto_embarque",
                                       "terminal", "pedagio", "tipo_preco"))):
            return _bloqueio("condicoes_comerciais_incompletas", serie_id=serie_id, classe=classe)
        if classe == "CBOT" and not c.get("contrato"):
            return _bloqueio("contrato_futuro_ausente", serie_id=serie_id, classe=classe)
        if classe == "CBOT" and any(not c.get(f) for f in ("mercado", "tipo_preco")):
            return _bloqueio("mercado_ou_tipo_cbot_ausente", serie_id=serie_id, classe=classe)
        if classe == "PRECO_FISICO" and any(not c.get(f) for f in ("praca", "tipo_preco")):
            return _bloqueio("praca_ou_tipo_preco_fisico_ausente", serie_id=serie_id, classe=classe)
        if obs.get("natureza") not in ("OBSERVADO", "INFORMADO"):
            excluidos += 1
            continue
        u = obs.get("unidade")
        if not isinstance(u, str) or not u.strip():
            return _bloqueio("unidade_ausente", serie_id=serie_id, classe=classe)
        if unidade is None:
            unidade = u
        elif unidade != u:
            raise ErroMotor("serie com unidades diferentes")
        try:
            ref = date.fromisoformat(obs["data_referencia"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ErroMotor("data_referencia invalida") from exc
        coleta = _tempo(obs.get("data_coleta"))
        publicacao = _tempo(obs["data_publicacao"]) if obs.get("data_publicacao") else None
        if publicacao is None:
            excluidos += 1
            continue
        if coleta > momento or publicacao > momento or ref > momento.date():
            excluidos += 1
            continue
        valor = _decimal(obs.get("valor"), positivo=True)
        identificador = str(obs.get("identidade") or obs.get("fingerprint") or "")
        if not identificador:
            raise ErroMotor("observacao sem identidade de origem")
        key = (ref.isoformat(), identificador)
        if key not in revisoes or coleta > revisoes[key][0]:
            revisoes[key] = (coleta, valor)
    por_dia: dict[str, list[Decimal]] = {}
    for (dia, _), (_, valor) in revisoes.items():
        por_dia.setdefault(dia, []).append(valor)
    diaria = sorted((date.fromisoformat(k), max(v) if classe == "FRETE_ANUNCIADO"
                    else Decimal(str(median(v)))) for k, v in por_dia.items())
    if len(diaria) < minimo_dias or (diaria and (diaria[-1][0] - diaria[0][0]).days < 7):
        return _bloqueio("amostra_temporal_insuficiente", serie_id=serie_id, classe=classe,
                         dias_validos=len(diaria), registros_excluidos=excluidos)
    idade = (momento.date() - diaria[-1][0]).days
    prazo = 7 if classe == "FRETE_ANUNCIADO" else 5
    if idade > prazo:
        return _bloqueio("serie_defasada", serie_id=serie_id, classe=classe,
                         dias_desde_ultima_referencia=idade, registros_excluidos=excluidos)
    corte = len(diaria) // 2
    anterior = Decimal(str(median([v for _, v in diaria[:corte]])))
    atual = Decimal(str(median([v for _, v in diaria[corte:]])))
    variacao = (atual / anterior - 1) * 100
    estado = "ALTA" if variacao >= limite else "BAIXA" if variacao <= -limite else "ESTABILIDADE"
    return {
        "status": "SHADOW_READY", "publicavel": False, "serie_id": serie_id,
        "classe": classe, "unidade": unidade, "tendencia": estado,
        "variacao_pct": str(round(variacao, 4)),
        "dias_validos": len(diaria), "data_mais_recente": diaria[-1][0].isoformat(),
        "registros_excluidos": excluidos, "natureza_resultado": "INFERIDO",
        "metodologia": "MEDIANAS_METADES_V1_SEM_PREVISAO",
        "regra_intradia": "MAIOR_ANUNCIO_MESMAS_CONDICOES" if classe == "FRETE_ANUNCIADO"
                         else "MEDIANA_DIA",
    }


def pressao_portuaria(snapshot: dict, *, as_of: str, historico_minimo: int = 30) -> dict:
    """Indice sombra de fila baseado em AIS e historico do MESMO porto.

    Line-up pode ajudar a contextualizar mas nunca comprova carga, operacao ou DUV.
    Nao chamar funcao com contagens duplicadas por mensagens AIS.
    """
    momento = _tempo(as_of)
    if not isinstance(snapshot, dict):
        raise ErroMotor("snapshot portuario deve ser objeto")
    porto = snapshot.get("porto_id")
    if not isinstance(porto, str) or not porto.strip():
        raise ErroMotor("porto_id obrigatorio")
    idade = momento - _tempo(snapshot.get("data_referencia"))
    if idade < timedelta(0):
        raise ErroMotor("snapshot AIS futuro")
    fila = _inteiro(snapshot.get("navios_aguardando"))
    aproximando = _inteiro(snapshot.get("navios_aproximando"))
    atracados = _inteiro(snapshot.get("navios_atracados"))
    if type(historico_minimo) is not int or not 10 <= historico_minimo <= 365:
        raise ErroMotor("historico_minimo invalido")
    historico = snapshot.get("historico_navios_aguardando", [])
    if not isinstance(historico, list) or len(historico) > 20000:
        raise ErroMotor("historico fora do limite")
    valores = [_inteiro(v) for v in historico]
    motivos = []
    if idade > timedelta(hours=6):
        motivos.append("snapshot_ais_defasado")
    if not snapshot.get("geocercas_validadas"):
        motivos.append("geocercas_pendentes")
    if not snapshot.get("mmsi_unicos"):
        motivos.append("mmsi_nao_deduplicados")
    if not snapshot.get("fonte_ais"):
        motivos.append("fonte_ais_ausente")
    cobertura = _decimal(snapshot.get("conciliacao_ais_operacao", 0))
    if cobertura < Decimal("0.95") or cobertura > 1:
        motivos.append("conciliacao_inferior_95_pct")
    if len(valores) < historico_minimo:
        motivos.append("historico_insuficiente")
    lineup_validado = snapshot.get("lineup_validado") is True
    if snapshot.get("lineup_72h") is not None:
        _inteiro(snapshot["lineup_72h"])
    if motivos:
        return {"status": "DADOS_INSUFICIENTES", "publicavel": False, "porto_id": porto,
                "motivos": motivos, "navios_aguardando_ais": fila,
                "lineup_utilizado": False, "indice_pressao": None}
    percentil = Decimal(sum(1 for n in valores if n <= fila)) / Decimal(len(valores)) * 100
    pressao = (percentil * Decimal("0.70") +
               min(Decimal(100), Decimal(aproximando) * 10) * Decimal("0.20") +
               min(Decimal(100), Decimal(atracados) * 12) * Decimal("0.10"))
    return {
        "status": "SHADOW_READY", "publicavel": False, "porto_id": porto,
        "navios_aguardando_ais": fila, "navios_aproximando_ais": aproximando,
        "indice_pressao": str(round(pressao, 2)),
        "percentil_historico": str(round(percentil, 2)),
        "lineup_utilizado": False,
        "lineup_72h_informado": snapshot.get("lineup_72h") if lineup_validado else None,
        "lineup_status": "CONTEXTUAL_VALIDADO" if lineup_validado else "NAO_CONFIAVEL_OU_AUSENTE",
        "natureza_resultado": "INFERIDO", "metodologia": "PRESSAO_AIS_SOMBRA_V1",
        "nota": "Indice derivado; nao e volume de carga, tempo real de espera ou navios oficialmente operados.",
    }


def resumo_logistico(relatorio_corredores: dict | None) -> dict:
    """Preserva escopo MDF-e; nao soma modais nem identifica terminal por localidade."""
    if relatorio_corredores is None:
        return _bloqueio("sem_recorte_mdfe", polos=[])
    if not isinstance(relatorio_corredores, dict):
        raise ErroMotor("relatorio de corredores invalido")
    if relatorio_corredores.get("estado") != "RECORTE_IMPORTADO_NAO_HOMOLOGADO":
        return _bloqueio("corredores_nao_homologados_ou_sem_dados", polos=[])
    polos = relatorio_corredores.get("resumo_polos", [])
    if not isinstance(polos, list):
        raise ErroMotor("resumo_polos invalido")
    return {
        "status": "SHADOW_READY", "publicavel": False,
        "recorte": relatorio_corredores.get("recorte"),
        "competencia": relatorio_corredores.get("competencia"),
        "fonte_sha256": relatorio_corredores.get("sha256_origem"),
        "polos": polos[:20], "polos_truncados": len(polos) > 20,
        "natureza_resultado": "INFERIDO",
        "restricao": "Somente MDF-e no recorte; nao atribuir transbordo ou somar com TU ferroviario/ANTAQ.",
    }


def montar_painel(pacote: dict, *, as_of: str) -> dict:
    """Um comando gera visao integrada com estados independentes, sem mesclar universos."""
    momento = _tempo(as_of)
    if not isinstance(pacote, dict):
        raise ErroMotor("pacote deve ser objeto")
    portos = pacote.get("portos", [])
    series = pacote.get("series", [])
    if not isinstance(portos, list) or len(portos) > 25:
        raise ErroMotor("lista de portos invalida")
    if not isinstance(series, list) or len(series) > 50:
        raise ErroMotor("lista de series invalida")
    if len({p.get("porto_id") for p in portos if isinstance(p, dict)}) != len(portos):
        raise ErroMotor("porto duplicado no pacote")
    from .maritimo_painel_avancado import avaliar_porto_avancado
    from .dinamica_mercados_pit import avaliar_dinamica_historica

    def avaliar_serie(s):
        base = tendencia_precos(s.get("observacoes", []), classe=s["classe"],
                               serie_id=s["serie_id"], as_of=as_of)
        # Dinamica com identidade econômica e banda explicita do dado
        # original. Nunca substituir estatistica descritiva por probabilidade.
        return {**base, "dinamica_historica": avaliar_dinamica_historica(
            s.get("observacoes", []), classe=s["classe"],
            serie_id=s["serie_id"], as_of=as_of)}

    def avaliar_porto(p):
        base = pressao_portuaria(p, as_of=as_of)
        return {**base, "avancado": avaliar_porto_avancado(p, as_of=as_of, pressao=base)}

    return {
        "status": "ANALISE_SHADOW_NAO_HOMOLOGADA",
        "as_of": momento.isoformat(),
        "logistica": resumo_logistico(pacote.get("corredores")),
        "maritimo": [avaliar_porto(p) for p in portos],
        "quantitativo": [avaliar_serie(s) for s in series],
        "restricoes": [
            "Nenhum numero representa frete negociado, transbordo confirmado ou embarque realizado.",
            "Nenhum indice shadow autoriza publicacao operacional ou previsao calibrada.",
            "BigQuery/GCS sao entradas potenciais: execucao cloud depende de coletores e permissao real.",
        ],
    }
