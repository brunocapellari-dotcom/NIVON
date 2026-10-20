"""Estado auditável da cobertura nacional de line-up do NIVON.

Catálogo ≠ coletor ativo. Índice institucional ≠ programação atual.
Não faz HTTP. Mantém terminais privados e portos pais distintos.
"""
from __future__ import annotations

import json
from collections import Counter

from .catalogo_fontes import carregar_catalogo
from .lineup_nacional import carregar_escopo
from .rotas_coleta import carregar_rotas, validar_rotas


def diagnosticar_portos(*, catalogo: dict | None = None, escopo: dict | None = None,
                        rotas: dict | None = None) -> dict:
    cat = catalogo if catalogo is not None else carregar_catalogo()
    inv = escopo if escopo is not None else carregar_escopo()
    rts = rotas if rotas is not None else carregar_rotas()
    validar_rotas(rts,cat)
    datasets={x["id"]:x for x in cat["datasets"]}
    routemap={x["dataset_id"]:x for x in rts["entries"]}
    found=[]
    for p in inv["ports"]:
        key="LINEUP_"+p["id"]
        d=datasets.get(key)
        r=routemap.get(key)
        if not d or not r:
            raise ValueError("porto sem dataset e rota canônica: "+p["id"])
        loc=r["locator"]
        if p["kind"]=="TUP_OU_COMPLEXO_CANDIDATO":
            stage="TUP_OU_COMPLEXO_CANDIDATO_SEM_DIREITOS"
        elif p.get("discovery_status")=="OFFICIAL_NAVIGATION_INDEX_ONLY":
            stage="INDICE_INSTITUCIONAL_SEM_DOCUMENTO_INDIVIDUAL"
        elif p.get("discovery_status")=="PUBLIC_PAGE_CANDIDATE_UNVERIFIED":
            stage="PAGINA_CANDIDATA_SEM_PARSER_HOMOLOGADO"
        elif loc["url"] is None:
            stage="URL_OPERACIONAL_NAO_LOCALIZADA"
        else:
            stage="PORTAL_CANDIDATO_A_HOMOLOGACAO"
        found.append({
            "porto_id":p["id"],"nome":p["name"],"uf":p["uf"],
            "tipo":p["kind"],"porto_pai":p.get("parent_port_id"),
            "estado":stage,"url_candidata":loc["url"],
            "parser_homologado":p["parser_homologated"],
            "coleta_ativa":r["runtime_enabled"],
            "publicacao_autorizada":d["commercial_redistribution_authorized"],
            "bloqueios":r["gates_missing"],
            "ultimo_dado_real_verificado":r["last_verified_data"],
        })
    categorias=Counter(x["estado"] for x in found)
    return {
        "unidades_cadastradas":len(found),
        "portos_organizados":sum(p["kind"]=="PORTO_ORGANIZADO" for p in inv["ports"]),
        "tups_e_complexos_candidatos":sum(p["kind"]=="TUP_OU_COMPLEXO_CANDIDATO" for p in inv["ports"]),
        "paginas_ou_indices_candidatos":sum(x["url_candidata"] is not None for x in found),
        "parsers_homologados":sum(x["parser_homologado"] for x in found),
        "coletas_ativas":sum(x["coleta_ativa"] for x in found),
        "publicacoes_autorizadas":sum(x["publicacao_autorizada"] for x in found),
        "por_estado_documental":dict(sorted(categorias.items())),
        "unidades":found,
        "nota":"Cobertura é inventário documental; não equivale a registros de navios válidos ou atualizados.",
    }


def main() -> None:
    print(json.dumps(diagnosticar_portos(),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
