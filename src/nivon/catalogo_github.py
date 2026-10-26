"""Consulta local do catálogo de fontes GitHub consolidado no NIVON.

Sem acesso à rede, não importa bibliotecas externas nem ativa coletas.
Diferencia INVENTARIADO / IMPLEMENTADO / ATIVADO / HOMOLOGADO.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CATALOGO = Path(__file__).resolve().parents[2] / "config" / "catalogo_integracoes_github_20261026.json"

class ErroCatalogo(ValueError):
    pass


def consultar_catalogo(*, arquivo=None, secao=None, status=None):
    caminho = Path(arquivo) if arquivo is not None else CATALOGO
    if caminho.is_symlink() or not caminho.is_file():
        raise ErroCatalogo("arquivo de catálogo indisponível ou inseguro")
    doc = json.loads(caminho.read_text(encoding="utf-8"))
    if doc.get("schema") != "nivon.integracoes.github.v1":
        raise ErroCatalogo("schema do catálogo desconhecido")
    if secao not in (None, "repositorios", "datasets_agrobr_2_0"):
        raise ErroCatalogo("seção inválida")
    partes = (secao,) if secao is not None else ("repositorios", "datasets_agrobr_2_0")
    saida = {}
    for parte in partes:
        dados = doc.get(parte)
        if not isinstance(dados, list):
            raise ErroCatalogo("seção sem lista de entradas")
        elementos = [
            d for d in dados if isinstance(d, dict) and
            (status is None or (d.get("decisao") if parte == "repositorios"
                                 else d.get("integracao")) == status)
        ]
        if len({d.get("id") for d in elementos}) != len(elementos):
            raise ErroCatalogo("identificadores duplicados")
        saida[parte] = elementos
    saida["referencia"] = doc["referencia"]
    saida["situacao"] = doc.get("prontidao", {})
    saida["nota"] = "Inventário não equivale a execução em GCP, coleta ou validação"
    return saida


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON — catálogo de fontes documentadas")
    p.add_argument("--secao", choices=("repositorios", "datasets_agrobr_2_0"))
    p.add_argument("--status", help="Filtro exato de decisão ou estado de integração")
    opts = p.parse_args(argv)
    print(json.dumps(consultar_catalogo(secao=opts.secao, status=opts.status),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
