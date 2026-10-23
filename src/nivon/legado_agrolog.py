"""Inventario de migração AgroLog -> NIVON, estritamente offline e sem habilitar coleta.

Entradas historicas são referências; status ACTIVE do legado nunca equivale
a licença, execucao ou homologacao no NIVON.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
REGISTRO = ROOT / "config/legado_agrolog/registro_coletores.v1.json"
LINKS = ROOT / "config/legado_agrolog/catalogo_links.v1.json"
NIVON = ROOT / "config/fontes_nivon_master.v1.json"

# Mapeamento SOMENTE de identidade do provedor, nunca do dataset nem de permissao.
# Entradas ambiguas ficam propositadamente sem correspondencia.
ALIAS_PROVEDORES = {
    "conab_armazens_cadastrados": "CONAB",
    "conab_safra_graos_xlsx": "CONAB",
    "imea_operational_xlsx": "IMEA",
    "ibge_pam": "IBGE",
    "cepea_prices": "CEPEA",
    "bcb_ptax_usd_daily": "BCB",
    "bcb_olinda_ptax_discovery": "BCB",
    "mdic_comexstat": "MDIC",
    "mdic_comexstat_bulk": "MDIC",
    "antt_open_data": "ANTT",
    "antaq_operational": "ANTAQ",
    "anp_bioenergy": "ANP",
    "anp_diesel": "ANP",
    "aneel_siga": "ANEEL",
    "ons_open_data": "ONS",
    "abiove_processing": "ABIOVE",
    "sigsif_cattle": "MAPA",
    "ibge_cattle": "IBGE",
    "inmet_weather": "INMET",
    "cptec_weather": "CPTEC",
    "nasa_power_grid": "NASA_POWER",
    "copernicus_climate": "COPERNICUS_CDS",
    "ana_hidroweb": "ANA",
    "aisstream_maritime": "AIS",
    "usda_fas_psd": "USDA",
    "usda_fas_export_sales": "USDA",
    "usda_agtransport": "USDA",
    "usda_wasde": "USDA",
    "usda_nass_quickstats": "USDA",
    "usda_nass_corn_weekly_current": "USDA",
    "usda_nass_soybeans_weekly_current": "USDA",
    "usda_nass_cotton_weekly_current": "USDA",
    "usda_nass_wheat_weekly_current": "USDA",
    "usda_crop_progress": "USDA",
    "usda_crop_production": "USDA",
    "usda_acreage": "USDA",
    "usda_prospective_plantings": "USDA",
    "usda_grain_stocks": "USDA",
    "usda_weekly_weather_crop_bulletin": "USDA",
    "noaa_cpc": "NOAA",
    "bcr_gea": "ARG_BCR_GEA",
    "bolsa_cereales_argentina": "ARG_BOLSA_CEREALES",
    "amis_market_monitor": "FAO",
    "igc_global": "IGC_GOI",
    "faostat": "FAO",
    "conab_noticias": "CONAB",
    "antt_rntrc": "ANTT",
    "antt_mdfe_public": "ANTT",
    "epe_sienergia_biomass": "EPE",
    "ibge_pevs_biomass": "IBGE",
    "snif_forest_biomass": "BR_SNIF",
    "ons_biomass_generation": "ONS",
    "epe_ben_biomass": "EPE",
    "anp_biometano": "ANP",
    "whatsapp_freight_authorized": "WHATSAPP_AI",
    "ecmwf_open_data": "ECMWF",
    "gfs_nomads": "NOAA",
    "gefs_nomads": "NOAA",
}

PRIORIDADE_P0 = frozenset({
    "conab_armazens_cadastrados", "conab_safra_graos_xlsx",
    "imea_operational_xlsx", "cepea_prices", "mdic_comexstat",
    "mdic_comexstat_bulk", "antt_open_data", "antt_mdfe_public",
    "antt_rntrc", "antaq_operational", "official_port_lineups",
    "chm_navigational_notices", "ana_hidroweb",
    "usda_wasde", "usda_fas_psd", "sagyp_argentina",
    "sema_mt_sisflora",
})
CLASSES = frozenset({"dados", "radar", "conhecimento"})
VALID_STATUS = frozenset({"active", "gated", "planned", "blocked", "deprecated"})
ID = re.compile(r"^[a-z][a-z0-9_]+$")


class ErroLegado(ValueError):
    """Snapshot legado invalido ou incompatível."""


def _ler_json(arquivo: Path) -> dict:
    if arquivo.is_symlink() or not arquivo.is_file() or arquivo.stat().st_size > 3_000_000:
        raise ErroLegado("snapshot ausente, symlink ou acima do limite")
    try:
        obj = json.loads(arquivo.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ErroLegado("JSON legado invalido") from exc
    if not isinstance(obj, dict) or obj.get("project") != "NIVON":
        raise ErroLegado("projeto legado invalido")
    if obj.get("schema_version") != "1.0.0":
        raise ErroLegado("versao de snapshot nao suportada")
    return obj


def validar_snapshots(registro: dict, links: dict, catalogo: dict) -> None:
    if registro.get("role") != "LEGACY_REFERENCE_ONLY":
        raise ErroLegado("registro sem modo referencia")
    if links.get("role") != "CATALOG_LINKS_REFERENCE_ONLY":
        raise ErroLegado("links sem modo referencia")
    if registro.get("migration_policy", {}).get("enabled") is not False:
        raise ErroLegado("coleta do legado nao pode ser ativada")
    if registro.get("migration_policy", {}).get("scheduled") is not False:
        raise ErroLegado("agendamento do legado nao permitido")
    if registro.get("migration_policy", {}).get("rights_inherited") is not False:
        raise ErroLegado("direitos do legado nao podem ser herdados")
    if links.get("collection_enabled") is not False:
        raise ErroLegado("catalogo de URLs nao permite coleta")
    fontes = registro.get("sources")
    entries = links.get("links")
    atuais = catalogo.get("sources")
    datasets = catalogo.get("datasets")
    if not all(isinstance(a, list) for a in (fontes, entries, atuais, datasets)):
        raise ErroLegado("listas faltantes")
    vistos = set()
    for fonte in fontes:
        if not isinstance(fonte, dict):
            raise ErroLegado("fonte legada invalida")
        id_ = fonte.get("source_id")
        if not isinstance(id_, str) or not ID.fullmatch(id_) or id_ in vistos:
            raise ErroLegado("id legado invalido/duplicado")
        vistos.add(id_)
        if fonte.get("legacy_status") not in VALID_STATUS:
            raise ErroLegado("status legado invalido")
        if fonte.get("security_class") != "PUBLIC" and fonte.get("endpoint") is not None:
            raise ErroLegado("endpoint privado exposto")
    vistos = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise ErroLegado("URL legada invalida")
        url = entry["url"]
        split = urlsplit(url)
        if (split.scheme not in {"http", "https"} or not split.hostname
                or split.username or split.password or url in vistos):
            raise ErroLegado("URL historica duplicada/insegura")
        vistos.add(url)
        classes = entry.get("classes")
        if (not isinstance(classes, list) or not classes or len(classes) != len(set(classes))
                or any(c not in CLASSES for c in classes)):
            raise ErroLegado("classificacao de link invalida")
    ids_atuais = {x["id"] for x in atuais}
    ids_datasets = {x["id"] for x in datasets}
    if len(ids_atuais) != len(atuais) or len(ids_datasets) != len(datasets):
        raise ErroLegado("catalogo NIVON duplicado")
    for old, new in ALIAS_PROVEDORES.items():
        if old not in {s["source_id"] for s in fontes}:
            raise ErroLegado("alias legado inexistente: " + old)
        if new not in ids_atuais:
            raise ErroLegado("alias aponta para fonte inexistente: " + new)


def gerar_relatorio(registro: dict, links: dict, catalogo: dict) -> dict:
    """Nao modifica o catalogo canônico, nao consulta URLs nem liga coletores."""
    validar_snapshots(registro, links, catalogo)
    source_ids = {x["id"] for x in catalogo["sources"]}
    datasets = catalogo["datasets"]
    itens = []
    for old in registro["sources"]:
        legado_id = old["source_id"]
        alias = ALIAS_PROVEDORES.get(legado_id)
        atual = alias if alias in source_ids else (
            legado_id.upper() if legado_id.upper() in source_ids else None
        )
        candidatos = sorted(d["id"] for d in datasets if d["source_id"] == atual)
        if atual is None:
            proxima = "CADASTRAR_OU_MAPEAR_PROVEDOR"
        elif old.get("execution_ref"):
            proxima = "COMPARAR_CODIGO_PARSER_E_CONTRATOS"
        else:
            proxima = "RECONCILIAR_DATASETS_E_DIREITOS"
        itens.append({
            "fonte_legada": legado_id,
            "fonte_nivon": atual,
            "datasets_nivon": candidatos,
            "status_historico_agrolog": old["legacy_status"],
            "tipo": old.get("type"),
            "metodo": old.get("method"),
            "referencia_codigo_agrolog": old.get("execution_ref"),
            "prioridade_migracao": "P0" if legado_id in PRIORIDADE_P0 else "P1",
            "proxima_acao": proxima,
            "estado_nivon": "REFERENCIA_NAO_HOMOLOGADA",
            "coleta_habilitada": False,
            "direitos_herdados": False,
        })
    urls = links["links"]
    classes = Counter(c for row in urls for c in row["classes"])
    statuses = Counter(row["status_historico_agrolog"] for row in itens)
    sem_match = [row["fonte_legada"] for row in itens if row["fonte_nivon"] is None]
    return {
        "schema_version": "1.0.0",
        "operacao": "CONCILIACAO_OFFLINE_SEM_COLETA",
        "origem_registro": registro["upstream"],
        "origem_links": links["origin"],
        "resumo": {
            "fontes_legadas": len(itens),
            "fontes_com_provedor_nivon": len(itens) - len(sem_match),
            "fontes_sem_provedor_correspondente": len(sem_match),
            "fontes_historicamente_ativas_no_agrolog": statuses["active"],
            "urls_historicas_unicas": len(urls),
            "urls_por_classe": dict(sorted(classes.items())),
            "datasets_nivon_consultados": len(datasets),
            "coletores_habilitados_pela_migracao": 0,
        },
        "fontes_sem_correspondencia": sem_match,
        "conciliacao": itens,
    }


def executar(*, so_resumo: bool = False) -> dict:
    registro = _ler_json(REGISTRO)
    links = _ler_json(LINKS)
    catalogo = _ler_json(NIVON)
    resultado = gerar_relatorio(registro, links, catalogo)
    if so_resumo:
        return {k: v for k, v in resultado.items() if k != "conciliacao"}
    return resultado


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Conciliar legado AgroLog com NIVON offline")
    p.add_argument("--resumo", action="store_true")
    p.add_argument("--saida", type=Path, help="salvar relatorio JSON local")
    args = p.parse_args(argv)
    try:
        result = executar(so_resumo=args.resumo)
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.saida:
            if args.saida.is_symlink():
                raise ErroLegado("destino symlink proibido")
            args.saida.parent.mkdir(parents=True, exist_ok=True)
            args.saida.write_text(content, encoding="utf-8")
        else:
            print(content, end="")
        return 0
    except (ErroLegado, OSError) as exc:
        print(json.dumps({"erro": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
