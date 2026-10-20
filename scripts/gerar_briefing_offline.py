"""CLI segura de homologação OFFLINE do briefing diário NIVON.

Exemplo: PYTHONPATH=src python scripts/gerar_briefing_offline.py
    --manifesto entradas/edicao.json
    --banco dados/radar.sqlite
    --saida saida/briefing.txt
    --auditoria saida/briefing.auditoria.json

Nenhuma operação de rede, consulta de contas, agendamento ou envio WhatsApp.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from nivon.pipeline_briefing import gerar_edicao_offline
from nivon.rss_radar import MAX_BYTES


def _arquivo_regular(path: Path, *, maximo: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=maximo:
        raise ValueError("arquivo inexistente, symlink, vazio ou muito extenso: "+path.name)
    return path.read_bytes()


def _sob_raiz(raiz: Path, relativo: str) -> Path:
    if not isinstance(relativo,str) or not relativo or len(relativo)>240:
        raise ValueError("referência inválida de arquivo XML")
    ref=Path(relativo)
    if ref.is_absolute() or any(p==".." for p in ref.parts):
        raise ValueError("snapshot fora da pasta do manifesto")
    destino=raiz.joinpath(ref)
    if not destino.resolve(strict=False).is_relative_to(raiz):
        raise ValueError("snapshot aponta para caminho externo")
    if destino.is_symlink():
        raise ValueError("snapshot por symlink bloqueado")
    return destino


def _escrita_atomica(path: Path, data: bytes) -> None:
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError("destino inválido ou pasta não criada")
    fd,nome=tempfile.mkstemp(prefix=".nivon-",dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(nome,path)
    finally:
        if os.path.exists(nome):
            os.unlink(nome)


def executar(*, manifesto: Path, banco: Path, saida: Path, auditoria: Path) -> dict:
    data=json.loads(_arquivo_regular(manifesto,maximo=1_000_000).decode("utf-8"))
    if not isinstance(data,dict) or not isinstance(data.get("feeds"),list):
        raise ValueError("manifesto inválido: feeds obrigatório")
    raiz=manifesto.parent.resolve()
    snapshots={}
    feeds=[]
    for f in data["feeds"]:
        if not isinstance(f,dict):
            raise ValueError("item de feed não é objeto")
        fid=f.get("fonte_id")
        if not isinstance(fid,str) or fid in snapshots:
            raise ValueError("fonte duplicada/ausente no manifesto")
        xml=_sob_raiz(raiz,f.get("arquivo_xml"))
        snapshots[fid]=_arquivo_regular(xml,maximo=MAX_BYTES)
        feeds.append({k:v for k,v in f.items() if k!="arquivo_xml"})
    if banco.is_symlink() or not banco.parent.is_dir() or banco.suffix!=".sqlite":
        raise ValueError("banco SQLite inválido")
    if saida==auditoria or saida==banco or auditoria==banco:
        raise ValueError("arquivos de saída e banco precisam ser distintos")
    with sqlite3.connect(str(banco)) as conn:
        result=gerar_edicao_offline(
            gerado_em=data["gerado_em"],feeds=feeds,
            snapshots_xml=snapshots,db=conn,
            indicadores=data.get("indicadores"),
            fontes_indicadores=data.get("fontes_indicadores"),
            fretes=data.get("fretes"),
            registros_portuarios=data.get("registros_portuarios"),
            licencas_portuarias=data.get("licencas_portuarias"),
        )
    texto=result["texto"]
    metadados={k:v for k,v in result.items() if k!="texto"}
    _escrita_atomica(saida,(texto+"\n").encode("utf-8"))
    _escrita_atomica(auditoria,(json.dumps(metadados,ensure_ascii=False,
                indent=2,sort_keys=True)+"\n").encode("utf-8"))
    return {"estado":result["estado"],"sha256":result["sha256"],
            "arquivo":str(saida),"auditoria":str(auditoria),
            "noticias_curadas":result["noticias_recebidas_curadas"],
            "enviado":False}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="NIVON: preparar briefing 100% offline sem envio")
    parser.add_argument("--manifesto",type=Path,required=True)
    parser.add_argument("--banco",type=Path,required=True)
    parser.add_argument("--saida",type=Path,required=True)
    parser.add_argument("--auditoria",type=Path,required=True)
    args=parser.parse_args(argv)
    status=executar(manifesto=args.manifesto,banco=args.banco,
                   saida=args.saida,auditoria=args.auditoria)
    print(json.dumps(status,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
