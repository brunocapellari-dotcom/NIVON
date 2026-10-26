"""Geracao atomica do snapshot privado NIVON a partir do painel BigQuery real."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile

from nivon.portal_interno import (ErroPortal, MAX_INPUT, _json_unico,
                                 montar_snapshot, validar_snapshot)


def gerar(*, entrada: Path, saida: Path, gerado_em: str):
    if entrada.is_symlink() or not entrada.is_file() or not 0 < entrada.stat().st_size <= MAX_INPUT:
        raise ErroPortal("entrada real inexistente ou insegura")
    if saida.is_symlink() or (saida.exists() and not saida.is_file()):
        raise ErroPortal("destino nao e arquivo regular")
    if not saida.parent.is_dir():
        raise ErroPortal("pasta de destino ausente")
    raw = entrada.read_text(encoding="utf-8")
    try:
        dados = json.loads(raw, object_pairs_hook=_json_unico,
                           parse_constant=lambda _: (_ for _ in ()).throw(ErroPortal("NaN proibido")))
    except json.JSONDecodeError as exc:
        raise ErroPortal("entrada JSON invalida") from exc
    result = validar_snapshot(montar_snapshot(dados, gerado_em=gerado_em))
    conteudo = json.dumps(result, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    fd, temp = tempfile.mkstemp(dir=saida.parent, prefix=".nivon-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(conteudo)
            fp.flush()
            os.fsync(fp.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, saida)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"estado": result["estado"], "indicadores": len(result["indicadores"]),
            "fontes_consultadas": len(result["fontes_consultadas"]),
            "publicavel": False, "caminho_privado": True}


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: readback privado -> snapshot do portal")
    p.add_argument("--entrada", required=True, type=Path)
    p.add_argument("--saida", required=True, type=Path)
    p.add_argument("--as-of", required=True)
    args = p.parse_args(argv)
    try:
        report = gerar(entrada=args.entrada, saida=args.saida, gerado_em=args.as_of)
    except (OSError, ValueError) as exc:
        p.exit(2, "NIVON: entrada bloqueada ou readback incompativel\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
