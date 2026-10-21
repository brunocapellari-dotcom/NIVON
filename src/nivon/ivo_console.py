"""Linha de comando read-only do IVO. Não executa motor ou provedor de IA."""
from __future__ import annotations

import argparse
import json

from .ivo_planejador import ErroPlanejamento, planejar_consulta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="IVO: planejar consulta interdisciplinar sem coletar dados, prever ou gastar."
    )
    parser.add_argument("--pergunta", required=True, help="Pergunta sobre uma cultura, mercado ou domínio.")
    parser.add_argument("--max-frentes", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        resultado = planejar_consulta(args.pergunta, max_frentes=args.max_frentes)
    except (ErroPlanejamento, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "BLOQUEADO", "erro": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
