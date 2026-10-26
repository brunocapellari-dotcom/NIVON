"""Executa um lote AIS original de arquivo local, sem rede e sem GCP."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from nivon.maritime.ais_ledger import ErroAIS, registrar_lote

def _unique_pairs(items):
    result={}
    for k,v in items:
        if k in result:
            raise ErroAIS("chave JSON duplicada")
        result[k]=v
    return result

def executar(*,arquivo,banco,porto_id,as_of):
    path=Path(arquivo)
    if path.is_symlink() or not path.is_file() or not 1<=path.stat().st_size<=5_000_000:
        raise ErroAIS("entrada AIS inexistente ou excessiva")
    rows=[]
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():continue
            rows.append(json.loads(line,object_pairs_hook=_unique_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ErroAIS("JSON nao-finito"))))
            if len(rows)>2000:raise ErroAIS("lote AIS >2000")
    return registrar_lote(banco=banco,porto_id=porto_id,mensagens=rows,as_of=as_of)

def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON AIS RAW → SQLite historico auditavel")
    p.add_argument("--entrada",required=True)
    p.add_argument("--banco",required=True)
    p.add_argument("--porto-id",required=True)
    p.add_argument("--as-of",required=True)
    a=p.parse_args(argv)
    try:
        out=executar(arquivo=a.entrada,banco=a.banco,
                     porto_id=a.porto_id,as_of=a.as_of)
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({"estado":"FALHA_FECHADA","classe":type(exc).__name__}))
        return 2
    print(json.dumps(out,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
