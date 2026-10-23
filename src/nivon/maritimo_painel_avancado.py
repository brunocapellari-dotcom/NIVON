"""Enriquecimento maritime SHADOW: reutiliza motores do NIVON Maritime.

Nao converte geolocalizacao AIS em operacao concluida e nunca atribui
frete, carga/tonelagem, DUV, terminal ou navio operador ao contexto AIS.
Nao altera scores ja publicados pelo contrato do painel operacional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

from .maritime.maritime_queue import QueueSnapshot, evaluate_queue_pressure
from .maritime.maritime_queue_forecast import forecast_queue
from .maritime.maritime_source_health import assess_source_health
from .painel_operacional import ErroMotor, _inteiro, _tempo


HORIZONTES = (6, 24, 48)


def _medida(valor):
    if isinstance(valor, bool):
        raise ErroMotor("medida booleana invalida")
    try:
        x = float(valor)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ErroMotor("medida de fila invalida") from exc
    if not isfinite(x) or x < 0:
        raise ErroMotor("medida de fila negativa ou nao-finita")
    return x


def _lista_numerica(valor, *, maximo=10000):
    if not isinstance(valor, list) or len(valor) > maximo:
        raise ErroMotor("amostra de fila invalida")
    return [_medida(x) for x in valor]


def _chegadas_acumuladas(valores):
    if not isinstance(valores, dict) or set(valores) != {"6", "24", "48"}:
        raise ErroMotor("chegadas previstas devem cobrir exatamente 6, 24 e 48h")
    numeros = [_medida(valores[str(h)]) for h in HORIZONTES]
    if numeros != sorted(numeros):
        raise ErroMotor("chegadas acumuladas nao podem decrescer")
    return dict(zip(HORIZONTES, numeros))


def avaliar_porto_avancado(snapshot: dict, *, as_of: str, pressao: dict) -> dict:
    """Executa saude de coletor, VQI e forecast usando dados do mesmo porto.

    Sem confirmacao independente da integridade do coletor, sem historico
    suficiente ou sem dados observados de taxa de atendimento => falha fechada.
    """
    _tempo(as_of)
    if not isinstance(snapshot, dict) or not isinstance(pressao, dict):
        raise ErroMotor("snapshot/pressao invalido")
    if pressao.get("porto_id") != snapshot.get("porto_id"):
        raise ErroMotor("porto divergente entre contexto e pressao")
    saude = snapshot.get("saude_coletor")
    status_saude = "NAO_INFORMADA"
    dados_saude = None
    if saude is not None:
        if not isinstance(saude, dict):
            raise ErroMotor("saude_coletor invalida")
        intervalo = _medida(saude.get("intervalo_esperado_minutos"))
        if intervalo < 1 or intervalo > 1440:
            raise ErroMotor("intervalo de coleta fora de 1..1440 minutos")
        for chave in ("ultimo_sucesso_em", "ultimo_registro_em", "ultimo_erro_em"):
            if saude.get(chave) is not None and _tempo(saude[chave]) > _tempo(as_of):
                raise ErroMotor("telemetria de fonte posterior ao as_of")
        aval = assess_source_health(
            source_id=snapshot.get("fonte_ais") or "AIS_NAO_IDENTIFICADO",
            now=as_of, expected_interval_minutes=intervalo,
            last_success_at=saude.get("ultimo_sucesso_em"),
            last_record_at=saude.get("ultimo_registro_em"),
            last_error_at=saude.get("ultimo_erro_em"),
            source_mode="PERIODIC",
        )
        status_saude = aval.status
        dados_saude = aval.to_dict()

    aprovado = (pressao.get("status") == "SHADOW_READY"
                and status_saude == "FRESH")
    historico = _lista_numerica(snapshot.get("historico_navios_aguardando", []), maximo=20000)
    espera = _lista_numerica(snapshot.get("horas_espera_observadas", []))
    motivos = []
    if not aprovado:
        motivos.append("port_pressure_ou_telemetria_nao_validada")
    if not espera:
        motivos.append("amostra_espera_ausente")
    if len(historico) < 30:
        motivos.append("historico_fila_insuficiente")

    # A rotina original pode aceitar lineup como componente; em NIVON ele e
    # apenas contexto e a componente quantitativa fica explicitamente ZERO.
    fila = QueueSnapshot(
        waiting_vessels=_inteiro(snapshot.get("navios_aguardando")),
        approaching_vessels=_inteiro(snapshot.get("navios_aproximando")),
        berthed_vessels=_inteiro(snapshot.get("navios_atracados")),
        waiting_hours=tuple(espera),
        lineup_next_72h=0,
    )
    indicador = evaluate_queue_pressure(
        fila, historical_waiting_counts=historico,
        geofences_validated=aprovado and not motivos,
        source_fresh=aprovado and not motivos,
        minimum_history_points=30,
    )
    # Ausencia de dados de chegadas/taxas nunca vira previsao de fluxo zero.
    servico = snapshot.get("taxas_atendimento_observadas_h")
    chegadas = snapshot.get("chegadas_acumuladas_previstas")
    taxas = _lista_numerica(servico) if servico is not None else []
    chegada_num = _chegadas_acumuladas(chegadas) if chegadas is not None else {}
    if not taxas or not chegada_num:
        motivos.append("chegadas_ou_taxas_atendimento_ausentes")
    previsao = forecast_queue(
        current_waiting=fila.waiting_vessels,
        arrivals_by_horizon=chegada_num,
        historical_service_rates_per_hour=taxas,
        geofences_validated=aprovado and not motivos,
        source_fresh=aprovado and not motivos,
        horizons=HORIZONTES,
        minimum_service_samples=30,
    )
    return {
        "status": "SHADOW_READY" if (indicador.status == "SHADOW_READY"
                                   or previsao.status == "SHADOW_READY") else "DATA_GATED",
        "publicavel": False,
        "saude_fonte_ais": dados_saude,
        "status_saude_fonte": status_saude,
        "vqi": indicador.to_dict(),
        "fila_6_24_48h": previsao.to_dict(),
        "regras": {
            "lineup_entrou_no_score": False,
            "operacao_concluida_inferida": False,
            "previsao_calibrada": False,
            "tempo_espera_ais_requer_validacao": True,
        },
        "motivos_bloqueio": sorted(set(motivos)),
    }
