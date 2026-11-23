#!/usr/bin/env python3
"""Contrato conservador: não publicar séries restritas via artefatos do GitHub.

Requer catálogo F4 completo. Este programa NÃO inspeciona o conteúdo de
artefatos em runtime; é uma barreira estática, complementar à governança de dados.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import yaml

CHAVES_BLOQUEADAS = (
    ".csv", ".parquet", ".xlsx", ".xls", ".jsonl", ".ndjson",
    ".sqlite", ".db", ".zip", "nivon_raw", "nivon_stage", "nivon_core",
    "raw/", "stage/", "core/", "series/",
)
ACOES_PUBLICACAO = ("actions/upload-artifact@", "actions/upload-release-asset@")
COMANDOS_PUBLICACAO = ("gh release upload ",)


def catalogar(caminho: Path) -> tuple[set[str], set[str]]:
    if not caminho.is_file():
        raise ValueError(f"Catálogo F4 obrigatório ausente: {caminho}")
    objeto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    if not isinstance(objeto, dict):
        raise ValueError("O catálogo deve ser um mapa YAML com a chave fontes.")
    lista = objeto.get("fontes")
    if isinstance(lista, dict):
        itens = [(str(k), v) for k, v in lista.items()]
    elif isinstance(lista, list):
        itens = [(str(item.get("id", "")), item) for item in lista
                 if isinstance(item, dict)]
        if len(itens) != len(lista):
            raise ValueError("Cada fonte precisa ser um mapa.")
    else:
        raise ValueError("Catálogo F4 precisa definir 'fontes' (lista ou mapa).")
    if not itens:
        raise ValueError("Catálogo de fontes vazio.")
    todas, restritas = set(), set()
    for identificador, fonte in itens:
        if not identificador or not isinstance(fonte, dict):
            raise ValueError(f"Entrada de fonte inválida: {identificador!r}")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", identificador):
            raise ValueError(f"ID inválido: {identificador}")
        if identificador in todas:
            raise ValueError(f"ID duplicado: {identificador}")
        todas.add(identificador)
        publicacao = fonte.get("publicacao")
        if not isinstance(publicacao, dict) or not isinstance(
            publicacao.get("serie_em_artefato_publico"), bool
        ):
            raise ValueError(
                f"Fonte {identificador}: F4 deve declarar bool "
                "'publicacao.serie_em_artefato_publico'."
            )
        if not publicacao["serie_em_artefato_publico"]:
            restritas.add(identificador)
    return todas, restritas


def verificar(workflows: Path, restritas: set[str]) -> list[str]:
    erros = []
    caminhos = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")])
    if not caminhos:
        return ["Não existem workflows para auditar."]
    for caminho in caminhos:
        try:
            documento = yaml.safe_load(caminho.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            erros.append(f"{caminho}: YAML inválido: {exc}")
            continue
        if not isinstance(documento, dict):
            erros.append(f"{caminho}: documento YAML vazio ou não mapeado.")
            continue
        jobs = documento.get("jobs", {})
        if not isinstance(jobs, dict):
            erros.append(f"{caminho}: jobs inválidos.")
            continue
        for nome, job in jobs.items():
            if not isinstance(job, dict):
                continue
            passos = job.get("steps", [])
            if not isinstance(passos, list):
                continue
            possui_artefato = any(
                isinstance(passo, dict) and (
                    any(a in str(passo.get("uses", "")).lower() for a in ACOES_PUBLICACAO)
                    or any(a in str(passo.get("run", "")).lower() for a in COMANDOS_PUBLICACAO)
                )
                for passo in passos
            )
            if not possui_artefato:
                continue
            # Rejeita jobs que referenciam qualquer fonte restrita.
            texto = str(job).lower()
            for origem in sorted(restritas):
                if re.search(r"(?<![a-z0-9])" + re.escape(origem) + r"(?![a-z0-9])", texto):
                    erros.append(
                        f"{caminho}:{nome}: publicação vinculada à fonte restrita {origem}."
                    )
            for passo in passos:
                if not isinstance(passo, dict):
                    continue
                acao = str(passo.get("uses", "")).lower()
                if any(a in acao for a in ACOES_PUBLICACAO):
                    campos = passo.get("with", {})
                    if not isinstance(campos, dict):
                        erros.append(f"{caminho}:{nome}: publicação sem parâmetros auditáveis.")
                        continue
                    caminho_artifact = str(campos.get("path", "")).lower()
                    if not caminho_artifact:
                        erros.append(f"{caminho}:{nome}: artefato sem path explícito.")
                    if any(entrada in caminho_artifact for entrada in CHAVES_BLOQUEADAS):
                        erros.append(
                            f"{caminho}:{nome}: caminho de série ou dado bruto em artefato."
                        )
    return erros


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogo", type=Path, default=Path("config/fontes.yaml"))
    parser.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    args = parser.parse_args(argv)
    try:
        todas, restritas = catalogar(args.catalogo)
        erros = verificar(args.workflows, restritas)
    except (OSError, ValueError) as exc:
        print(f"ERRO_AUDITORIA_PUBLICACAO: {exc}", file=sys.stderr)
        return 1
    for erro in erros:
        print(f"ERRO_AUDITORIA_PUBLICACAO: {erro}", file=sys.stderr)
    print(f"F5_FONTES={len(todas)} F5_RESTRITAS={len(restritas)} "
          f"F5_VIOLACOES={len(erros)}")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
