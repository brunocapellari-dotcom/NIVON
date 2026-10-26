"""P0/P1/P2 locais: aceite, grafo de dependências e skills versionáveis."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .core import ErroIntegracao, hash_texto


_RESULTADOS = {"SUCESSO", "FALHA", "PULADO", "DESCONHECIDO"}


def aceite_trabalho(*, tarefa: str, pr: int, commit: str, testes: str,
                    evidencia_url: str | None = None, deploy: bool = False) -> dict:
    """P0: um PR aberto ou um teste verde não equivale a entrega homologada."""
    if not re.fullmatch(r"NIVON-[A-Z0-9_-]{2,60}", tarefa):
        raise ErroIntegracao("TAREFA_INVALIDA")
    if type(pr) is not int or pr <= 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ErroIntegracao("PR_OU_SHA_INVALIDO")
    if testes not in _RESULTADOS:
        raise ErroIntegracao("RESULTADO_TESTE_INVALIDO")
    # Verifica-se somente coerência do registro. URLs/eventos devem ter prova independente.
    evid = bool(evidencia_url and evidencia_url.startswith("https://") and len(evidencia_url) <= 500)
    aprovado = testes == "SUCESSO" and evid and (not deploy or "run.app" in evidencia_url)
    return {"schema": "nivon.integracao.aceite.v1", "tarefa": tarefa,
            "pr": pr, "commit": commit, "testes": testes,
            "evidencia_informada": evid, "deploy_solicitado": deploy,
            "estado": "EVIDENCIA_PENDENTE_DE_VALIDACAO" if aprovado else "NAO_APROVADO",
            "homologado": False, "publicavel": False}


def dependencias_python(raiz: Path) -> dict:
    """Grafo estático local sem rede/LLM. Graphify pode enriquecê-lo fora de produção.

    Usa AST (não executa módulos). Apenas arquivos Python sob raiz fornecida.
    """
    raiz = Path(raiz)
    if raiz.is_symlink() or not raiz.is_dir():
        raise ErroIntegracao("DIRETORIO_NAO_VALIDO")
    arquivos = sorted(raiz.rglob("*.py"))
    if len(arquivos) > 2000 or any(p.is_symlink() or p.stat().st_size > 500_000 for p in arquivos):
        raise ErroIntegracao("GRAFO_ACIMA_DOS_LIMITES")
    arcos = set()
    erros = []
    for arquivo in arquivos:
        rel = arquivo.relative_to(raiz).as_posix()
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeError) as exc:
            erros.append(rel)
            continue
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for n in no.names:
                    if n.name.startswith("nivon"):
                        arcos.add((rel, n.name))
            elif isinstance(no, ast.ImportFrom):
                modulo = no.module or ""
                if no.level or modulo.startswith("nivon"):
                    arcos.add((rel, "." * no.level + modulo))
    return {"schema": "nivon.integracao.grafo.v1", "tipo": "ESTATICO_OBSERVADO_CODIGO",
            "arquivos_inspecionados": len(arquivos),
            "arestas": [{"arquivo": a, "importa": b} for a, b in sorted(arcos)],
            "erros_parse": erros, "nao_inferir_dependencias_dinamicas": True}


def importar_graphify(path: Path) -> dict:
    """Adapta uma exportação JSON do Graphify como arquivo NÃO CONFIÁVEL.

    Não a interpreta como dependência comprovada: schema do fornecedor pode variar.
    """
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.suffix.lower() != ".json" or p.stat().st_size > 2_000_000:
        raise ErroIntegracao("EXPORTACAO_INVALIDA")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        raise ErroIntegracao("EXPORTACAO_JSON_INVALIDA") from None
    if not isinstance(obj, (dict, list)):
        raise ErroIntegracao("EXPORTACAO_SCHEMA_INVALIDO")
    return {"schema": "nivon.integracao.graphify.v1", "fonte": "GRAPHIFY_EXPORTACAO_EXTERNA",
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size, "verificado": False,
            "apto_como_fonte_canonica": False}


def gerar_skill_rascunho(nome: str, texto_fonte: str, referencia: str, diretorio: Path) -> Path:
    """Book-to-Skill conservador: não infere conteúdo; só materializa fonte aprovada.

    A skill fica com status RASCUNHO e jamais aparece nas skills ativas.
    """
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", nome) or not 20 <= len(texto_fonte) <= 30_000:
        raise ErroIntegracao("SKILL_NOME_OU_TEXTO_INVALIDOS")
    if not referencia.startswith("https://") or len(referencia) > 400:
        raise ErroIntegracao("REFERENCIA_INVALIDA")
    destino = Path(diretorio)
    if destino.is_symlink() or not destino.is_dir():
        raise ErroIntegracao("DIRETORIO_SKILL_INVALIDO")
    path = destino / f"{nome}.rascunho.md"
    # Texto fonte é dado não confiável e vai para bloco marcado, não instruções do agente.
    texto = (f"# Skill em revisão: {nome}\n\n"
             f"Status: RASCUNHO — NÃO EXECUTAR AUTOMATICAMENTE\n\n"
             f"Fonte: {referencia}\n\n"
             f"SHA256 da fonte: {hash_texto(texto_fonte)}\n\n"
             "## Conteúdo da fonte (não são instruções de execução)\n\n"
             "```text\n" + texto_fonte.replace("```", "` ` `") + "\n```\n\n"
             "## Próximo passo\nValidar a autoria, licença, fidelidade, permissões e testes antes de promover a SKILL.md.\n")
    with path.open("x", encoding="utf-8") as f:
        f.write(texto)
    return path
