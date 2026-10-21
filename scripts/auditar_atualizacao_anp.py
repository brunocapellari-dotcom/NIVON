"""Auditoria offline do índice de semanas ANP (não é coletor).

Uso:
  PYTHONPATH=src python scripts/auditar_atualizacao_anp.py \
    --indice-html /dados/indice_anp.html \
    --indice-coletado-em 2026-10-20T15:00:00-03:00 \
    --gerado-em 2026-10-20T16:00:00-03:00 \
    --saida /dados/auditoria_anp.json

A página deve ter sido obtida legalmente por um processo separado. Nenhum acesso
à internet, scrape, tentativa de senha ou publicação ocorre neste comando.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nivon.anp_monitor_atualizacao import auditar_publicacoes_anp


def _ler(path: Path, limite: int) -> bytes:
    if (path.is_symlink() or not path.is_file() or
        not 0 < path.stat().st_size <= limite):
        raise ValueError("arquivo local inexistente, vazio, symlink ou acima do limite")
    return path.read_bytes()


def _gravar(path: Path, valor: dict) -> None:
    if path.is_symlink() or not path.parent.is_dir() or path.suffix != ".json":
        raise ValueError("saída deve ser JSON em diretório existente")
    data=(json.dumps(valor,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
    handle,nome=tempfile.mkstemp(prefix=".nivon-anp-",dir=path.parent)
    try:
        os.fchmod(handle,0o600)
        with os.fdopen(handle,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(nome,path)
    finally:
        if os.path.exists(nome):
            os.unlink(nome)


def auditar(*, indice_html: Path, indice_coletado_em: str,
            gerado_em: str, saida: Path,
            anterior: Path | None = None,
            anual_meta: Path | None = None) -> dict:
    if indice_html.resolve() == saida.resolve() or (
        anterior is not None and anterior.resolve()==saida.resolve()
    ) or (anual_meta is not None and anual_meta.resolve()==saida.resolve()):
        raise ValueError("arquivo de entrada não pode ser sobrescrito")
    anterior_doc=json.loads(_ler(anterior,200_000)) if anterior is not None else None
    meta=json.loads(_ler(anual_meta,30_000)) if anual_meta is not None else None
    if anterior_doc is not None and (
        not isinstance(anterior_doc,dict) or
        "indice_sha256" not in anterior_doc or
        "competencias_atualmente_no_indice" not in anterior_doc
    ):
        raise ValueError("auditoria anterior incompleta")
    auditoria=auditar_publicacoes_anp(
        _ler(indice_html,4_000_000),
        indice_coletado_em=indice_coletado_em,
        gerado_em=gerado_em,
        anual=meta,
        indice_anterior_sha256=anterior_doc.get("indice_sha256") if anterior_doc else None,
        semanas_anteriormente_observadas=frozenset(
            anterior_doc["competencias_atualmente_no_indice"]
        ) if anterior_doc else None,
    )
    # Guardar a lista efetivamente observada: revisão não pode apagar o histórico anterior.
    # A lista atual é serializada apenas como prova do índice, não como séries numéricas.
    from nivon.anp_indice_lpc import descobrir_semanas_lpc
    semanas=descobrir_semanas_lpc(_ler(indice_html,4_000_000),ano=int(gerado_em[:4]))
    auditoria["competencias_atualmente_no_indice"]=[
        item["semana_fim"] for item in semanas["semanas"]
    ]
    _gravar(saida,auditoria)
    return {"status":"AUDITADO_OFFLINE_SEM_COLETA_PRECO",
            "semanas":auditoria["semanas_indexadas"],
            "alertas":auditoria["alertas"],
            "saida":str(saida),"publicacao_autorizada":False}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="NIVON: auditar atualidade ANP sem rede")
    p.add_argument("--indice-html",type=Path,required=True)
    p.add_argument("--indice-coletado-em",required=True)
    p.add_argument("--gerado-em",required=True)
    p.add_argument("--saida",type=Path,required=True)
    p.add_argument("--anterior",type=Path)
    p.add_argument("--anual-meta",type=Path)
    args=p.parse_args(argv)
    result=auditar(indice_html=args.indice_html,indice_coletado_em=args.indice_coletado_em,
                   gerado_em=args.gerado_em,saida=args.saida,
                   anterior=args.anterior,anual_meta=args.anual_meta)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
