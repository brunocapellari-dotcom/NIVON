"""Auditoria de candidato distroless com as mesmas dependências do NIVON.

As contagens de vulnerabilidade são achados por pacote/versão e NÃO autorizam
produção. O teste de runtime, ABI e CVEs precisa ter evidência em ambas CPUs.
"""
from __future__ import annotations

import argparse
import json
import re
from .infra_analytics_audit import _contar, EXTRAS
from .infra_supplychain import ErroSupplyChain, _carregar_json

DISTROLESS_RE = re.compile(r"gcr\.io/distroless/cc-debian13@sha256:[a-f0-9]{64}\Z")
TRIXIE = "nivon-analytics:ci"
DISTROLESS = "nivon-analytics:distroless"


def comparar(original: dict, candidate: dict, bom: dict, *,
             arch: str, base: str, runtime_passed: bool) -> dict:
    if arch not in ("amd64", "arm64") or not isinstance(base,str) or not DISTROLESS_RE.fullmatch(base):
        raise ErroSupplyChain("base não corresponde ao digest oficial distroless")
    if runtime_passed is not True:
        raise ErroSupplyChain("compatibilidade ABI e execução não comprovadas")
    prev = _contar(original, TRIXIE)
    now = _contar(candidate, DISTROLESS)
    if not isinstance(bom, dict) or bom.get("bomFormat") != "CycloneDX":
        raise ErroSupplyChain("SBOM distroless ausente")
    components = bom.get("components")
    if not isinstance(components,list) or not components:
        raise ErroSupplyChain("SBOM vazio")
    names = {p.get("name","").lower().replace("_","-") for p in components
             if isinstance(p,dict) and isinstance(p.get("name"),str)}
    if not EXTRAS.issubset(names):
        raise ErroSupplyChain("SBOM perdeu dependência analítica")
    before=prev["HIGH"]+prev["CRITICAL"]
    after=now["HIGH"]+now["CRITICAL"]
    return {
        "schema":"nivon.infra.distroless_reduction.v1",
        "arch":arch,"candidate_base_digest":base,
        "runtime_synthetic_passed":True,
        "trixie_high":prev["HIGH"],"trixie_critical":prev["CRITICAL"],
        "distroless_high":now["HIGH"],"distroless_critical":now["CRITICAL"],
        "delta_blocking":after-before,
        "distroless_zero_high_critical":after==0,
        "sbom_components":len(components),
        "same_python_major_minor_expected":"3.11",
        "integrated_external_source_tests_passed":False,
        "security_licensing_verified":False,
        "image_adopted":False,
        "production_authorized":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Comparar C/V/E distroless sem release")
    p.add_argument("--trixie",required=True)
    p.add_argument("--candidate",required=True)
    p.add_argument("--sbom",required=True)
    p.add_argument("--arch",choices=("amd64","arm64"),required=True)
    p.add_argument("--digest-ref",required=True)
    p.add_argument("--runtime-passed",action="store_true")
    args=p.parse_args(argv)
    try:
        result=comparar(_carregar_json(args.trixie),_carregar_json(args.candidate),
                         _carregar_json(args.sbom),arch=args.arch,
                         base=args.digest_ref,runtime_passed=args.runtime_passed)
    except (OSError,ValueError):
        print(json.dumps({"status":"INVALID_DISTROLESS_PROOF","production_authorized":False}))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
