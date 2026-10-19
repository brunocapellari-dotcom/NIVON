"""Cobertura de indicadores: requisito, implementação e direitos NÃO se confundem."""
from __future__ import annotations
import json
from pathlib import Path
from .catalogo_fontes import DEFAULT as DEFAULT_FONTES, ErroCatalogo, carregar_catalogo

DEFAULT_MATRIZ = DEFAULT_FONTES.parent / "matriz_produtos_indicadores.v1.json"


def validar_matriz(matriz: dict, catalogo: dict) -> dict:
    if not isinstance(matriz,dict) or matriz.get("project")!="NIVON" or matriz.get("schema_version")!="1.0":
        raise ErroCatalogo("matriz de indicadores inválida")
    setores=matriz.get("systems")
    if not isinstance(setores,list) or len(setores)<10:
        raise ErroCatalogo("setores críticos ausentes")
    fontes={d["id"]:d for d in catalogo["datasets"]}
    ids=set()
    total=0
    for s in setores:
        sid=s.get("id")
        if not isinstance(sid,str) or not sid or sid in ids:
            raise ErroCatalogo("setor duplicado ou sem id")
        ids.add(sid)
        names=s.get("indicators")
        links=s.get("data")
        if not isinstance(names,list) or not names or len(names)!=len(set(names)):
            raise ErroCatalogo(f"{sid}: métricas vazias/duplicadas")
        if not isinstance(links,list) or not links or len(links)!=len(set(links)):
            raise ErroCatalogo(f"{sid}: datasets vazios/duplicados")
        if not isinstance(s.get("risks"),list) or not s["risks"]:
            raise ErroCatalogo(f"{sid}: limitações obrigatórias")
        for did in links:
            if did not in fontes:
                raise ErroCatalogo(f"{sid}: dataset sem catálogo: {did}")
        total+=len(names)
    required={"SOJA","MILHO","ALGODAO","BOI","BEZERRO","ACUCAR",
              "TRIGO","SORGO","FERTILIZANTES","DIESEL","ETANOL_DDG",
              "LOGISTICA_INTERMODAL","MARITIMO","CLIMA_HIDRO",
              "MERCADO_MACRO","BRIEFING_DIARIO","CANA","GERGELIM","FRANGO","SUINO",
              "METEOROLOGIA","HIDROLOGIA","ARMAZENAGEM","COMERCIO_EXTERIOR",
              "PETROLEO_ENERGIA","FRETE_RODOVIARIO","RISCO_GEOPOLITICO","INDUSTRIA_PROCESSAMENTO"}
    if ids!=required:
        raise ErroCatalogo("frentes do NIVON faltando ou desconhecidas")
    return {"frentes":len(setores),"indicadores":total,
            "ligacoes_de_dados":sum(len(s["data"]) for s in setores)}


def carregar_matriz(caminho=DEFAULT_MATRIZ, *, catalogo=None):
    arq=Path(caminho)
    if not arq.is_file() or arq.is_symlink() or arq.stat().st_size>160_000:
        raise ErroCatalogo("arquivo de matriz ausente/inseguro")
    try: d=json.loads(arq.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError) as e: raise ErroCatalogo("JSON de indicadores inválido") from e
    validar_matriz(d, catalogo or carregar_catalogo())
    return d


def diagnostico_matriz(matriz:dict,catalogo:dict)->list[dict]:
    por_id={d["id"]:d for d in catalogo["datasets"]}
    out=[]
    for s in matriz["systems"]:
        candidatos=[por_id[x] for x in s["data"]]
        testados=sum(d["stage"]=="REAL_SNAPSHOT_TESTED" for d in candidatos)
        out.append({
            "frente":s["id"],
            "indicadores_previstos":len(s["indicators"]),
            "datasets_requeridos":len(candidatos),
            "snapshots_reais_testados":testados,
            "datasets_sem_homologacao":len(candidatos)-testados,
            "apto_producao":False,
            "observacao":"Teste de snapshot não equivale a atualização operacional ou liberação de direitos.",
        })
    return out


if __name__ == "__main__":
    from .catalogo_fontes import carregar_catalogo
    c=carregar_catalogo()
    m=carregar_matriz(catalogo=c)
    print(json.dumps({"resumo":validar_matriz(m,c),"frentes":diagnostico_matriz(m,c)},
                     ensure_ascii=False,indent=2))
