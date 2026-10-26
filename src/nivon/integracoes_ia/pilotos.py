"""Pilotos P0-P2 do NIVON, explicitamente acionados e com evidência sanitizada.

Este módulo não realiza coleta recorrente, publicação, deploy ou concessão IAM.
O resultado nunca atesta frescor de dados nem homologa um fornecedor.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from .core import ErroIntegracao, PoliticaIntegracao, catalogo, diagnostico
from .engenharia import dependencias_python
from . import provedores


CAPACIDADES_PILOTO = ("diagnostico", "grafo", "firecrawl", "pageindex", "hindsight", "paperclip")
EXTERNAS = frozenset({"firecrawl", "pageindex", "hindsight", "paperclip"})


def politica_ambiente() -> PoliticaIntegracao:
    """Duas aprovações separadas; hosts exatos e explícitos; nenhuma origem é inferida."""
    hosts = tuple(x.strip().lower() for x in os.getenv("NIVON_AI_APPROVED_HOSTS", "").split(",") if x.strip())
    return PoliticaIntegracao(
        habilitar_rede=os.getenv("NIVON_AI_NETWORK_APPROVED") == "true",
        autorizar_servico_externo=os.getenv("NIVON_AI_EXTERNAL_APPROVED") == "true",
        dominios_aprovados=hosts,
    )


def _resumo(capacidade: str, bruto: dict) -> dict:
    """Não enviar texto de fonte, perguntas, respostas LLM, títulos ou IDs privados à CI."""
    if capacidade == "firecrawl":
        texto = bruto["texto"]
        ev = bruto["evidencia"]
        if ev["publicavel"] is not False or ev["validado"] is not False:
            raise ErroIntegracao("FIRECRAWL_PROVENIENCIA_INSEGURA")
        return {"bytes_texto": len(texto.encode("utf-8")), "sha256_texto": ev["sha256"],
                "natureza": ev["natureza"]}
    if capacidade == "pageindex":
        if bruto["publicavel"] is not False:
            raise ErroIntegracao("PAGEINDEX_PUBLICACAO_INESPERADA")
        texto = str(bruto["resposta"])
        return {"sha256_documento": bruto["documento_sha256"],
                "sha256_resposta": hashlib.sha256(texto.encode()).hexdigest(),
                "natureza": bruto["natureza"], "resposta_presente": bool(texto.strip())}
    if capacidade == "hindsight":
        if bruto["publicavel"] is not False:
            raise ErroIntegracao("HINDSIGHT_PUBLICACAO_INESPERADA")
        return {"memorias_encontradas": len(bruto["memorias"]), "natureza": bruto["natureza"]}
    if capacidade == "paperclip":
        if bruto["canonica"] is not False:
            raise ErroIntegracao("PAPERCLIP_CANONIZACAO_INESPERADA")
        return {"tarefas_lidas": len(bruto["tarefas_externas"]), "canonica": False}
    if capacidade == "grafo":
        if bruto.get("erros_parse"):
            raise ErroIntegracao("GRAFO_COM_ERRO_DE_PARSER")
        return {"arquivos_inspecionados": bruto["arquivos_inspecionados"],
                "arestas": len(bruto["arestas"]), "tipo": bruto["tipo"]}
    if capacidade == "diagnostico":
        return {"capacidades_catalogadas": len(catalogo()),
                "capacidades_diagnosticadas": len(bruto)}
    raise ErroIntegracao("CAPACIDADE_INVALIDA")


def executar(capacidade: str, *, origem: str = "", pergunta: str = "",
             arquivo: str = "", raiz: str = "src/nivon",
             politica: PoliticaIntegracao | None = None) -> dict:
    """Somente uma capacidade por execução para limitar custo e raio de falha."""
    if capacidade not in CAPACIDADES_PILOTO:
        raise ErroIntegracao("CAPACIDADE_NAO_SUPORTADA")
    ativa = politica or politica_ambiente()
    if capacidade in EXTERNAS:
        ativa.permitir_externo()
    if capacidade == "diagnostico":
        bruto = diagnostico()
    elif capacidade == "grafo":
        bruto = dependencias_python(Path(raiz))
    elif capacidade == "firecrawl":
        if not origem:
            raise ErroIntegracao("FONTE_OBRIGATORIA")
        bruto = provedores.consultar_firecrawl(origem, ativa)
    elif capacidade == "pageindex":
        if not pergunta or not arquivo:
            raise ErroIntegracao("DOCUMENTO_E_PERGUNTA_OBRIGATORIOS")
        # Evita ler PDF arbitrário de secrets, /proc, ou de diretórios de trabalho externos.
        base = Path("docs").resolve(strict=True)
        path = Path(arquivo)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
            raise ErroIntegracao("DOCUMENTO_FORA_DO_DIRETORIO_APROVADO")
        bruto = provedores.consultar_pageindex(path, pergunta, ativa)
    elif capacidade == "hindsight":
        if not pergunta:
            raise ErroIntegracao("CONSULTA_OBRIGATORIA")
        bruto = provedores.consultar_hindsight(pergunta, ativa)
    else:
        bruto = provedores.listar_paperclip(ativa)
    resumo = _resumo(capacidade, bruto)
    return {
        "schema": "nivon.integracao.piloto.v1",
        "capacidade": capacidade,
        "execucao": "PILOTO_EXTERNO_REAL" if capacidade in EXTERNAS else "EXECUCAO_LOCAL_REAL",
        "estado": "EXECUTADO_SEM_HOMOLOGACAO",
        "gerado_utc": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GITHUB_SHA") or None,
        "run_id": os.getenv("GITHUB_RUN_ID") or None,
        "resultado_sanitizado": resumo,
        "validado_em_producao": False,
        "frescor_dados_validado": False,
        "publicavel": False,
        "deploy_realizado": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="NIVON: diagnóstico ou piloto externo opt-in")
    parser.add_argument("--capacidade", required=True, choices=CAPACIDADES_PILOTO)
    parser.add_argument("--origem", default="")
    parser.add_argument("--pergunta", default="")
    parser.add_argument("--arquivo", default="")
    parser.add_argument("--raiz", default="src/nivon")
    parser.add_argument("--saida", required=True, type=Path)
    args = parser.parse_args(argv)
    saida = args.saida
    if saida.exists() or saida.is_symlink() or not saida.parent.is_dir():
        print("DESTINO_INSEGURO", file=sys.stderr)
        return 2
    try:
        relatorio = executar(args.capacidade, origem=args.origem, pergunta=args.pergunta,
                            arquivo=args.arquivo, raiz=args.raiz)
        dados = json.dumps(relatorio, ensure_ascii=False, sort_keys=True, indent=2)
        with saida.open("x", encoding="utf-8") as f:
            f.write(dados + "\n")
        print("NIVON_PILOTO=" + args.capacidade + " RESULTADO=EXECUTADO_SEM_HOMOLOGACAO")
        return 0
    except (ErroIntegracao, KeyError, TypeError, ValueError) as exc:
        # Não expor respostas dos fornecedores nem credenciais nos logs.
        codigo = str(exc) if isinstance(exc, ErroIntegracao) else "RESULTADO_EXTERNO_INVALIDO"
        print("NIVON_PILOTO_BLOQUEADO=" + codigo, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
