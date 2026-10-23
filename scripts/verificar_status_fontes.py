"""Validação pós-persistência de lote: dados parciais não parecem sucesso."""
from __future__ import annotations
import json
import sys
from pathlib import Path


def verificar_lote(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>300000:
        raise ValueError("relatorio de coleta ausente ou invalido")
    try:
        doc=json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError) as exc:
        raise ValueError("relatorio nao JSON") from exc
    fontes=doc.get("fontes")
    if not isinstance(fontes,list) or not fontes or len(fontes)>100:
        raise ValueError("lista de fontes invalida")
    sucesso=sum(isinstance(f,dict) and f.get("estado")=="COLETADO" for f in fontes)
    falhas=sum(isinstance(f,dict) and f.get("estado")=="FALHOU" for f in fontes)
    if sucesso+falhas!=len(fontes) or doc.get("sucesso")!=sucesso or doc.get("falhas")!=falhas:
        raise ValueError("contagem e estado de fontes inconsistentes")
    if falhas:
        return {"estado":"PARCIAL","sucesso":sucesso,"falhas":falhas,"aprovado":False}
    return {"estado":"TODAS_COLETADAS","sucesso":sucesso,"falhas":0,"aprovado":True}


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description="Resultado de coleta apos arquivar e carregar")
    p.add_argument("arquivo")
    args=p.parse_args(argv)
    try:
        ret=verificar_lote(args.arquivo)
    except (ValueError,OSError) as exc:
        print(json.dumps({"aprovado":False,"erro":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps(ret,ensure_ascii=False))
    return 0 if ret["aprovado"] else 2


if __name__=="__main__":
    raise SystemExit(main())
