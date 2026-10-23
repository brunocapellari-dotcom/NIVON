"""Executa painel operacional NIVON em um lote JSON local, sem rede ou Cloud."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nivon.painel_operacional import ErroMotor
from nivon.ponte_painel_fontes import analisar_fontes


def _sem_chaves_duplicadas(pares):
    resultado = {}
    for chave, valor in pares:
        if chave in resultado:
            raise ErroMotor("chave JSON duplicada: " + chave)
        resultado[chave] = valor
    return resultado


def executar(arquivo: str, *, as_of: str, executar_bigquery: bool = False) -> dict:
    origem = Path(arquivo)
    if not origem.is_file() or origem.is_symlink():
        raise ErroMotor("arquivo de entrada precisa ser arquivo local regular")
    if origem.stat().st_size > 5_000_000:
        raise ErroMotor("entrada maior que 5MB")
    pacote = json.loads(
        origem.read_text(encoding="utf-8"),
        object_pairs_hook=_sem_chaves_duplicadas,
        parse_constant=lambda _: (_ for _ in ()).throw(ErroMotor("NaN/Infinity nao permitido")),
    )
    return analisar_fontes(pacote, as_of=as_of, executar_bigquery=executar_bigquery)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Painel NIVON logistica + AIS + tendencias (shadow)")
    parser.add_argument("--entrada", required=True, help="pacote JSON local")
    parser.add_argument("--as-of", required=True, help="timestamp ISO UTC ou com offset")
    parser.add_argument("--executar-bigquery", action="store_true",\n                        help="autoriza leitura BigQuery via ADC/WIF; pode gerar custo")
    a = parser.parse_args(argv)
    try:
        saida = executar(a.entrada, as_of=a.as_of, executar_bigquery=a.executar_bigquery)
    except (ErroMotor, OSError, ValueError) as exc:
        print(json.dumps({"status": "FALHA_FECHADA", "erro": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
