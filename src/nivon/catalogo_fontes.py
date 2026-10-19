"""Catálogo Mestre NIVON v1 — único inventário de fontes e datasets.

A consulta NÃO autoriza coleta. Lê metadados versionados e monta um plano
sem rede, segredos, acesso a contas ou ações agendadas.
"""
from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "config" / "fontes_nivon_master.v1.json"
GRUPOS = frozenset({
    "SAFRA", "BALANCO", "GEO", "INDUSTRIA", "PECUARIA", "COMEX", "LOGISTICA",
    "PORTOS", "ENERGIA", "FERTILIZANTES", "PRECOS", "CLIMA", "HIDRO", "MACRO", "RADAR",
})
PRIORIDADES = ("P0", "P1", "P2")
ESTAGIOS = frozenset({
    "REAL_SNAPSHOT_TESTED", "CODE_PRESENT", "DISCOVERY_ONLY",
    "CANDIDATE", "BLOCKED_RIGHTS",
})
DIREITOS = frozenset({"REVIEW", "ATTRIBUTION_REVIEW", "RESTRICTED"})
PRODUTOS_ESTRATEGICOS = frozenset({
    "SOJA", "MILHO", "ALGODAO", "BOI", "BEZERRO",
    "ACUCAR", "TRIGO", "SORGO", "FERTILIZANTES", "DIESEL",
})
MODOS_CADENCIA = frozenset({
    "HOURLY", "SIX_HOURLY", "TWICE_DAILY", "INTRADAY", "DAILY",
    "WEEKLY", "BIWEEKLY", "MONTHLY", "QUARTERLY",
    "QUADRIMESTRAL", "ANNUAL", "SEASONAL", "IRREGULAR",
})


class ErroCatalogo(ValueError):
    pass


def carregar_catalogo(caminho: str | Path = DEFAULT) -> dict:
    """Somente um arquivo JSON local; falha fechado se estrutura divergir."""
    arq = Path(caminho)
    if arq.is_symlink() or not arq.is_file() or arq.suffix.lower() != ".json":
        raise ErroCatalogo("arquivo do catálogo deve ser JSON local regular")
    if arq.stat().st_size > 250_000:
        raise ErroCatalogo("catálogo excessivo")
    try:
        obj = json.loads(arq.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroCatalogo("catálogo inválido") from exc
    validar_catalogo(obj)
    return obj


def validar_catalogo(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("project") != "NIVON":
        raise ErroCatalogo("metadados NIVON ausentes")
    if doc.get("schema_version") != "1.0.0":
        raise ErroCatalogo("versão do contrato não suportada")
    if doc.get("default_policy") != "DENY_ALL_SCHEDULED_FETCHES_UNTIL_RIGHTS_AND_PARSER_HOMOLOGATED":
        raise ErroCatalogo("política de execução não é deny-by-default")
    if doc.get("dates_required") != ["competencia", "referencia", "publicacao", "coleta"]:
        raise ErroCatalogo("quatro datas obrigatórias incorretas")
    fontes = doc.get("sources")
    conjuntos = doc.get("datasets")
    if not isinstance(fontes, list) or not isinstance(conjuntos, list):
        raise ErroCatalogo("listas de fontes/datasets ausentes")
    ids_fontes: set[str] = set()
    for fonte in fontes:
        if not isinstance(fonte, dict):
            raise ErroCatalogo("fonte inválida")
        id_ = fonte.get("id")
        if not isinstance(id_, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,70}", id_) or id_ in ids_fontes:
            raise ErroCatalogo("fonte repetida ou id inválido")
        ids_fontes.add(id_)
        if fonte.get("rights") not in DIREITOS:
            raise ErroCatalogo(f"{id_}: direitos inválidos")
        if not isinstance(fonte.get("provider"), str) or not fonte["provider"].strip():
            raise ErroCatalogo(f"{id_}: provedor não identificado")
        url = fonte.get("official_url")
        if not isinstance(url, str):
            raise ErroCatalogo(f"{id_}: URL ausente")
        p = urlsplit(url)
        if (p.scheme != "https" or not p.hostname or p.username or p.password or
                p.port not in (None, 443)):
            raise ErroCatalogo(f"{id_}: URL insegura")
    ids: set[str] = set()
    grupos: set[str] = set()
    produtos: set[str] = set()
    for dado in conjuntos:
        if not isinstance(dado, dict):
            raise ErroCatalogo("dataset inválido")
        id_ = dado.get("id")
        if (not isinstance(id_, str) or
                not re.fullmatch(r"[A-Z][A-Z0-9_]{2,90}", id_) or id_ in ids):
            raise ErroCatalogo("dataset com id inválido ou duplicado")
        ids.add(id_)
        if dado.get("source_id") not in ids_fontes:
            raise ErroCatalogo(f"{id_}: fonte inexistente")
        if dado.get("group") not in GRUPOS:
            raise ErroCatalogo(f"{id_}: grupo desconhecido")
        grupos.add(dado["group"])
        if dado.get("stage") not in ESTAGIOS or dado.get("priority") not in PRIORIDADES:
            raise ErroCatalogo(f"{id_}: estágio/prioridade inválidos")
        if dado.get("cadence") not in MODOS_CADENCIA:
            raise ErroCatalogo(f"{id_}: periodicidade inválida")
        if any(dado.get(key) is not False for key in (
                "enabled", "collection_authorized", "commercial_redistribution_authorized")):
            raise ErroCatalogo(f"{id_}: coleta/direito habilitado sem gate explícito")
        if dado.get("data_dates_required") != doc["dates_required"]:
            raise ErroCatalogo(f"{id_}: contrato temporal incompleto")
        if dado.get("downstream_contract") != "OBSERVACAO_CANONICA_V1":
            raise ErroCatalogo(f"{id_}: contrato canônico incompatível")
        if (not isinstance(dado.get("topic"), str) or not dado["topic"].strip()
                or not isinstance(dado.get("mode"), str) or not dado["mode"].strip()):
            raise ErroCatalogo(f"{id_}: tema ou modo ausente")
        ps = dado.get("products")
        if not isinstance(ps, list) or not ps or any(not isinstance(x, str) or not x for x in ps):
            raise ErroCatalogo(f"{id_}: produtos ausentes")
        produtos.update(ps)
    faltam = PRODUTOS_ESTRATEGICOS - produtos
    if faltam:
        raise ErroCatalogo("produtos estratégicos sem cobertura: " + ",".join(sorted(faltam)))
    if not GRUPOS <= grupos:
        raise ErroCatalogo("domínios não cobertos: " + ",".join(sorted(GRUPOS-grupos)))
    ports = {d["id"] for d in conjuntos if d["id"].startswith("LINEUP_")}
    if len(ports) != 10:
        raise ErroCatalogo("cadastro marítimo precisa de 10 portos brasileiros distintos")
    return {"fontes": len(fontes), "datasets": len(conjuntos), "grupos": len(grupos),
            "commodities_estrategicas": len(PRODUTOS_ESTRATEGICOS),
            "portos_br": len(ports), "coletas_ativadas": 0}


def diagnostico(doc: dict, *, grupo: str | None = None,
                produto: str | None = None, prioridade: str | None = None) -> dict:
    dados = doc["datasets"]
    if grupo:
        if grupo not in GRUPOS:
            raise ErroCatalogo("grupo inexistente")
        dados = [d for d in dados if d["group"] == grupo]
    if produto:
        dados = [d for d in dados if produto.upper() in d["products"]]
    if prioridade:
        if prioridade not in PRIORIDADES:
            raise ErroCatalogo("prioridade inválida")
        dados = [d for d in dados if d["priority"] == prioridade]
    stages = Counter(d["stage"] for d in dados)
    grupos = Counter(d["group"] for d in dados)
    return {"total": len(dados), "por_estagio": dict(sorted(stages.items())),
            "por_grupo": dict(sorted(grupos.items())),
            "prontos_para_agendar": 0,
            "bloqueados_ate_gates": len(dados),
            "datasets": [{
                "id": d["id"], "source_id": d["source_id"], "stage": d["stage"],
                "priority": d["priority"], "mode": d["mode"],
                "cadence": d["cadence"], "next_gate": proximo_gate(d, doc)
            } for d in dados]}


def proximo_gate(dado: dict, doc: dict) -> str:
    fonte = next(f for f in doc["sources"] if f["id"] == dado["source_id"])
    if fonte["rights"] == "RESTRICTED" or dado["stage"] == "BLOCKED_RIGHTS":
        return "DIREITOS_COMERCIAIS: nao acessar/redistribuir sem licenca"
    if dado["stage"] == "REAL_SNAPSHOT_TESTED":
        return "VALIDAR_DIREITOS_POR_OPERACAO_E_HISTORICO_PERSISTENTE"
    if dado["stage"] == "CODE_PRESENT":
        return "HOMOLOGAR_COLETA_REAL_SCHEMA_E_COBERTURA"
    return "RESOLVER_ENDPOINT_DOCUMENTADO_DIREITOS_E_PARSER"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="NIVON: catálogo único de coletores (somente leitura)")
    p.add_argument("--arquivo", default=str(DEFAULT))
    p.add_argument("--grupo")
    p.add_argument("--produto")
    p.add_argument("--prioridade", choices=PRIORIDADES)
    p.add_argument("--resumo", action="store_true")
    args = p.parse_args(argv)
    try:
        doc = carregar_catalogo(args.arquivo)
        resultado = diagnostico(doc, grupo=args.grupo, produto=args.produto,
                                 prioridade=args.prioridade)
        if args.resumo:
            resultado.pop("datasets")
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ErroCatalogo) as exc:
        print(json.dumps({"status": "CATALOGO_INVALIDO", "erro": str(exc)},ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
