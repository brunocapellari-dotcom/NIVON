"""Inspeção sem download dos tamanhos dos Parquets ANTAQ de fonte TERCEIRA."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from .antaq_secundaria_gcp_2025 import HF_REPO,HF_COMMIT,ARQUIVOS

MAX_DOWNLOAD_PER_FILE=65_000_000

def inspecionar_siblings(siblings):
    por_nome={s.rfilename:s for s in siblings}
    out=[]
    for tipo,path in ARQUIVOS.items():
        item=por_nome.get(path)
        if item is None:
            raise ValueError(f"HF_ARQUIVO_AUSENTE:{tipo}")
        size=getattr(item,"size",None)
        if type(size) is not int or size<=0:
            raise ValueError(f"HF_TAMANHO_NAO_COMPROVADO:{tipo}")
        out.append({"tipo":tipo,"arquivo":path,"bytes_informados":size,
                    "limite_atual_bytes":MAX_DOWNLOAD_PER_FILE,
                    "tamanho_aprovado":size<=MAX_DOWNLOAD_PER_FILE})
    return {
        "estado":"METADADOS_TERCEIRO_HF_VERIFICADOS_SEM_DOWNLOAD",
        "revisao":HF_COMMIT, "fonte":HF_REPO,
        "arquivos":out,
        "gravacao_cloud":False,
        "microdados_oficiais_antaq":False,
        "apto_para_tentativa_local":all(x["tamanho_aprovado"] for x in out),
    }

def consultar():
    from huggingface_hub import HfApi
    info=HfApi().dataset_info(repo_id=HF_REPO,revision=HF_COMMIT,files_metadata=True)
    if info.sha != HF_COMMIT:
        raise ValueError("HF_REVISAO_NAO_CORRESPONDE")
    return inspecionar_siblings(info.siblings)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="Inspecionar tamanhos ANTAQ HF revisao fixada sem copiar arquivos")
    parser.add_argument("--saida",required=True)
    args=parser.parse_args(argv)
    try:
        doc=consultar()
        dest=Path(args.saida)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        print(json.dumps(doc,ensure_ascii=False))
        return 0
    except (ValueError,OSError) as exc:
        print(json.dumps({"estado":"METADADOS_HF_INCONCLUSIVOS","motivo":str(exc)},
                         ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
