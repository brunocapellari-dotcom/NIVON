"""IVE/IVO: leitura governada de exportacoes canonicas do Second Brain.

Adaptador puro e offline para second_brain.agrolog_release.AgroLogKnowledgeRecord
(model_dump json). ResearchPackage NAO promove claims. Nao duplica store,
Knowledge Factory, mecanismo de assinatura ou autoridade de autorizacao.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from hashlib import sha256
from typing import Callable
from urllib.parse import urlsplit

from .ivo_conhecimento_adapter import ClaimCurado


class ErroProvenienciaIVO(ValueError):
    """Fonte, versao, data, atestacao ou direito nao verificavel."""


HEX = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
TIPOS = {
    "OBSERVADO": "DADO_OBSERVADO",
    "ESTIMADO": "ESTIMATIVA",
    "PROJETADO": "PROJECAO",
    "INFERIDO": "INFERENCIA",
    "ESTRUTURAL": "CONHECIMENTO_ESTRUTURAL",
    "SOURCE_LAG": "SINAL_INDIRETO",
}


def _momento(v: object, campo: str) -> datetime:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            pass
    if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroProvenienciaIVO(f"{campo}: timestamp ISO com fuso obrigatorio")
    return v.astimezone(timezone.utc)


def _dia(v: object, campo: str) -> date:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ErroProvenienciaIVO(f"{campo}: data AAAA-MM-DD obrigatoria")
    try:
        return date.fromisoformat(v)
    except ValueError as exc:
        raise ErroProvenienciaIVO(f"{campo}: data invalida") from exc


def _id(v: object, campo: str) -> str:
    if not isinstance(v, str) or not ID.fullmatch(v):
        raise ErroProvenienciaIVO(f"{campo}: identificador invalido")
    return v


def _hash(v: object, campo: str) -> str:
    if not isinstance(v, str) or not HEX.fullmatch(v):
        raise ErroProvenienciaIVO(f"{campo}: SHA-256 obrigatorio")
    return v


def _mapping(v: object, campo: str) -> dict:
    if not isinstance(v, dict):
        raise ErroProvenienciaIVO(f"{campo}: objeto esperado")
    return v


def _url(v: object) -> str:
    if not isinstance(v, str) or len(v) > 2048:
        raise ErroProvenienciaIVO("URL de fonte invalida")
    partes = urlsplit(v)
    if (partes.scheme != "https" or not partes.hostname
            or partes.username or partes.password or partes.fragment):
        raise ErroProvenienciaIVO("fonte primaria exige HTTPS sem credenciais")
    return v


def _canonical_json(record: dict) -> bytes:
    try:
        result = json.dumps(
            record, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ErroProvenienciaIVO("registro nao serializavel") from exc
    if len(result) > 128_000:
        raise ErroProvenienciaIVO("registro excessivo")
    return result


@dataclass(frozen=True)
class ExportacaoSegundoCerebro:
    """Snapshot fornecido pelo servidor, nao pelo usuario ou pelo LLM."""
    registro: dict
    evidencia_bruta: bytes
    exportado_em: datetime


@dataclass(frozen=True)
class AtestacaoCanonicaIVO:
    """Resposta de um verificador de autoridade externo; NAO assinatura local."""
    claim_id: str
    evidence_id: str
    source_id: str
    tenant: str
    consumidor: str
    registro_sha256: str
    evidencia_sha256: str
    fonte_url: str
    decision_id: str
    auditoria_id: str
    aprovado_em: datetime
    verificado_em: datetime
    promocao_confirmada: bool
    direito_consultar: bool
    vigente_no_corte: bool


Verificador = Callable[[str, str, str, datetime], AtestacaoCanonicaIVO]


def normalizar_exportacoes_canonicas(
    exportacoes: list[ExportacaoSegundoCerebro], *, corte: datetime,
    tenant: str, verificador: Verificador | None,
    projetos_origem: frozenset[str] = frozenset({"AGROLOG", "NIVON"}),
) -> dict:
    """Retorna claims para o gateway Hermes, nao resposta publicada.

    Todos os registros devem passar na mesma transacao logica. Uma exportacao
    invalida aborta o lote inteiro: nao ha sucesso parcial mascarado.
    """
    asof = _momento(corte, "corte")
    _id(tenant, "tenant")
    if not callable(verificador):
        raise ErroProvenienciaIVO("verificador externo nao configurado")
    if not isinstance(exportacoes, list) or len(exportacoes) > 100:
        raise ErroProvenienciaIVO("lote invalido")
    if (not isinstance(projetos_origem, frozenset) or not projetos_origem
            or any(not isinstance(x, str) or not ID.fullmatch(x) for x in projetos_origem)):
        raise ErroProvenienciaIVO("allowlist de origem invalida")
    claims = []
    metadados = []
    vistos = set()
    for ex in exportacoes:
        if type(ex) is not ExportacaoSegundoCerebro:
            raise ErroProvenienciaIVO("exportacao invalida")
        registro = _mapping(ex.registro, "registro")
        exportado = _momento(ex.exportado_em, "exportado_em")
        if exportado > asof:
            raise ErroProvenienciaIVO("exportacao futura no corte")
        if registro.get("contract_version") != "1.0":
            raise ErroProvenienciaIVO("contrato desconhecido")
        claim_id = _id(registro.get("claim_id"), "claim_id")
        evidence_id = _id(registro.get("evidence_id"), "evidence_id")
        source_id = _id(registro.get("source_id"), "source_id")
        projeto = _id(registro.get("project"), "project")
        _id(registro.get("domain"), "domain")
        if projeto not in projetos_origem or claim_id in vistos:
            raise ErroProvenienciaIVO("origem ou claim duplicado")
        vistos.add(claim_id)
        if registro.get("status") != "CANONICO":
            raise ErroProvenienciaIVO("registro nao canonico; ResearchPackage nao e promocao")
        promotion = _mapping(registro.get("promotion"), "promotion")
        if (promotion.get("promoted_by") != "knowledge_factory"
                or promotion.get("audited") is not True
                or promotion.get("validated") is not True):
            raise ErroProvenienciaIVO("promocao nao validada")
        decision_id = _id(promotion.get("decision_id"), "decision_id")
        if registro.get("truth_classification") not in TIPOS:
            raise ErroProvenienciaIVO("natureza de dado desconhecida")
        texto = registro.get("claim")
        if not isinstance(texto, str) or not texto.strip() or len(texto) > 8000:
            raise ErroProvenienciaIVO("texto de claim invalido")
        dates = _mapping(registro.get("dates"), "dates")
        publication = _momento(dates.get("publication_date"), "publication_date")
        collection = _momento(dates.get("collection_date"), "collection_date")
        if publication > collection or collection > exportado:
            raise ErroProvenienciaIVO("publicacao/coleta/exportacao incoerentes")
        valid_from = _momento(registro.get("valid_from"), "valid_from")
        valid_to = (None if registro.get("valid_to") is None else
                    _momento(registro["valid_to"], "valid_to"))
        if valid_from > asof or (valid_to is not None and valid_to <= asof):
            raise ErroProvenienciaIVO("claim fora de sua vigencia")
        if valid_to is not None and valid_to <= valid_from:
            raise ErroProvenienciaIVO("janela de validade invalida")
        reference = _dia(dates.get("reference_date"), "reference_date")
        competence = dates.get("competence_date")
        if competence is None:
            raise ErroProvenienciaIVO("competencia ausente")
        competence = _dia(competence, "competence_date")
        evidences = registro.get("evidence")
        if not isinstance(evidences, list) or not 1 <= len(evidences) <= 40:
            raise ErroProvenienciaIVO("lista de evidencias invalida")
        selected = []
        for evidence in evidences:
            ev = _mapping(evidence, "evidence")
            if _id(ev.get("source_id"), "source_id") != source_id:
                raise ErroProvenienciaIVO("fonte de evidencia divergente")
            if _id(ev.get("evidence_id"), "evidence_id") == evidence_id:
                selected.append(ev)
        if len(selected) != 1:
            raise ErroProvenienciaIVO("identidade da evidencia ambigua")
        if not isinstance(ex.evidencia_bruta, bytes) or len(ex.evidencia_bruta) > 8_000_000:
            raise ErroProvenienciaIVO("bytes da evidencia ausentes/excessivos")
        evidence_hash = sha256(ex.evidencia_bruta).hexdigest()
        if _hash(selected[0].get("content_hash"), "evidence.content_hash") != evidence_hash:
            raise ErroProvenienciaIVO("evidencia alterada ou hash fraco")
        registro_hash = sha256(_canonical_json(registro)).hexdigest()
        try:
            at = verificador(claim_id, registro_hash, evidence_hash, asof)
        except Exception:
            raise ErroProvenienciaIVO("verificacao externa indisponivel") from None
        if type(at) is not AtestacaoCanonicaIVO:
            raise ErroProvenienciaIVO("atestado externo invalido")
        if (at.promocao_confirmada is not True
                or at.direito_consultar is not True
                or at.vigente_no_corte is not True
                or at.claim_id != claim_id or at.evidence_id != evidence_id
                or at.source_id != source_id or at.tenant != tenant
                or at.consumidor != "NIVON"
                or _hash(at.registro_sha256, "registro_sha256") != registro_hash
                or _hash(at.evidencia_sha256, "evidencia_sha256") != evidence_hash
                or _id(at.decision_id, "decision_id") != decision_id):
            raise ErroProvenienciaIVO("atestado nao corresponde ao registro")
        audit_id = _id(at.auditoria_id, "auditoria_id")
        fonte_url = _url(at.fonte_url)
        approved = _momento(at.aprovado_em, "aprovado_em")
        verified = _momento(at.verificado_em, "verificado_em")
        if not (collection <= approved <= verified <= asof):
            raise ErroProvenienciaIVO("atestado tardio ou retroativo")
        # O modelo Second Brain armazena data, nao hora, para referencia e
        # competencia. Convertemos 00 UTC apenas como convenio de transporte.
        ref_at = datetime.combine(reference, time.min, tzinfo=timezone.utc)
        c = ClaimCurado(
            claim_id=claim_id, texto=texto, dominio=registro["domain"],
            fonte_id=source_id, fonte_url=fonte_url,
            documento_sha256=evidence_hash, competencia=competence.isoformat(),
            referencia_em=ref_at, publicado_em=publication,
            coletado_em=collection, validado_em=verified,
            aprovado_por="KNOWLEDGE_FACTORY_ATTESTATION",
            auditoria_id=audit_id, tipo=TIPOS[registro["truth_classification"]],
            status="APROVADO", direitos_aprovados=True,
            suplantado_em=valid_to,
        )
        c.validar()
        claims.append(c)
        metadados.append({
            "claim_id": claim_id, "evidence_id": evidence_id,
            "knowledge_project": projeto, "decision_id": decision_id,
            "registro_sha256": registro_hash,
            "evidencia_sha256": evidence_hash,
            "referencia_granularidade": "DIA",
            "classificacao_origem": registro["truth_classification"],
            "relacoes_nao_causais": {
                "supersedes": registro.get("supersedes", []),
                "contradicts": registro.get("contradicts", []),
                "derived_from": registro.get("derived_from", []),
            },
        })
    return {
        "estado": "CONTRATOS_VALIDADOS_EXTERNO_AINDA_NAO_CERTIFICADO",
        "claims": claims, "metadados": metadados,
        "fonte_canonicidade": "SECOND_BRAIN_KNOWLEDGE_FACTORY",
        "uso": "APENAS_GATEWAY_HERMES_READONLY",
        "llm_executado": False, "treino_executado": False,
        "observacao": (
            "Callback de atestacao nao equivale assinatura real; dados reais "
            "exigem verificador, snapshots e direitos homologados."
        ),
    }
