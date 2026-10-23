"""Entrada operacional PTAX: consulta HTTP para quarentena, apenas opt-in.

Exemplo após autorização do Source Registry:
PYTHONPATH=src python scripts/coletar_ptax_quarentena.py \\
  --catalogo config/fontes_nivon_master.v1.json \\
  --banco /dados/nivon_ptax_quarentena.sqlite \\
  --moeda USD --inicio 2026-10-19 --fim 2026-10-23 \\
  --permitir-rede --evidencia-direitos DOC_INTERNO_VALIDADO

Sem aprovações no catálogo, a execução falha ANTES de criar banco,
chamar rede ou adicionar observações. Nenhuma autorização é simulada.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from nivon.captura_ptax_http import _autorizado
from nivon.coletor_ptax_quarentena import executar_coleta_ptax_quarentena
from nivon.ptax_plano import planejar_consultas_ptax


class ErroCLIQuarentenaPTAX(ValueError):
    pass


def _catalogo(path: str) -> dict:
    f = Path(path)
    if f.is_symlink() or not f.is_file() or f.stat().st_size > 500_000:
        raise ErroCLIQuarentenaPTAX("arquivo de catálogo inválido")
    with f.open("rb") as stream:
        dados = stream.read(500_001)
    if len(dados) > 500_000:
        raise ErroCLIQuarentenaPTAX("catálogo excessivo")
    try:
        d = json.loads(dados.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ErroCLIQuarentenaPTAX("catálogo JSON inválido") from exc
    if not isinstance(d, dict) or not isinstance(d.get("datasets"), list):
        raise ErroCLIQuarentenaPTAX("estrutura de catálogo inválida")
    return d


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description="Captura HTTPS PTAX somente com direitos e rede opt-in"
    )
    parser.add_argument("--catalogo", required=True)
    parser.add_argument("--banco", required=True)
    parser.add_argument("--moeda", choices=["USD", "EUR"], required=True)
    parser.add_argument("--inicio", required=True)
    parser.add_argument("--fim", required=True)
    parser.add_argument("--dias-janela", type=int, default=4)
    parser.add_argument("--permitir-rede", action="store_true")
    parser.add_argument("--evidencia-direitos")
    args = parser.parse_args(argv)
    planos = planejar_consultas_ptax(
        moeda=args.moeda, inicio=args.inicio, fim=args.fim,
        dias_janela=args.dias_janela,
    )
    if len(planos) > 8:
        raise ErroCLIQuarentenaPTAX("máximo de oito consultas por execução")
    catalogo = _catalogo(args.catalogo)
    if not args.permitir_rede:
        raise PermissionError("rede desativada: usar --permitir-rede")
    direitos = frozenset(("COLETA", "ARMAZENAMENTO"))
    _autorizado(catalogo, direitos, args.evidencia_direitos)
    caminho = Path(args.banco)
    if caminho.is_symlink() or (
        caminho.exists() and not caminho.is_file()
    ) or caminho.parent.is_symlink() or not caminho.parent.is_dir():
        raise ErroCLIQuarentenaPTAX("destino do banco inválido")
    with sqlite3.connect(caminho) as db:
        db.execute("PRAGMA foreign_keys=ON")
        return executar_coleta_ptax_quarentena(
            db, planos=planos, catalogo=catalogo,
            permitir_rede=True, autorizacoes=direitos,
            evidencia_direitos=args.evidencia_direitos,
        )


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, sort_keys=True))
