"""Autorização manual e restrita de ingestão ZARC, separada de agendamento.

Exceção estrita do catálogo DENY-ALL para uma única edição oficial do MAPA,
somente staging de quarentena; COLETA+ARMAZENAMENTO de obra CC BY com atribuição.
Nenhuma autorização para publicação, transações comerciais ou atualizações
recorrentes é derivada desse contrato.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

RECURSO="139e5a60-1f43-4cc8-aeab-a35dbbf816c0"
DATASET="ZARC_JANELAS"
EVIDENCIA_PREFIXO="MAPA_CCBY_ZARC_"
_S=re.compile(r"[0-9a-f]{64}\Z")

class ErroLicencaZarc(ValueError):
    pass

@dataclass(frozen=True)
class LicencaManualZarc:
    dataset_id:str
    resource_id:str
    ckan_fingerprint:str
    evidence_id:str
    license_id:str
    scope:str
    schedule:bool
    publication:bool

def emitir_licenca_manual(sinal, *, consentimento_manual=False):
    """Só emite permissão após leitura validada do CKAN oficial.

    consentimento_manual=True deve ser informado pelo operador a cada rodada
    controlada; passar a flag não é agendamento ou autorização genérica.
    """
    if consentimento_manual is not True:
        raise PermissionError("CONSENTIMENTO_DA_COLETA_MANUAL_AUSENTE")
    if not isinstance(sinal,dict):
        raise ErroLicencaZarc("FONTE_CKAN_INVALIDA")
    sha=sinal.get("metadata_fingerprint")
    if (sinal.get("dataset_id")!=DATASET
            or sinal.get("resource_id")!=RECURSO
            or sinal.get("source_id")!="ZARC"
            or sinal.get("licenca_declarada")!="cc-by"
            or sinal.get("consegue_provar_arquivo_alterado") is not False
            or not isinstance(sha,str) or not _S.fullmatch(sha)):
        raise ErroLicencaZarc("LICENCA_OFICIAL_NAO_COMPROVADA")
    return LicencaManualZarc(
       dataset_id=DATASET, resource_id=RECURSO,
       ckan_fingerprint=sha,
       evidence_id=EVIDENCIA_PREFIXO+sha,
       license_id="cc-by",
       scope="QUARENTENA_LOCAL_MANUAL",
       schedule=False,publication=False,
    )

def validar_licenca_manual(permissao, *, dataset_id, evidence_id):
    return (
        type(permissao) is LicencaManualZarc
        and dataset_id==DATASET and permissao.dataset_id==DATASET
        and permissao.resource_id==RECURSO
        and permissao.license_id=="cc-by"
        and permissao.scope=="QUARENTENA_LOCAL_MANUAL"
        and permissao.schedule is False
        and permissao.publication is False
        and isinstance(permissao.ckan_fingerprint,str)
        and _S.fullmatch(permissao.ckan_fingerprint) is not None
        and permissao.evidence_id==EVIDENCIA_PREFIXO+permissao.ckan_fingerprint
        and evidence_id==permissao.evidence_id
    )
