"""CLI de análise local: CSVs já obtidos com autorização, sem coleta pela rede.

Uso: PYTHONPATH=src python -m nivon.analise_local --config contrato.json
A configuração define mapeamentos reais verificados; nenhuma coluna é inventada.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .destinos import Terminal, analisar_destinos
from .importadores import mapear_fabricas, mapear_fluxos
from .ingestao import ContratoCSV, ler_csv_local


def _ler_json(path: str) -> dict:
    data = Path(path).read_bytes()
    if len(data) > 100_000:
        raise ValueError("configuração excede limite de 100 KB")
    item = json.loads(data.decode("utf-8"))
    if not isinstance(item, dict):
        raise ValueError("configuração deve ser objeto")
    return item


def _csv(definicao: dict) -> list[dict]:
    mapa = definicao["colunas"]
    item = ler_csv_local(
        definicao["caminho"],
        ContratoCSV(
            fonte_id=definicao["fonte_id"],
            campos_obrigatorios=tuple(mapa.values()),
            status_fonte=definicao.get("status", "PENDENTE"),
            operacoes_autorizadas=frozenset(definicao.get("operacoes", [])),
            tamanho_maximo=int(definicao.get("limite_bytes", 30_000_000)),
            linhas_maximas=int(definicao.get("limite_linhas", 500_000)),
        ),
        competencia=definicao["competencia"],
        referencia=definicao["referencia"],
        publicacao=definicao["publicacao"],
    )
    return item["linhas"]


def executar(config: dict) -> dict:
    for nome in ("antt", "mapa", "terminais", "mes_corte"):
        if nome not in config:
            raise ValueError(f"configuração sem {nome}")
    fabrica_cfg = config["mapa"]
    fluxo_cfg = config["antt"]
    fabricas = mapear_fabricas(
        _csv(fabrica_cfg), fabrica_cfg["colunas"], fonte_id=fabrica_cfg["fonte_id"],
        situacoes_ativas=frozenset(fabrica_cfg["dominios"]["situacoes_ativas"]),
        situacoes_inativas=frozenset(fabrica_cfg["dominios"]["situacoes_inativas"]),
        atividades_fabricante=frozenset(fabrica_cfg["dominios"]["atividades_fabricante"]),
        atividades_nao_fabricante=frozenset(fabrica_cfg["dominios"]["atividades_nao_fabricante"]),
        areas_alimentacao_animal=frozenset(fabrica_cfg["dominios"]["areas_alimentacao_animal"]),
        areas_nao_alimentacao_animal=frozenset(fabrica_cfg["dominios"]["areas_nao_alimentacao_animal"]),
    )
    dados = mapear_fluxos(_csv(fluxo_cfg), fluxo_cfg["colunas"], fonte_id=fluxo_cfg["fonte_id"])
    terminais = [
        Terminal(t["uf"], t["municipio"], t["tipo"], frozenset(t["produtos"]), t["fonte_id"])
        for t in config["terminais"]
    ]
    resultado = analisar_destinos(
        dados["fluxos"], fabricas, terminais,
        mes_corte=config["mes_corte"],
        janela_meses=int(config.get("janela_meses", 12)),
        min_meses_recorrentes=int(config.get("min_meses_recorrentes", 3)),
    )
    resultado["auditoria_importacao"] = {
        "total_fabricas_cadastradas_no_arquivo": len(fabricas),
        "fabricas_elegiveis": sum(f.elegivel for f in fabricas),
        "terminais_referenciados": len(terminais),
        "linhas_sem_ncm": dados["linhas_ncm_ausente"],
        "toneladas_sem_ncm": dados["toneladas_sem_ncm_t"],
        "linhas_ncm_outros": dados["linhas_outros_produtos"],
        "status": "NAO_HOMOLOGADO_COM_DADOS_REAIS",
    }
    return resultado


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="NIVON — cruzamento offline de fluxos MT × MAPA × terminais")
    p.add_argument("--config", required=True, help="JSON privado com mapeamentos e direitos por operação")
    args = p.parse_args(argv)
    try:
        resultado = executar(_ler_json(args.config))
    except (OSError, ValueError, KeyError, TypeError, PermissionError) as exc:
        print(f"ERRO_CONTRATO: {type(exc).__name__} — {exc}", file=sys.stderr)
        return 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
