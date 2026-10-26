"""Utilitário de diagnóstico manual, sem chamadas externas nem implantação."""
import argparse
import json
from pathlib import Path

from .core import catalogo, diagnostico, limitar_contexto
from .engenharia import dependencias_python, importar_graphify, gerar_skill_rascunho


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON - integrações opcionais IA")
    comandos = p.add_subparsers(dest="acao", required=True)
    comandos.add_parser("catalogo")
    comandos.add_parser("diagnostico")
    grafo = comandos.add_parser("grafo-local")
    grafo.add_argument("raiz", type=Path)
    importacao = comandos.add_parser("graphify-exportacao")
    importacao.add_argument("arquivo", type=Path)
    reduzir = comandos.add_parser("limitar-contexto")
    reduzir.add_argument("arquivo", type=Path)
    reduzir.add_argument("--limite", type=int, default=8000)
    skill = comandos.add_parser("skill-rascunho")
    skill.add_argument("nome")
    skill.add_argument("arquivo", type=Path)
    skill.add_argument("--referencia", required=True)
    skill.add_argument("--destino", required=True, type=Path)
    a = p.parse_args(argv)
    if a.acao == "catalogo":
        resultado = catalogo()
    elif a.acao == "diagnostico":
        resultado = diagnostico()
    elif a.acao == "grafo-local":
        resultado = dependencias_python(a.raiz)
    elif a.acao == "graphify-exportacao":
        resultado = importar_graphify(a.arquivo)
    elif a.acao == "limitar-contexto":
        resultado = limitar_contexto(a.arquivo.read_text(encoding="utf-8"), limite=a.limite)
    else:
        resultado = {"rascunho": str(gerar_skill_rascunho(a.nome, a.arquivo.read_text(encoding="utf-8"),
                                          a.referencia, a.destino)), "habilitada": False}
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
