"""Adaptador offline para o agregado diário do parser horário INMET (PR #9).

Compatibiliza SOMENTE o contrato de saída do parser, sem duplicá-lo.
Cada dia agregado requer convenção física da hora e relatório QC explícitos.
O adaptador nunca promove o QC intrínseco, autoriza coleta ou comprova
independência de uma auditoria externa.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from math import isfinite

from .pacotes_chuva_asof import ErroPacoteChuva, _sha, _t


class ErroAdaptadorINMET(ErroPacoteChuva):
    pass


_CODIGO = re.compile(r"A[0-9]{3,5}\Z")
_QC_FIELDS = frozenset({
    "estacao_id", "data_rotulo_utc", "raw_csv_sha256",
    "convencao_hora", "referencia_convencao",
    "resultado", "validado_em", "auditor_id",
})


def _json_relatorio(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 100_000:
        raise ErroAdaptadorINMET("relatório QC ausente/excessivo")
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ErroAdaptadorINMET("relatório QC com chave duplicada")
            out[k] = v
        return out
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              ErroAdaptadorINMET("NaN/Infinity em QC")))
    except (UnicodeError, ValueError) as exc:
        raise ErroAdaptadorINMET("relatório QC JSON inválido") from exc
    if not isinstance(data, dict) or set(data) != _QC_FIELDS:
        raise ErroAdaptadorINMET("relatório QC sem contrato completo")
    return data


def converter_dia_inmet_para_snapshot(
    *, agregado, data_rotulo_utc, convencao_hora, relatorio_qc_bytes,
    observacao_publicada_em, qc_publicado_em, coletado_em,
    prova_disponibilidade_sha256, classe="SINTETICO",
):
    """Converte UM dia com 24 horas INMET para pacote do verificador as-of.

    O pacote deve ser saída de agregar_dias_inmet da PR #9; sua classe ainda
    será declarada NAO_HOMOLOGADO. O horário físico só é atribuído com
    convenção exógena de início/fim do intervalo horário e QC rastreável.
    """
    if (not isinstance(agregado, dict) or
        agregado.get("dataset_id") != "INMET_ESTACOES" or
        agregado.get("status") != "DIARIO_PRELIMINAR_NAO_HOMOLOGADO" or
        agregado.get("liberacao_preditiva") is not False):
        raise ErroAdaptadorINMET("somente agregado diário bruto não homologado")
    station = agregado.get("estacao")
    if not isinstance(station, str) or not _CODIGO.fullmatch(station):
        raise ErroAdaptadorINMET("código WMO INMET obrigatório")
    csv_sha = _sha(agregado.get("raw_sha256"), "CSV fonte")
    if type(classe) is not str or classe not in ("SINTETICO", "REAL_AUTORIZADO"):
        raise ErroAdaptadorINMET("classe de aquisição inválida")
    if convencao_hora not in ("FIM_INTERVALO", "INICIO_INTERVALO"):
        raise ErroAdaptadorINMET("convenção física da hora não confirmada")
    evidence = agregado.get("referencia_convencao")
    if not isinstance(evidence, str) or len(evidence.strip()) < 12:
        raise ErroAdaptadorINMET("referência documental de convenção obrigatória")
    try:
        d = date.fromisoformat(data_rotulo_utc)
    except (ValueError, TypeError) as exc:
        raise ErroAdaptadorINMET("data UTC do agregado inválida") from exc
    if not isinstance(agregado.get("dias"), list):
        raise ErroAdaptadorINMET("lista de dias inválida")
    matched = [x for x in agregado["dias"] if isinstance(x, dict) and x.get("data_utc") == data_rotulo_utc]
    if len(matched) != 1:
        raise ErroAdaptadorINMET("dia não único ou não encontrado no agregado")
    row = matched[0]
    if (type(row.get("horas_encontradas")) is not int or row["horas_encontradas"] != 24 or
        type(row.get("horas_chuva_validas")) is not int or row["horas_chuva_validas"] != 24 or
        row.get("convencao_intervalo_confirmada") is not True or
        row.get("comparacao_grade_permitida") is not True or
        row.get("qc_sensor") != "NAO_HOMOLOGADO" or
        row.get("classificacao") != "AGREGACAO_ESTACAO_SEM_QC"):
        raise ErroAdaptadorINMET("cobertura incompleta, convenção ou QC de base inválidos")
    rain = row.get("chuva_rotulo_utc_mm")
    if type(rain) not in (int, float) or not isfinite(rain) or not 0 <= rain <= 1000:
        raise ErroAdaptadorINMET("chuva ausente ou fisicamente suspeita")

    qc = _json_relatorio(relatorio_qc_bytes)
    if (qc["estacao_id"] != station or qc["data_rotulo_utc"] != data_rotulo_utc or
        qc["raw_csv_sha256"] != csv_sha or qc["convencao_hora"] != convencao_hora or
        qc["referencia_convencao"] != evidence or qc["resultado"] != "APROVADO" or
        not isinstance(qc["auditor_id"], str) or
        not 4 <= len(qc["auditor_id"].strip()) <= 120):
        raise ErroAdaptadorINMET("atestado de QC não corresponde ao arquivo/estação/intervalo")

    anchor = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if convencao_hora == "FIM_INTERVALO":
        interval_end = anchor + timedelta(hours=23)
        interval_start = interval_end - timedelta(hours=24)
    else:
        interval_start = anchor
        interval_end = anchor + timedelta(hours=24)

    published = _t(observacao_publicada_em, "publicação original observação")
    qc_validated = _t(qc["validado_em"], "validação QC")
    qc_published = _t(qc_publicado_em, "publicação QC")
    capture = _t(coletado_em, "captura pacote")
    if not (interval_end <= published <= capture and
            interval_end <= qc_validated <= qc_published <= capture):
        raise ErroAdaptadorINMET("QC ou observação não estavam disponíveis na coleta")
    proof_hash = _sha(prova_disponibilidade_sha256, "prova de disponibilidade")
    latest_pub = max(published, qc_published)
    qc_hash = hashlib.sha256(relatorio_qc_bytes).hexdigest()
    normalized = {
        "estacao_id": "INMET_" + station,
        "inicio_intervalo_em": interval_start.isoformat(),
        "fim_intervalo_em": interval_end.isoformat(),
        "observado_mm": float(rain),
        "qc": "APROVADO",
        "qc_evidencia_sha256": qc_hash,
        "obs_publicado_em": latest_pub.isoformat(),
    }
    raw = json.dumps({"registro": normalized}, sort_keys=True,
                     separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    snapshot = {
        "manifesto": {
            "dataset_id": "INMET_ESTACOES", "fonte_id": "INMET",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "capturado_em": capture.isoformat(),
            "classe": classe,
            "prova_disponibilidade_sha256": proof_hash,
        },
        "bytes_json": raw,
    }
    return {
        "snapshot": snapshot,
        "data_rotulo_utc": data_rotulo_utc,
        "convencao_hora": convencao_hora,
        "periodo_fisico_inicio_utc": interval_start.isoformat(),
        "periodo_fisico_fim_utc": interval_end.isoformat(),
        "csv_bruto_sha256": csv_sha,
        "relatorio_qc_sha256": qc_hash,
        "qc_relatorio_autenticado_externamente": False,
        "disponibilidade_historica_atestada_externamente": False,
        "homologado": False,
        "estado": "NORMALIZACAO_INMET_INTERVALO_QC_DECLARADO_OFFLINE",
    }
