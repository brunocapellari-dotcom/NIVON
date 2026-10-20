"""Validação estática da pesquisa histórico-científica contra catálogos canônicos."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit
from .catalogo_fontes import carregar_catalogo
from .rotas_coleta import carregar_rotas, validar_rotas
from .cobertura import carregar_matriz
from .registro_motores import carregar_registro, validar_registro

ROOT = Path(__file__).resolve().parents[2]


def auditoria_pesquisa() -> dict:
    fonte = carregar_catalogo()
    rotas = carregar_rotas()
    validar_rotas(rotas, fonte)
    matriz = carregar_matriz(catalogo=fonte)
    motores = validar_registro(carregar_registro(), matriz)
    p = ROOT / "config" / "catalogo_tecnico_historico.v1.json"
    b = ROOT / "config" / "bibliotecas_cientificas.v1.json"
    hist = json.loads(p.read_text(encoding="utf-8"))
    libs = json.loads(b.read_text(encoding="utf-8"))
    if hist.get("project") != "NIVON" or libs.get("project") != "NIVON":
        raise ValueError("pesquisa de projeto desconhecido")
    ids = {d["id"] for d in fonte["datasets"]}
    vistos = set()
    for item in hist["historical_sources"]:
        did = item["id"]
        if did not in ids or did in vistos:
            raise ValueError("fonte histórica fora do catálogo ou duplicada: " + did)
        vistos.add(did)
        url = urlsplit(item["evidence"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("evidência com URL inválida: " + did)
        if not item.get("history") or not item.get("nature") or not item.get("risk"):
            raise ValueError("base sem natureza/história/limites: " + did)
        if item.get("status", "").startswith("OPERATIONAL"):
            raise ValueError("declaração de homologação indevida")
    repos = set()
    for item in libs["items"]:
        nome = item["repo"]
        if nome in repos or nome.count("/") != 1:
            raise ValueError("biblioteca/repositório repetido ou inválido")
        repos.add(nome)
        if not item.get("license") or not item.get("decision"):
            raise ValueError("biblioteca sem licença ou decisão")
    if any(d["enabled"] or d["collection_authorized"] for d in fonte["datasets"]):
        raise ValueError("fonte ativada sem auditoria")
    return {
        "fontes": len(fonte["sources"]),
        "datasets": len(fonte["datasets"]),
        "rotas": len(rotas["entries"]),
        "historicos_documentados": len(vistos),
        "repositorios_inspecionados": len(repos),
        "motores_cadastrados": motores["frentes"],
        "homologados": motores["modelos_preditivos_homologados"],
        "status": "CADASTRO_CONSISTENTE_NAO_OPERACIONAL",
    }


if __name__ == "__main__":
    print(json.dumps(auditoria_pesquisa(), ensure_ascii=False, indent=2))
