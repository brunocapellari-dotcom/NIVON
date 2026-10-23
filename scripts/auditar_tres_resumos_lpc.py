#!/usr/bin/env python3
"""Audita três planilhas semanais ANP locais. Sem rede, DB ou publicação.

Uso: python scripts/auditar_tres_resumos_lpc.py --manifesto caminho/manifesto.json
Opcional --saida caminho/relatorio.json (somente metadados, sem preços).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from nivon.anp_lpc_homologacao import auditar_tres_edicoes_lpc

_MAX_MANIFEST = 32_768


def _arquivo_local(base: Path, valor: str, *, max_bytes: int) -> bytes:
    if not isinstance(valor, str) or not valor or Path(valor).is_absolute():
        raise ValueError("somente arquivo relativo ao diretório do manifesto")
    caminho = base / valor
    if caminho.is_symlink() or not caminho.resolve().is_relative_to(base.resolve()):
        raise ValueError("arquivo fora da raiz ou link simbólico não autorizado")
    if not caminho.is_file() or not 1 <= caminho.stat().st_size <= max_bytes:
        raise ValueError("arquivo ausente, vazio ou maior que o limite")
    return caminho.read_bytes()


def carregar_manifesto_local(caminho: Path) -> dict:
    if caminho.is_symlink() or not caminho.is_file() or caminho.stat().st_size > _MAX_MANIFEST:
        raise ValueError("manifesto local não encontrado ou inválido")
    base = caminho.resolve().parent
    obj = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or set(obj) != {
        "indice_arquivo", "indice_sha256_esperado", "capturado_indice_em",
        "as_of", "ano", "edicoes"
    }:
        raise ValueError("campos obrigatórios de manifesto divergentes")
    if not isinstance(obj["edicoes"], list) or len(obj["edicoes"]) != 3:
        raise ValueError("manifesto exige três edições")
    edicoes = []
    for ed in obj["edicoes"]:
        if not isinstance(ed, dict) or set(ed) != {
            "arquivo", "url", "sha256", "publicado_em", "coletado_em",
            "prova_publicacao_sha256",
        }:
            raise ValueError("campos de edição divergentes")
        dados = {k: v for k, v in ed.items() if k != "arquivo"}
        dados["xlsx"] = _arquivo_local(base, ed["arquivo"], max_bytes=14_000_000)
        edicoes.append(dados)
    return {
        "indice_html": _arquivo_local(base, obj["indice_arquivo"], max_bytes=4_000_000),
        "indice_sha256_esperado": obj["indice_sha256_esperado"],
        "capturado_indice_em": obj["capturado_indice_em"],
        "as_of": obj["as_of"],
        "ano": obj["ano"],
        "edicoes": edicoes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Auditoria OFFLINE, nunca homologação automática")
    ap.add_argument("--manifesto", type=Path, required=True)
    ap.add_argument("--saida", type=Path)
    args = ap.parse_args(argv)
    try:
        params = carregar_manifesto_local(args.manifesto)
        resposta = auditar_tres_edicoes_lpc(**params)
        payload = json.dumps(resposta, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        if args.saida is None:
            sys.stdout.write(payload)
        else:
            pasta = args.saida.resolve().parent
            if not pasta.is_dir() or args.saida.is_symlink():
                raise ValueError("destino de saída inválido")
            destino = args.saida.resolve()
            with tempfile.NamedTemporaryFile(mode="w", dir=pasta, encoding="utf-8",
                                             prefix=".anp_lpc_", suffix=".tmp",
                                             delete=False) as fh:
                temp = Path(fh.name)
                fh.write(payload)
            try:
                os.replace(temp, destino)
            finally:
                temp.unlink(missing_ok=True)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print("AUDITORIA_ANP_NAO_CONCLUIDA: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
