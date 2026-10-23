"""Plano operacional das rotas de coleta NIVON: catálogo mestre, fail-closed.

Combina catálogo mestre (um só cadastro de produto, estágio, prioridade, cadência,
fonte) e rotas técnicas. Nenhum acesso HTTP ou execução de collector aqui.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from .catalogo_fontes import carregar_catalogo, ErroCatalogo

ROOT = Path(__file__).resolve().parents[2]
ROTAS = ROOT / "config" / "rotas_coleta.v1.json"
CLASSES = frozenset({
    "STRUCTURED_FILE", "ACCESS_GATED", "OFFICIAL_API", "PUBLISHED_DOCUMENT",
    "DASHBOARD_MANUAL_EXPORT", "INTERNAL_CONTRACT", "DISCOVERY_REQUIRED", "API_OR_FILE",
    "STREAM_AUTH",
})
LOCATORS = frozenset({
    "DIRECT_PUBLIC_FILE", "DIRECT_OFFICIAL_API", "PUBLISHED_API_DOC", "PROVIDER_PORTAL", "OFFICIAL_INDEX",
    "OFFICIAL_DASHBOARD", "NOT_VERIFIED_PER_DATASET",
})
PROIBIDOS_URL = frozenset({"localhost", "127.0.0.1", "0.0.0.0"})
CAMPOS_PRINCIPAIS = frozenset({
    "dataset_id", "collector_class", "locator", "implementation_scope",
    "authentication", "last_verified_data", "runtime_enabled", "scheduled_enabled",
    "primary_blocker", "gates_missing", "history", "data_contract",
    "source_note", "preliminary_evidence",
})


class ErroRota(ValueError):
    pass


def carregar_rotas(path: str | Path = ROTAS) -> dict:
    p = Path(path)
    if p.suffix != ".json" or not p.is_file() or p.is_symlink() or p.stat().st_size > 250_000:
        raise ErroRota("arquivo de rotas ausente, inválido ou grande demais")
    try:
        o = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroRota("JSON das rotas inválido") from exc
    return o


def validar_rotas(rotas: dict, catalogo: dict) -> dict:
    if not isinstance(rotas, dict) or rotas.get("project") != "NIVON" or rotas.get("schema_version") != "1.0.0":
        raise ErroRota("versão do plano operacional incompatível")
    if rotas.get("policy") != "DENY_ALL_UNTIL_PER_OPERATION_RIGHTS_TESTS_AND_PERSISTENCE":
        raise ErroRota("política default-deny ausente")
    entries = rotas.get("entries")
    if not isinstance(entries, list):
        raise ErroRota("entries obrigatórias")
    datasets = {d["id"]: d for d in catalogo["datasets"]}
    sources = {s["id"]: s for s in catalogo["sources"]}
    ids = set()
    for e in entries:
        if not isinstance(e, dict) or not CAMPOS_PRINCIPAIS <= set(e):
            raise ErroRota("rota sem contrato mínimo")
        id_ = e["dataset_id"]
        if id_ not in datasets or id_ in ids:
            raise ErroRota("dataset inexistente ou duplicado: " + str(id_))
        ids.add(id_)
        d = datasets[id_]
        fonte = sources[d["source_id"]]
        if e["collector_class"] not in CLASSES:
            raise ErroRota(f"{id_}: classe técnica desconhecida")
        if e["runtime_enabled"] is not False or e["scheduled_enabled"] is not False:
            raise ErroRota(f"{id_}: ativação sem autorização por fonte")
        if e["last_verified_data"] is not None:
            raise ErroRota(f"{id_}: data de validação operacional não pode ser presumida")
        if e["data_contract"] != "OBSERVACAO_CANONICA_V1":
            raise ErroRota(f"{id_}: contrato canônico incompatível")
        if e["history"] != "BACKFILL_TO_OLDEST_LEGAL_AND_TECHNICALLY_AVAILABLE_THEN_INCREMENTAL":
            raise ErroRota(f"{id_}: histórico sem backfill e controle de acesso")
        gates = e["gates_missing"]
        if not isinstance(gates, list) or not gates or any(not isinstance(x, str) or not x for x in gates):
            raise ErroRota(f"{id_}: gates ausentes")
        if not {"HISTORICAL_BACKFILL", "DURABLE_PERSISTENCE_AND_RESTORE", "LICENSED_PUBLICATION_GATE"} <= set(gates):
            raise ErroRota(f"{id_}: não há controles mínimos de histórico e publicação")
        if (d["stage"] == "BLOCKED_RIGHTS" or fonte["rights"] == "RESTRICTED"):
            if e["collector_class"] != "ACCESS_GATED" or "RIGHTS_COLLECTION" not in gates:
                raise ErroRota(f"{id_}: fonte com direitos restritos sem bloqueio")
        loc = e["locator"]
        if not isinstance(loc, dict) or loc.get("kind") not in LOCATORS:
            raise ErroRota(f"{id_}: tipo de localização inválido")
        uri = loc.get("url")
        if uri is None:
            if loc["kind"] != "NOT_VERIFIED_PER_DATASET" or "EXACT_ENDPOINT_UNKNOWN" not in gates:
                raise ErroRota(f"{id_}: endpoint desconhecido marcado como conhecido")
        else:
            if not isinstance(uri, str):
                raise ErroRota(f"{id_}: URL não é texto")
            parsed = urlsplit(uri)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ErroRota(f"{id_}: URL insegura")
            if parsed.hostname in PROIBIDOS_URL or parsed.port not in (None, 443):
                raise ErroRota(f"{id_}: host/porta proibidos")
            fonte_host = urlsplit(fonte["official_url"]).hostname or ""
            # Aliases oficiais derivados devem ser explicitamente permitidos
            # para evitar transformar host arbitrário em endpoint de dados.
            homologados = {
                "MAPA": {"dados.agricultura.gov.br"},
                "BCB": {"olinda.bcb.gov.br", "dadosabertos.bcb.gov.br", "api.bcb.gov.br"},
                "OPEN_METEO": {"api.open-meteo.com", "archive-api.open-meteo.com", "flood-api.open-meteo.com", "ensemble-api.open-meteo.com"},
                "INPE_TERRABRASILIS": {"terrabrasilis.dpi.inpe.br"},
                "WB": {"api.worldbank.org", "thedocs.worldbank.org"},
                "CONAB": {"www.gov.br", "gov.br", "conab.gov.br", "www.conab.gov.br", "portaldeinformacoes.conab.gov.br"},
                "ANP": {"www.gov.br", "gov.br"},
                "MDIC": {"www.gov.br", "gov.br"},
                "IBGE": {"servicodados.ibge.gov.br", "apisidra.ibge.gov.br"},
                "ANTT": {"dados.antt.gov.br"},
                "INPE_QUEIMADAS": {"dataserver-coids.inpe.br"},
                "NASA_GLAM": {"glam1.gsfc.nasa.gov"},
                "EARTH_SEARCH": {"earth-search.aws.element84.com"},
                "ESA_WORLDCOVER": {"registry.opendata.aws", "esa-worldcover.s3.eu-central-1.amazonaws.com"},
                "USDA": {"www.ams.usda.gov", "apps.fas.usda.gov"},
                "JRC_GSW": {"global-surface-water.appspot.com", "storage.googleapis.com"},
                "NOAA": {"www.cpc.ncep.noaa.gov", "psl.noaa.gov"},
                "IMF_PORTWATCH": {"portwatch.imf.org"},
                "GEOGLAM_CROPMONITOR": {"www.cropmonitor.org"},
                "EMBRAPA_GEOINFO": {"geoinfo.dados.embrapa.br"},
                "FAO": {"fpma.fao.org", "fenixservices.fao.org", "bulks-faostat.fao.org"},
                "EUROSTAT": {"ec.europa.eu"},
            }
            if parsed.hostname != fonte_host and parsed.hostname not in homologados.get(d["source_id"], set()):
                raise ErroRota(f"{id_}: host não demonstrado como domínio oficial da fonte")
        if not isinstance(e["source_note"], str) or not e["source_note"]:
            raise ErroRota(f"{id_}: limitações da fonte não identificadas")
    ausentes = set(datasets) - ids
    if ausentes:
        raise ErroRota("datasets sem rota técnica: " + ",".join(sorted(ausentes)))
    return {
        "fontes": len(sources), "datasets": len(datasets), "rotas": len(entries),
        "classes": dict(sorted(Counter(e["collector_class"] for e in entries).items())),
        "endpoints_não_localizados": sum(e["locator"]["url"] is None for e in entries),
        "referencias_a_arquivos_diretos": sum(e["locator"]["kind"] == "DIRECT_PUBLIC_FILE" for e in entries),
        "coletas_ativadas": 0,
        "status": "CATALOGO_OPERACIONAL_VALIDADO_SEM_EXECUCAO",
    }


def montar_plano(rotas: dict, catalogo: dict, *, prioridade: str | None = None,
                  grupo: str | None = None) -> list[dict]:
    validar_rotas(rotas, catalogo)
    dados = {d["id"]: d for d in catalogo["datasets"]}
    fontes = {s["id"]: s for s in catalogo["sources"]}
    ret = []
    for x in rotas["entries"]:
        d = dados[x["dataset_id"]]
        if prioridade and d["priority"] != prioridade:
            continue
        if grupo and d["group"] != grupo:
            continue
        fonte = fontes[d["source_id"]]
        ret.append({
            "dataset": d["id"], "prioridade": d["priority"], "grupo": d["group"],
            "fonte": fonte["provider"], "modo": d["mode"], "cadencia_proposta": d["cadence"],
            "via_tecnica": x["collector_class"],
            "fonte_especifica": x["locator"]["url"],
            "estado_referencia": x["locator"]["kind"],
            "evidencia": x["locator"].get("source_proof"),
            "codigo_reutilizavel": d["existing_module"],
            "direitos": fonte["rights"],
            "bloqueios": x["gates_missing"],
            "programado": False,
        })
    prioridade_ordem = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(ret, key=lambda r: (prioridade_ordem[r["prioridade"]], r["grupo"], r["dataset"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="NIVON: rotas API/download/portal dos 86 datasets; SEM COLETA")
    ap.add_argument("--prioridade", choices=["P0", "P1", "P2"])
    ap.add_argument("--grupo")
    ap.add_argument("--resumo", action="store_true")
    args = ap.parse_args(argv)
    try:
        catalogo = carregar_catalogo()
        rotas = carregar_rotas()
        diagnostico = validar_rotas(rotas, catalogo)
        if not args.resumo:
            diagnostico["plano"] = montar_plano(rotas, catalogo, prioridade=args.prioridade, grupo=args.grupo)
        print(json.dumps(diagnostico, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ErroCatalogo, ErroRota) as exc:
        print(json.dumps({"status": "BLOQUEADO", "erro": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
