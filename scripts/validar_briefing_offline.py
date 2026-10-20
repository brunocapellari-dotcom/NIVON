"""CLI de pre-homologação NIVON: verificação offline, nunca envia WhatsApp.

Consome TXT + auditoria gerados por gerar_briefing_offline.py e um pacote
separado de provas externas aprovado pelo operador. Retorno 0 = apto à REVISÃO,
2 = bloqueado, sem significar autorização de publicação.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nivon.editorial_preflight import avaliar_previa_editorial


def _ler(path: Path, *, limite: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limite:
        raise ValueError("arquivo inválido/symlink/tamanho excedido: " + path.name)
    return path.read_text(encoding="utf-8")


def executar(*, texto: Path, auditoria: Path, provas: Path) -> dict:
    raw = _ler(texto, limite=200_000)
    # O gerador existente acrescenta exatamente um terminador de linha ao TXT.
    conteudo = raw[:-1] if raw.endswith("\n") else raw
    edicao = json.loads(_ler(auditoria, limite=1_000_000))
    evidencia = json.loads(_ler(provas, limite=1_000_000))
    if not isinstance(edicao, dict) or not isinstance(evidencia, dict):
        raise ValueError("pacotes JSON devem ser objetos")
    if "texto" in edicao:
        raise ValueError("auditoria não pode substituir o texto assinado")
    edicao["texto"] = conteudo
    return avaliar_previa_editorial(
        edicao=edicao, gerado_em=edicao.get("gerado_em"),
        noticias=evidencia.get("noticias"),
        cotacoes=evidencia.get("cotacoes"),
        fretes=evidencia.get("fretes"),
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="NIVON: auditar briefing, SEM ENVIO")
    p.add_argument("--texto", type=Path, required=True)
    p.add_argument("--auditoria", type=Path, required=True)
    p.add_argument("--provas", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        relatorio = executar(texto=args.texto, auditoria=args.auditoria,
                            provas=args.provas)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        relatorio = {"apto_revisao": False, "bloqueios": ["LEITURA:" + str(exc)],
                     "modo": "OFFLINE_SEM_ENVIO"}
    print(json.dumps(relatorio, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if relatorio["apto_revisao"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
