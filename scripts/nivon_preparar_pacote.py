"""Validador editorial NIVON somente leitura, sem chaves ou envio.

PYTHONPATH=src python scripts/nivon_preparar_pacote.py pacote.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from nivon.pacote_editorial_offline import avaliar_pacote_offline, avaliar_lote_offline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Avaliar pacote sem enviar")
    parser.add_argument("pacote")
    parser.add_argument("--lote", action="store_true", help="Entrada é lista de pacotes")
    args = parser.parse_args(argv)
    try:
        arquivo = Path(args.pacote)
        if not arquivo.is_file() or arquivo.stat().st_size > 2_000_000:
            raise ValueError("pacote inexistente ou excessivo")
        pacote = json.loads(arquivo.read_text(encoding="utf-8"))
        if args.lote:
            resultado = avaliar_lote_offline(pacote)
            print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
            return 0 if resultado["bloqueados"] == 0 else 1
        resultado = avaliar_pacote_offline(pacote)
        pre = resultado["preflight"]
        print(json.dumps({
            "estado": resultado["estado"], "bloqueios": pre["bloqueios"][:40],
            "lacunas": pre["lacunas"][:40],
            "quantidades": pre.get("quantidades", {}),
            "envio_habilitado": False,
            "nota": "Sem verificação de emissores reais ou autorização de envio",
        }, ensure_ascii=False, sort_keys=True))
        return 0 if resultado["estado"] == "PREVALIDADO_OFFLINE" else 1
    except (OSError, ValueError, TypeError, KeyError):
        print("Pacote inválido; nenhum envio ou arquivo alterado", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
