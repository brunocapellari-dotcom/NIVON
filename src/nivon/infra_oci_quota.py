"""Comparação OFFLINE de proposta OCI e limites públicos Always Free.

Limite publicado NÃO prova quota/capacidade na conta. Nunca provisiona.
Nenhum JSON é aceito como autorização de custo, login, deploy ou upgrade.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REFERENCE_QUOTAS = {
    "a1_ocpus_total": 2,
    "a1_memory_gb_total": 12,
    "a1_ocpu_hours_month": 1500,
    "a1_memory_gb_hours_month": 9000,
    "boot_and_block_gb_total": 200,
    "object_storage_gb_total": 20,
}

class ErroCotaOCI(ValueError):
    pass


def carregar_proposta(path: str | Path | None = None) -> dict:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "infra" / "oci" / "capacidade-candidata.v1.json"
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000:
        raise ErroCotaOCI("configuração OCI ausente, link ou excessiva")

    def sem_duplicatas(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ErroCotaOCI("chave repetida no JSON")
            out[k] = v
        return out

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=sem_duplicatas)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroCotaOCI("documento OCI inválido") from exc


def avaliar_proposta(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != "nivon.oci.capacity_candidate.v1":
        raise ErroCotaOCI("schema OCI incompatível")
    for key, expected in (("review_only", True),
                          ("provisioning_authorized", False),
                          ("paid_fallback_allowed", False)):
        if type(doc.get(key)) is not bool or doc[key] is not expected:
            raise ErroCotaOCI("não permitir credencial, deploy nem fallback pago: "+key)
    quota = doc.get("quota_reference_not_tenancy_proof")
    if quota != REFERENCE_QUOTAS:
        raise ErroCotaOCI("referência de cotas alterada sem revisão metodológica")
    cand = doc.get("nivon_candidate")
    if not isinstance(cand, dict) or cand.get("shape") != "VM.Standard.A1.Flex":
        raise ErroCotaOCI("somente candidato A1 revisado é aceito")
    nums=("ocpus","memory_gb","boot_gb","additional_block_gb","object_gb","maximum_calendar_hours")
    for key in nums:
        if type(cand.get(key)) is not int or cand[key] < 0:
            raise ErroCotaOCI("quantidade OCI inválida: "+key)
    if not cand["ocpus"] or not cand["memory_gb"] or cand["boot_gb"] < 50:
        raise ErroCotaOCI("VM sem CPU/RAM ou boot inferior a 50 GB")
    if not 1 <= cand["maximum_calendar_hours"] <= 744:
        raise ErroCotaOCI("horas mensais devem ser de 1 até 744")
    if cand.get("public_ip_required") is not False or cand.get("public_ports_requested") != []:
        raise ErroCotaOCI("plano de infraestrutura somente privado; revisar acessos")
    limits = doc.get("limits")
    expected_flags = {"additional_paid_resources": False,
                      "automatic_upgrade": False,
                      "disallow_other_project_quota_assumptions": True,
                      "requires_operator_release_gate": True,
                      "requires_offsite_backup_and_restore": True}
    if not isinstance(limits, dict) or any(limits.get(k) is not v or type(limits.get(k)) is not bool
                                           for k, v in expected_flags.items()):
        raise ErroCotaOCI("política de gastos ou recuperação relaxada")
    ev = doc.get("tenant_evidence")
    if not isinstance(ev, dict):
        raise ErroCotaOCI("bloco de tenancy ausente")
    for k in ("home_region_verified","shape_capacity_verified","billing_and_quota_verified"):
        if type(ev.get(k)) is not bool or ev[k]:
            raise ErroCotaOCI("prova externa de conta não pode ser afirmada pelo blueprint")
    if ev.get("home_region") is not None:
        raise ErroCotaOCI("região da conta não pode ser presumida")
    usage_keys = (
        "other_a1_ocpus_used","other_a1_memory_gb_used",
        "other_boot_block_gb_used","other_object_gb_used",
        "other_a1_ocpu_hours_current_month","other_a1_memory_gb_hours_current_month",
    )
    if any(ev.get(x) is not None for x in usage_keys):
        raise ErroCotaOCI("recursos de outros projetos são desconhecidos até inventário autenticado")

    proposal = {
        "a1_ocpus_total": cand["ocpus"],
        "a1_memory_gb_total": cand["memory_gb"],
        "a1_ocpu_hours_month": cand["ocpus"] * cand["maximum_calendar_hours"],
        "a1_memory_gb_hours_month": cand["memory_gb"] * cand["maximum_calendar_hours"],
        "boot_and_block_gb_total": cand["boot_gb"] + cand["additional_block_gb"],
        "object_storage_gb_total": cand["object_gb"],
    }
    exceeds = sorted(k for k, v in proposal.items() if v > REFERENCE_QUOTAS[k])
    return {
        "modo":"PARECER_TEORICO_OFFLINE",
        "estado":"PROPOSTA_FORA_DA_REFERENCIA" if exceeds else "CANDIDATO_COMPATIVEL_SOZINHO_CONTA_DESCONHECIDA",
        "proposta": proposal,
        "limites_publicos": dict(REFERENCE_QUOTAS),
        "excede_referencia": exceeds,
        "capacidade_regional_comprovada":False,
        "quota_restante_comprovada":False,
        "estimativa_de_custo_zero_garantida":False,
        "deploy_autorizado":False,
        "referencia_nao_inclui_uso_da_holding_ou_outros_projetos":True,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="OCI: diagnóstico teórico, sem acesso ao provedor")
    p.add_argument("--config",help="proposta JSON com fonte verificável")
    p.add_argument("--require-account-proof",action="store_true",
                   help="retorna 3 enquanto conta e billing não forem auditados")
    args=p.parse_args(argv)
    try:
        result=avaliar_proposta(carregar_proposta(args.config))
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        if args.require_account_proof or result["excede_referencia"]:
            return 3
        return 0
    except (ErroCotaOCI, OSError) as exc:
        print(json.dumps({"estado":"BLOQUEADO","motivo":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
