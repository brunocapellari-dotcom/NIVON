"""Contexto climático MJO/RMM estritamente point-in-time (offline).

Associa índice OBSERVADO, nunca probabilidade de chuva, a horários de emissão
NWP. Só usa um snapshot publicado E capturado até cada emissão. Indexar
revisão baixada depois de uma emissão histórica seria vazamento temporal.
Nenhuma fonte real é ativada automaticamente.
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from hashlib import sha256
import re

from .mjo_rmm import normalizar_rmm_bom, ultimo_rmm_ate, RMMInvalido


class ErroContextoMJO(ValueError):
    pass


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_./:-]{3,120}\Z")


def _instant(value, label):
    if not isinstance(value, str) or "T" not in value:
        raise ErroContextoMJO(label + ": timestamp ISO com fuso obrigatório")
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroContextoMJO(label + ": timestamp inválido") from exc
    if v.tzinfo is None or v.utcoffset() is None:
        raise ErroContextoMJO(label + ": fuso obrigatório")
    return v.astimezone(timezone.utc)


def _hash(value, label):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ErroContextoMJO(label + ": SHA-256 inválido")
    return value


def indexar_contexto_mjo_asof(*, previsoes, snapshots_rmm, max_defasagem_dias=7):
    """Audita lista de emissões e as associa a observações RMM historizadas.

    Um snapshot: {texto, fonte_id='BOM_RMM', publicado_em, coletado_em,
    raw_sha256, tipo='SINTETICO', evidencia_disponibilidade_sha256}.
    Entrada real bloqueada enquanto BOM_RMM não tiver catálogo/licenças.
    Uma previsão: {previsao_id, emitido_em}. Cada saída contém no máximo
    um índice de diagnóstico, jamais uma feature aprovada ou forecast MJO.
    """
    if type(max_defasagem_dias) is not int or not 1 <= max_defasagem_dias <= 14:
        raise ErroContextoMJO("defasagem máxima precisa ser 1 a 14 dias")
    if (not isinstance(previsoes, (tuple, list)) or
        not 1 <= len(previsoes) <= 5000 or
        not isinstance(snapshots_rmm, (tuple, list)) or
        not 1 <= len(snapshots_rmm) <= 200):
        raise ErroContextoMJO("emissões ou snapshots fora do limite")
    prepared = []
    sha_known = set()
    snapshot_temporal = {}
    for item in snapshots_rmm:
        if not isinstance(item, dict) or set(item) != {
            "texto", "fonte_id", "publicado_em", "coletado_em", "raw_sha256",
            "tipo", "evidencia_disponibilidade_sha256"
        }:
            raise ErroContextoMJO("manifesto RMM incompleto ou ambíguo")
        if item["tipo"] != "SINTETICO":
            raise PermissionError(
                "BOM_RMM real não autorizado no catálogo; registrar fonte/licença antes"
            )
        if item["fonte_id"] != "BOM_RMM":
            raise ErroContextoMJO("mistura de índices BOM/CPC proibida")
        text = item["texto"]
        if not isinstance(text, str) or not 1 <= len(text) <= 4_000_000:
            raise ErroContextoMJO("texto RMM inválido ou excessivo")
        real_sha = sha256(text.encode("utf-8")).hexdigest()
        if _hash(item["raw_sha256"], "hash bruto") != real_sha:
            raise ErroContextoMJO("snapshot RMM sofreu alteração RAW")
        _hash(item["evidencia_disponibilidade_sha256"], "hash da evidência")
        published = _instant(item["publicado_em"], "publicação")
        captured = _instant(item["coletado_em"], "coleta")
        if published > captured:
            raise ErroContextoMJO("coleta anterior à publicação")
        # Mesmo hash pode ser recolhido em instantes diferentes; a primeira
        # aparição é a que define a elegibilidade histórica.
        unique = (real_sha, captured)
        if unique in sha_known:
            raise ErroContextoMJO("snapshot bruto e captura duplicados")
        sha_known.add(unique)
        same_instant = (published, captured)
        former = snapshot_temporal.get(same_instant)
        if former is not None and former != real_sha:
            raise ErroContextoMJO("edições conflitantes no mesmo horário de publicação e captura")
        snapshot_temporal[same_instant] = real_sha
        try:
            normalized = normalizar_rmm_bom(
                texto=text, publicado_em=published.isoformat(),
                coletado_em=captured.isoformat(),
                licenca_verificada=False,
            )
        except RMMInvalido as exc:
            raise ErroContextoMJO("RMM bruto rejeitado pelo parser canônico") from exc
        if normalized["hash_sha256"] != real_sha:
            raise ErroContextoMJO("hash canônico divergente")
        if any(date.fromisoformat(row["data"]) > published.date()
               for row in normalized["observacoes"]):
            raise ErroContextoMJO("snapshot declara publicação anterior à observação contida")
        prepared.append((captured, published, real_sha, normalized))
    prepared.sort(key=lambda x: (x[0], x[1], x[2]))

    answer = []
    known_ids = set()
    for forecast in previsoes:
        if not isinstance(forecast, dict) or set(forecast) != {"previsao_id", "emitido_em"}:
            raise ErroContextoMJO("emissão sem contrato")
        ident = forecast["previsao_id"]
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in known_ids:
            raise ErroContextoMJO("identificador de previsão duplicado ou inválido")
        known_ids.add(ident)
        issue = _instant(forecast["emitido_em"], "emissão")
        candidates = [p for p in prepared if p[0] <= issue and p[1] <= issue]
        chosen = candidates[-1] if candidates else None
        base = {
            "previsao_id": ident, "emitido_em_utc": issue.isoformat(),
            "natureza": "INDICE_DIAGNOSTICO_RMM_OBSERVADO",
            "fonte_id": "BOM_RMM", "modelo_de_chuva_alterado": False,
            "previsao_regional_inferida": False, "homologado": False,
            "direitos_reais_aprovados": False,
            "disponibilidade_externa_auditada": False,
        }
        if chosen is None:
            answer.append({**base, "status": "SEM_VINTAGE_DISPONIVEL",
                           "fase_fonte": None, "amplitude": None,
                           "data_indice": None, "snapshot_sha256": None,
                           "defasagem_dias": None, "sinal": None})
            continue
        capture, publication, raw_sha, normalized = chosen
        observation = ultimo_rmm_ate(snapshot=normalized, corte_em=issue.isoformat())
        if observation is None:
            status = "SEM_OBSERVACAO_DISPONIVEL"
            age = None
        else:
            age = (issue.date() - date.fromisoformat(observation["data"])).days
            status = ("RMM_OBSERVADO_FRACO" if observation["sinal"] == "FRACO"
                      else "RMM_OBSERVADO_ATIVO")
            if age > max_defasagem_dias:
                status = "RMM_DESATUALIZADO"
        answer.append({
            **base, "status": status,
            "fase_fonte": observation["fase_fonte"] if observation and age <= max_defasagem_dias else None,
            "amplitude": observation["amplitude"] if observation and age <= max_defasagem_dias else None,
            "data_indice": observation["data"] if observation and age <= max_defasagem_dias else None,
            "snapshot_sha256": raw_sha,
            "snapshot_publicado_em_utc": publication.isoformat(),
            "snapshot_coletado_em_utc": capture.isoformat(),
            "defasagem_dias": age,
            "sinal": observation["sinal"] if observation and age <= max_defasagem_dias else None,
        })
    return {
        "status": "CONTEXTUALIZACAO_MJO_ASOF_SINTETICA_NAO_HOMOLOGADA",
        "n_previsoes": len(previsoes),
        "n_snapshots": len(snapshots_rmm),
        "contextos": answer,
        "uso_modelo_predictivo_permitido": False,
        "homologado": False,
        "limites": (
            "SHA-256 garante apenas igualdade dos bytes fornecidos: não prova "
            "origem BOM, publicação antiga, licença, QC nem independência. "
            "RMM é índice de diagnóstico; fase não determina precipitação "
            "municipal, vazão, perdas agrícolas ou impactos comerciais."
        ),
    }


def contextualizar_nwp_com_mjo_asof(
    *, snapshots_previsao, snapshots_rmm, acumulacao_horas=24,
    max_defasagem_dias=7,
):
    """Vincula SHA de um forecast NWP a um índice RMM já conhecido na EMISSÃO.

    Não extrai previsão de chuva a partir de MJO. A previsão é o snapshot
    normalizado e hash-verificado usado pelo motor de precipitação; a emissão
    não é inferida do horário de captura do arquivo. O resultado é sidecar
    diagnóstico sem modificar série prevista, pesos ou escores.
    """
    from datetime import timedelta
    from .pacotes_chuva_asof import _parse_snapshot, _numero, ErroPacoteChuva

    if (type(acumulacao_horas) not in (float, int) or
        not 1 / 60 <= acumulacao_horas <= 720):
        raise ErroContextoMJO("janela de acumulação inválida")
    if (not isinstance(snapshots_previsao, (list, tuple)) or
        not 1 <= len(snapshots_previsao) <= 5000):
        raise ErroContextoMJO("snapshots NWP ausentes ou excessivos")
    issues = []
    for pack in snapshots_previsao:
        try:
            row, capture, raw_sha, _, _ = _parse_snapshot(
                pack, kind="PREVISAO", catalogo=None,
                autorizacoes=frozenset(), direitos_ref=None,
            )
        except (ErroPacoteChuva, PermissionError) as exc:
            raise ErroContextoMJO("snapshot de previsão NWP inválido ou não autorizado") from exc
        issued = _instant(row["emitido_em"], "emissão NWP")
        published = _instant(row["previsao_publicada_em"], "publicação NWP")
        features = _instant(row["features_publicadas_ate"], "features NWP")
        valid = _instant(row["valido_em"], "validade NWP")
        climate = _instant(row["climatologia_publicada_em"], "baseline NWP")
        if climate > issued:
            raise ErroContextoMJO("baseline NWP publicado após emissão")
        members = row["membros_mm"]
        if not isinstance(members, list) or not 3 <= len(members) <= 100:
            raise ErroContextoMJO("ensemble NWP requer 3 a 100 membros")
        try:
            for member in members:
                _numero(member, "chuva prevista por membro")
            _numero(row["prob_climatologica"], "probabilidade climatológica", 0, 1)
        except ErroPacoteChuva as exc:
            raise ErroContextoMJO("membros ou climatologia NWP inválidos") from exc
        if not (features <= issued <= published <= capture
                <= valid - timedelta(hours=acumulacao_horas)):
            raise ErroContextoMJO("fuga temporal no snapshot NWP acumulado")
        issues.append({"previsao_id": raw_sha, "emitido_em": issued.isoformat()})
    result = indexar_contexto_mjo_asof(
        previsoes=issues, snapshots_rmm=snapshots_rmm,
        max_defasagem_dias=max_defasagem_dias,
    )
    return {
        **result, "natureza_vinculo": "SIDECAR_SHA_NWP_RMM_OBSERVADO",
        "nwp_hashes_raw_conferidos": len(issues),
        "estatisticas_nwp_alteradas": False,
        "homologado": False,
    }
