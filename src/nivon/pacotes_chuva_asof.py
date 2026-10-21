"""Ponte offline RAW forecast -> observação -> verificação de chuva as-of.

Nunca lê rede, completa períodos faltantes ou atesta arquivos retrospec-
tivamente. Um snapshot = um intervalo de previsão/observação. SHA vincula
bytes ao manifesto; comprovantes históricos externos continuam obrigatórios.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from math import isfinite

from .verificacao_chuva_ensemble_asof import (
    ErroVerificacaoChuva, verificar_chuva_ensemble_asof,
)


class ErroPacoteChuva(ValueError):
    pass


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FONTE = re.compile(r"[A-Z][A-Z0-9_]{2,90}\Z")
_PREVISOES = frozenset({"NOAA_GFS", "ECMWF_MODELOS", "CPTEC_MERGE"})
_OBSERVACOES = frozenset({"INMET_ESTACOES", "ANA_HIDRO"})
_MANIFESTO = frozenset({
    "dataset_id", "fonte_id", "sha256", "capturado_em",
    "classe", "prova_disponibilidade_sha256",
})
_PREVISAO = frozenset({
    "estacao_id", "produto_id", "versao_produto", "emitido_em",
    "previsao_publicada_em", "features_publicadas_ate",
    "climatologia_publicada_em", "valido_em", "membros_mm",
    "prob_climatologica",
})
_OBSERVACAO = frozenset({
    "estacao_id", "inicio_intervalo_em", "fim_intervalo_em",
    "observado_mm", "qc", "qc_evidencia_sha256", "obs_publicado_em",
})


def _t(value, label):
    if not isinstance(value, str) or "T" not in value:
        raise ErroPacoteChuva(label + ": timestamp com fuso obrigatório")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPacoteChuva(label + ": timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroPacoteChuva(label + ": fuso ausente")
    return dt.astimezone(timezone.utc)


def _sha(value, label):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ErroPacoteChuva(label + ": SHA-256 obrigatório")
    return value


def _numero(value, label, lo=0, hi=5000):
    if type(value) not in (int, float) or not isfinite(value) or not lo <= value <= hi:
        raise ErroPacoteChuva(label + ": valor numérico fora do contrato")
    return float(value)


def _ident(value, label):
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 120:
        raise ErroPacoteChuva(label + ": identificador inválido")
    return value


def _parse_snapshot(item, *, kind, catalogo, direitos_ref, autorizacoes):
    if not isinstance(item, dict) or set(item) != {"manifesto", "bytes_json"}:
        raise ErroPacoteChuva("snapshot requer bytes RAW e manifesto explícitos")
    raw = item["bytes_json"]
    meta = item["manifesto"]
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 250_000:
        raise ErroPacoteChuva("snapshot RAW ausente ou acima do limite")
    if not isinstance(meta, dict) or set(meta) != _MANIFESTO:
        raise ErroPacoteChuva("manifesto incompleto ou ambíguo")
    ds = meta["dataset_id"]
    if ds not in (_PREVISOES if kind == "PREVISAO" else _OBSERVACOES):
        raise ErroPacoteChuva("dataset inadequado à natureza dos dados")
    source = meta["fonte_id"]
    if not isinstance(source, str) or not _FONTE.fullmatch(source):
        raise ErroPacoteChuva("fonte não canônica")
    sha = _sha(meta["sha256"], "arquivo bruto")
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ErroPacoteChuva("hash RAW difere do manifesto")
    _sha(meta["prova_disponibilidade_sha256"], "prova externa de disponibilidade")
    capture = _t(meta["capturado_em"], "captura")
    classe = meta["classe"]
    if classe not in ("SINTETICO", "REAL_AUTORIZADO"):
        raise ErroPacoteChuva("classe de aquisição desconhecida")
    if classe == "REAL_AUTORIZADO":
        if (not isinstance(catalogo, dict) or
            not isinstance(catalogo.get("datasets"), list)):
            raise PermissionError("catálogo aprovado obrigatório para dado real")
        matches = [d for d in catalogo["datasets"] if d.get("id") == ds]
        if (len(matches) != 1 or matches[0].get("source_id") != source or
            matches[0].get("enabled") is not True or
            matches[0].get("collection_authorized") is not True or
            not {"COLETA", "ARMAZENAMENTO", "PESQUISA"}.issubset(autorizacoes) or
            not isinstance(direitos_ref, str) or len(direitos_ref.strip()) < 8):
            raise PermissionError("fonte real não homologada para coleta/armazenamento/pesquisa")
    elif direitos_ref is not None or autorizacoes:
        raise ErroPacoteChuva("fixture sintética não admite direitos reais")
    def no_duplicate_keys(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ErroPacoteChuva("JSON RAW com chave duplicada")
            obj[k] = v
        return obj
    try:
        data = json.loads(raw.decode("utf-8-sig"),
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ErroPacoteChuva("NaN/Infinity JSON proibidos")),
                          object_pairs_hook=no_duplicate_keys)
    except (UnicodeError, ValueError) as exc:
        raise ErroPacoteChuva("JSON RAW inválido") from exc
    if not isinstance(data, dict) or set(data) != {"registro"} or not isinstance(data["registro"], dict):
        raise ErroPacoteChuva("snapshot deve conter um registro normalizado")
    row = data["registro"]
    if set(row) != (_PREVISAO if kind == "PREVISAO" else _OBSERVACAO):
        raise ErroPacoteChuva("registro fora do contrato da fonte")
    return row, capture, sha, ds, classe


def montar_e_verificar_pares_chuva(
    *, snapshots_previsao, snapshots_observacao, estacao_id,
    produto_id, versao_produto, horizonte_horas, acumulacao_horas,
    passo_horas, limiar_evento_mm, fonte_climatologia,
    catalogo=None, autorizacoes=frozenset(), direitos_ref=None,
):
    """Monta pares com RAW conferido e executa verificador probabilístico.

    O adapter NÃO interpreta arquivo bruto de estação: recebe intervalos já
    normalizados e com QC externo; dados INMET horários brutos exigem parser,
    convenção intervalar e atestado de sensor antes desta etapa. Para séries
    reais, catálogo operacional, direitos por operação e atestados externos
    constituem pré-condições; mesmo assim homologado permanece falso.
    """
    for label, val in (("estação", estacao_id), ("produto", produto_id),
                       ("versão", versao_produto), ("climatologia", fonte_climatologia)):
        _ident(val, label)
    w = _numero(acumulacao_horas, "janela em horas", 1/60, 720)
    if not isinstance(autorizacoes, (set, frozenset)):
        raise ErroPacoteChuva("conjunto de permissões inválido")
    if (not isinstance(snapshots_previsao, (list, tuple)) or
        not isinstance(snapshots_observacao, (list, tuple)) or
        not 30 <= len(snapshots_previsao) <= 5000 or
        not 30 <= len(snapshots_observacao) <= 5000):
        raise ErroPacoteChuva("30 a 5000 snapshots de cada natureza obrigatórios")
    forecast = {}
    observed = {}
    sha_refs = set()
    classes = set()
    fontes_previsao = set()
    fontes_obs = set()
    for kind, snapshots, destination, source_ids in (
        ("PREVISAO", snapshots_previsao, forecast, fontes_previsao),
        ("OBSERVACAO", snapshots_observacao, observed, fontes_obs),
    ):
        for item in snapshots:
            row, captured, sha, ds, classe = _parse_snapshot(
                item, kind=kind, catalogo=catalogo,
                autorizacoes=autorizacoes, direitos_ref=direitos_ref)
            if (ds, sha) in sha_refs:
                raise ErroPacoteChuva("snapshot duplicado; preservar uma vintage por intervalo")
            sha_refs.add((ds, sha))
            classes.add(classe)
            source_ids.add(ds)
            if row["estacao_id"] != estacao_id:
                raise ErroPacoteChuva("estação da observação ou previsão divergente")
            if kind == "PREVISAO":
                if (row["produto_id"] != produto_id or
                    row["versao_produto"] != versao_produto):
                    raise ErroPacoteChuva("produto/versão de previsão heterogêneo")
                issued = _t(row["emitido_em"], "emissão")
                published = _t(row["previsao_publicada_em"], "publicação do forecast")
                features = _t(row["features_publicadas_ate"], "features")
                climate = _t(row["climatologia_publicada_em"], "climatologia")
                valid = _t(row["valido_em"], "validade")
                if not features <= issued <= published <= captured <= valid - timedelta(hours=w):
                    raise ErroPacoteChuva("previsão não estava capturada antes do intervalo")
                if climate > captured:
                    raise ErroPacoteChuva("baseline climatológico publicado depois da captura")
                if not isinstance(row["membros_mm"], list) or not 3 <= len(row["membros_mm"]) <= 100:
                    raise ErroPacoteChuva("membros ausentes ou excessivos")
                for member in row["membros_mm"]:
                    _numero(member, "membro chuva")
                _numero(row["prob_climatologica"], "prob climatologia", 0, 1)
                key = valid
            else:
                start = _t(row["inicio_intervalo_em"], "início intervalo observado")
                valid = _t(row["fim_intervalo_em"], "fim intervalo observado")
                publication = _t(row["obs_publicado_em"], "publicação observada")
                if abs((valid - start).total_seconds()/3600 - w) > 1e-6:
                    raise ErroPacoteChuva("observação não cobre a mesma duração")
                if not valid <= publication <= captured:
                    raise ErroPacoteChuva("observação coletada antes de publicada/medida")
                _numero(row["observado_mm"], "chuva observada")
                _sha(row["qc_evidencia_sha256"], "QC externo da estação")
                if row["qc"] != "APROVADO":
                    raise ErroPacoteChuva("sem QC de estação aprovado externamente")
                key = valid
            if key in destination:
                raise ErroPacoteChuva("múltiplas vintages/edições para mesmo período sem seleção auditada")
            destination[key] = (row, captured, sha)
    if len(classes) != 1 or len(fontes_previsao) != 1 or len(fontes_obs) != 1:
        raise ErroPacoteChuva("classes ou datasets misturados")
    if set(forecast) != set(observed):
        raise ErroPacoteChuva("pontos não pareados; não preencher lacunas ou descartar silenciosamente")
    records = []
    for valid in sorted(forecast):
        f, fc, fs = forecast[valid]
        o, oc, os = observed[valid]
        rec = {
            "estacao_id": estacao_id, "produto_id": produto_id,
            "versao_produto": versao_produto,
            "suporte_temporal": "ACUMULADO_INTERVALO",
            "emitido_em": f["emitido_em"],
            "previsao_publicada_em": f["previsao_publicada_em"],
            "previsao_coletada_em": fc.isoformat(),
            "features_publicadas_ate": f["features_publicadas_ate"],
            "valido_em": valid.isoformat(),
            "obs_publicado_em": o["obs_publicado_em"],
            "obs_coletado_em": oc.isoformat(),
            "climatologia_publicada_em": f["climatologia_publicada_em"],
            "observado_mm": o["observado_mm"],
            "membros_mm": f["membros_mm"],
            "prob_climatologica": f["prob_climatologica"],
            "qc": "APROVADO", "modo_validacao": "FORA_AMOSTRA",
        }
        records.append(rec)
    try:
        metrics = verificar_chuva_ensemble_asof(
            registros=records, estacao_id=estacao_id,
            produto_id=produto_id, versao_produto=versao_produto,
            horizonte_horas=horizonte_horas, acumulacao_horas=acumulacao_horas,
            passo_horas=passo_horas, limiar_evento_mm=limiar_evento_mm,
            fonte_observacao=next(iter(fontes_obs)),
            fonte_climatologia=fonte_climatologia,
        )
    except ErroVerificacaoChuva as exc:
        raise ErroPacoteChuva("pares RAW não aprovados no verificador científico") from exc
    return {
        "avaliacao": metrics,
        "pacotes_raw_verificados_por_hash": len(sha_refs),
        "snapshots_previsao": len(forecast),
        "snapshots_observacao": len(observed),
        "sha256_previsoes": [forecast[k][2] for k in sorted(forecast)],
        "sha256_observacoes": [observed[k][2] for k in sorted(observed)],
        "classe_entrada": next(iter(classes)),
        "prova_externa_vintages_validada": False,
        "qc_instrumental_validado_independentemente": False,
        "holdout_validado_independentemente": False,
        "homologado": False,
        "classificacao": "JOIN_OFFLINE_RAW_HASH_ASOF_NAO_HOMOLOGADO",
    }
