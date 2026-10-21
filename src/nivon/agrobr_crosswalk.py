"""Conciliação documental agrobr × catálogo NIVON, sem rede nem permissões implícitas.

A relação upstream é apenas uma tabela auxiliar: as fontes/datasets canônicos
continuam sendo definidos em config/fontes_nivon_master.v1.json.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from .catalogo_fontes import carregar_catalogo, validar_catalogo

ROOT = Path(__file__).resolve().parents[2]
CROSSWALK = ROOT / "config" / "agrobr_crosswalk.v1.json"
STATUSES = {"MAPEADA", "NAO_MAPEADA", "FORA_DO_ESCOPO"}
POLICY = "DOCUMENTARY_ONLY_NO_DATA_COLLECTION_NO_NEW_CANONICAL_SOURCES_NO_RIGHTS_GRANTED"


class ErroCrosswalk(ValueError):
    pass


def carregar_crosswalk(path: str | Path = CROSSWALK) -> dict:
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.suffix != ".json" or p.stat().st_size > 60_000:
        raise ErroCrosswalk("crosswalk deve ser um JSON local regular e limitado")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroCrosswalk("crosswalk JSON invalido") from exc
    return obj


def reconciliar(catalogo: dict, crosswalk: dict) -> dict:
    """Audita nomes e ligacoes existentes; jamais ativa coletores ou incorpora dados."""
    validar_catalogo(catalogo)
    if not isinstance(crosswalk, dict) or crosswalk.get("project") != "NIVON":
        raise ErroCrosswalk("projeto invalido")
    if crosswalk.get("schema_version") != "1.0" or crosswalk.get("policy") != POLICY:
        raise ErroCrosswalk("contrato ou politica incompatível")
    if crosswalk.get("use_case") != "NON_COMMERCIAL_RESEARCH_USE":
        raise ErroCrosswalk("proposito nao comercial obrigatorio")
    upstream = crosswalk.get("upstream")
    if not isinstance(upstream, dict) or upstream.get("repository") != "bruno-portfolio/agrobr" or upstream.get("document") != "docs/sources/index.md":
        raise ErroCrosswalk("origem upstream nao verificavel")
    if not re.fullmatch(r"[a-f0-9]{40}", str(upstream.get("commit", ""))):
        raise ErroCrosswalk("commit upstream precisa de SHA completo")
    entries = crosswalk.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ErroCrosswalk("entries invalidos")
    if len(entries) != upstream.get("documented_count"):
        raise ErroCrosswalk("cobertura difere da declaracao documental upstream")

    fontes = {x["id"]: x for x in catalogo["sources"]}
    por_fonte: dict[str, list] = {}
    for d in catalogo["datasets"]:
        por_fonte.setdefault(d["source_id"], []).append(d)

    vistos = set()
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ErroCrosswalk("entrada nao e objeto")
        slug, status, fid = entry.get("slug"), entry.get("status"), entry.get("source_id")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,60}", slug) or slug in vistos:
            raise ErroCrosswalk("slug duplicado ou invalido")
        vistos.add(slug)
        if status not in STATUSES:
            raise ErroCrosswalk("status desconhecido")
        if slug in {"defensivos", "lista_suja"} and status != "FORA_DO_ESCOPO":
            raise ErroCrosswalk("dominio excluido nao pode ser promovido")
        if status == "MAPEADA":
            if not isinstance(fid, str) or fid not in fontes:
                raise ErroCrosswalk("source_id ausente no catalogo canonico")
            if "motivo" in entry:
                raise ErroCrosswalk("entrada mapeada nao recebe motivo de exclusao")
        else:
            if fid is not None:
                raise ErroCrosswalk("fonte nao mapeada/excluida nao pode conter source_id")
            if status == "FORA_DO_ESCOPO" and (not isinstance(entry.get("motivo"), str) or not entry["motivo"].strip()):
                raise ErroCrosswalk("exclusao requer motivo")
        datasets = por_fonte.get(fid, []) if status == "MAPEADA" else []
        restricted = status == "MAPEADA" and (fontes[fid]["rights"] == "RESTRICTED"
                         or any(d["stage"] == "BLOCKED_RIGHTS" for d in datasets))
        if status == "FORA_DO_ESCOPO":
            gate = "NAO_INTEGRAR"
        elif status == "NAO_MAPEADA":
            gate = "REVISAR_RELEVANCIA_E_FONTE_CANONICA"
        elif restricted:
            gate = "REVISAR_DIREITOS_NAO_COMERCIAIS_POR_OPERACAO"
        elif not datasets:
            gate = "MAPEAR_DATASET_CANONICO_ANTES_DE_ADAPTAR"
        else:
            gate = "COMPARAR_COLETOR_EXISTENTE_E_VALIDAR_AMOSTRA_REAL"
        out.append({
            "agrobr_slug": slug, "source_id_canonico": fid,
            "status": status, "datasets_canônicos": [d["id"] for d in datasets],
            "datasets_p0": [d["id"] for d in datasets if d["priority"] == "P0"],
            "direitos_pendentes": status == "MAPEADA",
            "acesso_runtime_testado": False, "coleta_autorizada_pelo_crosswalk": False,
            "integracao_autorizada_pelo_crosswalk": False, "proximo_gate": gate,
        })
    por_estado = dict(sorted(Counter(e["status"] for e in out).items()))
    cobertos = sorted({d for e in out for d in e["datasets_canônicos"]})
    return {
        "uso": "NAO_COMERCIAL", "estado": "DOCUMENTAL_SEM_TESTE_DE_REDE",
        "upstream_commit": upstream["commit"], "fontes_agrobr_documentadas": len(out),
        "por_estado": por_estado, "datasets_canonicos_cobertos_sem_duplicacao": len(cobertos),
        "fontes_canonicas_criadas": 0, "datasets_criados": 0,
        "coletas_ativadas": 0, "direitos_concedidos": 0,
        "comparacoes": out,
        "limite": "Acesso e funcionamento de conectores upstream nao foram testados; licencia e autorizacao exigem verificacao por operacao.",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Concilia agrobr e NIVON offline; nao acessa fontes")
    p.add_argument("--crosswalk", default=str(CROSSWALK))
    p.add_argument("--resumo", action="store_true")
    args = p.parse_args(argv)
    try:
        result = reconciliar(carregar_catalogo(), carregar_crosswalk(args.crosswalk))
        if args.resumo:
            result.pop("comparacoes")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"estado": "BLOQUEADO", "motivo": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
