"""Comando OFFLINE de extração ANP resumo semanal XLSX (MT, diesel).

Não acessa a internet e não autoriza publicar/preencher lacunas. Serve para
homologação de amostras legalmente obtidas e comparação com números da ANP.

PYTHONPATH=src python scripts/inspecionar_lpc_semanal.py
  --arquivo /dados/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx
  --url-fonte https://www.gov.br/anp/.../resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx
  --coletado-em 2026-10-20T10:00:00-03:00
  --saida /dados/lpc_mt.json
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nivon.anp_resumo_lpc import MAX_BYTES,ler_resumo_semanal_lpc


def executar(*,arquivo: Path,url_fonte: str,coletado_em: str,saida: Path,
             municipios: list[str] | None = None) -> dict:
    if arquivo.is_symlink() or not arquivo.is_file() or arquivo.suffix.lower()!=".xlsx":
        raise ValueError("XLSX local inválido ou symlink")
    size=arquivo.stat().st_size
    if not 100<=size<=MAX_BYTES:
        raise ValueError("tamanho de XLSX incompatível")
    if saida.is_symlink() or not saida.parent.is_dir() or saida.resolve()==arquivo.resolve():
        raise ValueError("destino JSON inseguro")
    filtro=frozenset(municipios) if municipios else None
    result=ler_resumo_semanal_lpc(
        arquivo.read_bytes(),coletado_em=coletado_em,
        origem_url=url_fonte,municipios_mt=filtro,
    )
    raw=(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
    fd,tmp=tempfile.mkstemp(dir=saida.parent,prefix=".anp-",suffix=".tmp")
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as fp:
            fp.write(raw);fp.flush();os.fsync(fp.fileno())
        os.replace(tmp,saida)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return {"estado":"XLSX_ANALISADO_OFFLINE_NAO_PUBLICAVEL",
            "arquivo_sha256":result["sha256"],
            "registros":len(result["observacoes"]),
            "municipios":result["municipios_distintos"],
            "saida":str(saida)}


def main(argv=None):
    a=argparse.ArgumentParser(description="NIVON: importar semana LPC ANP offline")
    a.add_argument("--arquivo",type=Path,required=True)
    a.add_argument("--url-fonte",required=True)
    a.add_argument("--coletado-em",required=True)
    a.add_argument("--saida",type=Path,required=True)
    a.add_argument("--municipio",action="append",default=[])
    v=a.parse_args(argv)
    print(json.dumps(executar(arquivo=v.arquivo,url_fonte=v.url_fonte,
                   coletado_em=v.coletado_em,saida=v.saida,
                   municipios=v.municipio),ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
