"""NIVON hydrologic ensemble: forecast RAIN -> SCS-CN -> unit hydrograph.

Pure CPU math. Does NOT forecast rainfall itself, assign a stage to a river,
infer navigability, download from a forecast provider or publish an alert.
Probability counts are scenario frequencies, NOT calibrated flood risk.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import mean
from .hidrograma_bacia import hidrograma_evento_cn, ErroHidrograma


class ErroEnsembleBacia(ValueError):
    pass


def _time(value: str, label: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ErroEnsembleBacia(label + ": timestamp ISO com fuso obrigatório")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroEnsembleBacia(label + ": timestamp inválido") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ErroEnsembleBacia(label + ": fuso não informado")
    return result.astimezone(timezone.utc)


def _finite(value, label, minimum=None, maximum=None):
    if type(value) not in (float, int) or not isfinite(value):
        raise ErroEnsembleBacia(label + ": número finito obrigatório")
    x = float(value)
    if minimum is not None and x < minimum or maximum is not None and x > maximum:
        raise ErroEnsembleBacia(label + ": fora dos limites físicos")
    return x


def _quantil_linear(ordenados: list[float], p: float) -> float:
    if not ordenados:
        raise ErroEnsembleBacia("nenhum membro disponível")
    at = (len(ordenados) - 1) * p
    k = int(at)
    if k == len(ordenados) - 1:
        return ordenados[k]
    return ordenados[k] + (at - k) * (ordenados[k + 1] - ordenados[k])


def cenario_ensemble_bacia(
    *, membros_chuva: list[dict], emitido_em: str, dados_publicados_ate: str,
    passo_horas: float, area_bacia_km2: float, numero_curva: float,
    fracao_abstracao_inicial: float, resposta_unitaria_pesos: list[float],
    limiar_pico_direto_m3_s: float, bacia_id: str,
    fonte_modelo_chuva: str, fonte_cn: str, fonte_resposta_unitaria: str,
    fonte_limiar: str,
) -> dict:
    """Run each weather-member rainfall path through SAME hydrology parameters.

    Rainfall must already have been converted to areal average for this
    catchment, with appropriate geospatial provenance. This is a conditional
    scenario, not an operational river flow forecast.
    """
    issued = _time(emitido_em, "emissão")
    latest = _time(dados_publicados_ate, "vintage dos dados")
    if latest > issued:
        raise ErroEnsembleBacia("features foram publicadas após a previsão")
    for label, value in (
        ("bacia", bacia_id), ("modelo de chuva", fonte_modelo_chuva),
        ("fonte CN", fonte_cn), ("hidrograma unitário", fonte_resposta_unitaria),
        ("fonte do limiar", fonte_limiar),
    ):
        if not isinstance(value, str) or not 8 <= len(value.strip()) <= 250:
            raise ErroEnsembleBacia(label + ": identificador/evidência obrigatório")
    threshold = _finite(limiar_pico_direto_m3_s, "limiar de vazão direta", 0, 1e9)
    step = _finite(passo_horas, "passo", 1/60, 72)
    if not isinstance(membros_chuva, (list, tuple)) or not 3 <= len(membros_chuva) <= 200:
        raise ErroEnsembleBacia("precisa de 3 a 200 membros meteorológicos")
    members = []
    ids = set()
    reference_times = None
    for member in membros_chuva:
        if not isinstance(member, dict) or set(member) != {"membro_id", "chuva_intervalos"}:
            raise ErroEnsembleBacia("membro fora do contrato")
        ident = member["membro_id"]
        if not isinstance(ident, str) or not 1 <= len(ident) <= 80 or ident in ids:
            raise ErroEnsembleBacia("identificador de membro inválido/duplicado")
        ids.add(ident)
        path = member["chuva_intervalos"]
        if not isinstance(path, (list, tuple)) or not 2 <= len(path) <= 5000:
            raise ErroEnsembleBacia("chuva de membro ausente")
        times = tuple(_time(row.get("data_hora"), "passo futuro") if isinstance(row, dict)
                      else _time(None, "passo futuro") for row in path)
        if times[0] <= issued:
            raise ErroEnsembleBacia("chuva futura começa antes da emissão")
        if reference_times is None:
            reference_times = times
        elif times != reference_times:
            raise ErroEnsembleBacia("membros não têm os mesmos horários e horizonte")
        try:
            hydro = hidrograma_evento_cn(
                chuva_intervalos=path, passo_horas=step,
                numero_curva=numero_curva, area_bacia_km2=area_bacia_km2,
                fracao_abstracao_inicial=fracao_abstracao_inicial,
                resposta_unitaria_pesos=resposta_unitaria_pesos,
                fonte_chuva=fonte_modelo_chuva, fonte_cn=fonte_cn,
                fonte_resposta_unitaria=fonte_resposta_unitaria,
                bacia_id=bacia_id,
            )
        except ErroHidrograma as exc:
            raise ErroEnsembleBacia("membro de chuva ou hidrograma inválido") from exc
        members.append({
            "membro_id": ident,
            "pico_vazao_direta_m3_s": hydro["vazao_pico_direta_m3_s"],
            "volume_direto_m3": hydro["volume_hidrograma_m3"],
            "chuva_evento_mm": hydro["chuva_total_evento_mm"],
            "horario_pico_utc": next(
                r["data_hora_utc"] for r in hydro["hydrograma"]
                if r["vazao_direta_m3_s"] == hydro["vazao_pico_direta_m3_s"]
            ),
            "hidrograma": hydro["hydrograma"],
        })
    peaks = sorted(r["pico_vazao_direta_m3_s"] for r in members)
    totals = sorted(r["volume_direto_m3"] for r in members)
    n = len(peaks)
    probability = sum(p >= threshold for p in peaks) / n
    if all(x == peaks[0] for x in peaks):
        ensemble_status = "SEM_DISPERSAO_IDENTIFICADA"
    else:
        ensemble_status = "DISPERSAO_CENARIOS_NAO_CALIBRADA"
    return {
        "bacia_id": bacia_id,
        "emitido_em_utc": issued.isoformat(),
        "dados_publicados_ate_utc": latest.isoformat(),
        "primeiro_passo_utc": reference_times[0].isoformat(),
        "ultimo_passo_chuva_utc": reference_times[-1].isoformat(),
        "membros": n,
        "limiar_vazao_DIRETA_m3_s": threshold,
        "fracao_membros_pico_direto_acima_ou_igual_limiar": probability,
        "pico_direto_quantiles_m3_s": {
            "p10": _quantil_linear(peaks, .1),
            "p50": _quantil_linear(peaks, .5),
            "p90": _quantil_linear(peaks, .9),
        },
        "volume_direto_quantiles_m3": {
            "p10": _quantil_linear(totals, .1),
            "p50": _quantil_linear(totals, .5),
            "p90": _quantil_linear(totals, .9),
        },
        "pico_direto_media_m3_s": mean(peaks),
        "estado_ensemble": ensemble_status,
        "resultados_membros": members,
        "fontes": {
            "chuva": fonte_modelo_chuva, "CN": fonte_cn,
            "resposta_unitaria": fonte_resposta_unitaria, "limiar": fonte_limiar,
        },
        "classificacao": "CENARIOS_CONDICIONAIS_CHUVA_VAZAO_DIRETA",
        "probabilidade_calibrada": False,
        "alerta_hidrologico_oficial": False,
        "previsao_operacional_homologada": False,
        "limites": (
            "Fração de membros NÃO é probabilidade calibrada de cheia. "
            "Pico de escoamento direto de sub-bacia NÃO é vazão total do rio, "
            "cota, calado ou descarga na hidrovia. Exige chuva areal, CN, "
            "kernel e limiar por bacia calibrados, vazão de base, roteamento, "
            "vintages meteorológicas reais e validação retrospectiva."
        ),
    }
