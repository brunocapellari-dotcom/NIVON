"""Gate local de evidências Trivy + CycloneDX para imagem sintética NIVON.

Não executa scanners, não altera recursos e não abre links/URLs externos.
Imprime SOMENTE contagens; relatórios potencialmente sensíveis não vão a logs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class ErroSupplyChain(ValueError):
    pass


SEVERIDADES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _carregar_json(caminho: str | Path) -> dict:
    p = Path(caminho)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= 40_000_000:
        raise ErroSupplyChain("relatório ausente, simbólico, vazio ou acima de 40 MB")
    try:
        with p.open("r", encoding="utf-8") as f:
            obj = json.load(f, object_pairs_hook=_sem_duplicatas)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ErroSupplyChain("relatório JSON inválido") from exc
    if not isinstance(obj, dict):
        raise ErroSupplyChain("raiz do relatório não é objeto")
    return obj


def _sem_duplicatas(pares):
    obj = {}
    for k, v in pares:
        if k in obj:
            raise ErroSupplyChain("chave repetida no JSON")
        obj[k] = v
    return obj


def avaliar_relatorios(scan: dict, sbom: dict, *, imagem: str) -> dict:
    """Recusa prova ausente, imagem divergente e achados HIGH/CRITICAL."""
    if not isinstance(imagem, str) or imagem != "nivon-worker-supply:ci":
        raise ErroSupplyChain("identidade da imagem não permitida")
    if not isinstance(scan, dict) or scan.get("ArtifactName") != imagem:
        raise ErroSupplyChain("Trivy não analisou a imagem solicitada")
    if scan.get("ArtifactType") != "container_image":
        raise ErroSupplyChain("relatório não é de imagem de contêiner")
    if type(scan.get("SchemaVersion")) is not int or scan["SchemaVersion"] <= 0:
        raise ErroSupplyChain("schema Trivy não reconhecido")
    resultados = scan.get("Results")
    if not isinstance(resultados, list) or not resultados:
        raise ErroSupplyChain("sem resultados de inspeção: não assumir zero CVEs")

    contagens = {sev: 0 for sev in sorted(SEVERIDADES)}
    for r in resultados:
        if not isinstance(r, dict) or not isinstance(r.get("Target"), str):
            raise ErroSupplyChain("resultado Trivy sem alvo identificado")
        achados = r.get("Vulnerabilities", [])
        if not isinstance(achados, list):
            raise ErroSupplyChain("lista de vulnerabilidades inválida")
        for item in achados:
            if not isinstance(item, dict) or item.get("Severity") not in SEVERIDADES:
                raise ErroSupplyChain("severidade ausente ou desconhecida")
            contagens[item["Severity"]] += 1

    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        raise ErroSupplyChain("SBOM não é CycloneDX")
    if not isinstance(sbom.get("specVersion"), str) or not sbom["specVersion"]:
        raise ErroSupplyChain("versão CycloneDX ausente")
    # Lista de pacotes pode vir de outra imagem mesmo com formato CycloneDX
    # válido. Exigir identificação explícita do próprio artefato inspecionado.
    metadata = sbom.get("metadata")
    principal = metadata.get("component") if isinstance(metadata, dict) else None
    if (not isinstance(principal, dict)
            or principal.get("name") != imagem
            or principal.get("type") != "container"):
        raise ErroSupplyChain("SBOM não identifica a mesma imagem do Trivy")
    componentes = sbom.get("components")
    if not isinstance(componentes, list) or not componentes:
        raise ErroSupplyChain("SBOM sem componentes: cobertura não comprovada")
    if any(not isinstance(x, dict) or not isinstance(x.get("name"), str)
           or not x["name"] for x in componentes):
        raise ErroSupplyChain("componente SBOM inválido")
    bloqueantes = contagens["HIGH"] + contagens["CRITICAL"]
    return {
        "estado": "BLOCKED_HIGH_CRITICAL" if bloqueantes else "STATIC_SCAN_NO_HIGH_CRITICAL",
        "imagem": imagem,
        "sbom_componentes": len(componentes),
        "resultados_trivy": len(resultados),
        "vulnerabilidades_por_severidade": contagens,
        "bloqueantes": bloqueantes,
        "producao_autorizada": False,
        "revisao_independente_concluida": False,
        "imagem_arm64_escaneada": False,
        "backup_remoto_verificado": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validador offline de relatórios supply chain")
    parser.add_argument("--trivy-json", required=True)
    parser.add_argument("--cyclonedx-json", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    try:
        data = avaliar_relatorios(_carregar_json(args.trivy_json),
                                 _carregar_json(args.cyclonedx_json),
                                 imagem=args.image)
    except (OSError, ErroSupplyChain) as exc:
        print(json.dumps({"estado": "INVALID_EVIDENCE",
                          "motivo": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(data, sort_keys=True))
    return 3 if data["bloqueantes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
