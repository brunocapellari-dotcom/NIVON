"""Validador estático do registro de motores, independente de coleta.

O manifesto versionado não autoriza operação em produção. Resolução de
função limitada a módulos do pacote nivon conhecidos e apenas de código local.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from .catalogo_fontes import ErroCatalogo
from .cobertura import carregar_matriz

ROOT=Path(__file__).resolve().parents[2]
DEFAULT=ROOT/"config"/"motores_inteligencia.v1.json"
MODULOS=frozenset({
    "motores_agro_estrategicos","motores_meteo_hidro",
    "motores_integracao_estrategica","motores_cadeias","cadeias_adicionais",
    "inteligencia_temporal",
    "balancos","motores","anp_diesel","destinos","portos",
    "bcb_ptax","briefing_diario","mdic_exportacao","mdic_importacao",
    "conab_agrobr","previsoes_bibliotecas","lineup_nacional","portos_automaticos",
    "fertilizantes","anp_ppi","eventos_editoriais","briefing_composto",
    "agentes_nivon","entrega_whatsapp","cotacoes_externas",
    "ana_contrato","series_ambientais","inmet_historico",
    "ana_hidrowebservice","inmet_bdmep",
    "modelos_fisicos","verificacao_probabilistica","analogos_historicos","unidades_mercado","nasa_power_nivon",
})


def carregar_registro(path=DEFAULT):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.suffix!=".json" or p.stat().st_size>150_000:
        raise ErroCatalogo("registro de motores ausente ou inseguro")
    try:obj=json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError) as exc:raise ErroCatalogo("JSON de motores inválido") from exc
    return obj


def validar_registro(doc,matriz):
    if not isinstance(doc,dict) or doc.get("project")!="NIVON" or doc.get("schema_version")!="1.0":
        raise ErroCatalogo("registro NIVON incompatível")
    if doc.get("default_policy")!="ENGINES_OFFLINE_NO_SCHEDULE_OR_DEPLOY":
        raise ErroCatalogo("gate de produção dos motores ausente")
    entries=doc.get("engines")
    if not isinstance(entries,list):
        raise ErroCatalogo("lista de motores ausente")
    fronts={x["id"]:x for x in matriz["systems"]}
    ids=set();count=0
    for entry in entries:
        if not isinstance(entry,dict) or entry.get("front_id") not in fronts:
            raise ErroCatalogo("frente do motor não cadastrada")
        fid=entry["front_id"]
        if fid in ids:
            raise ErroCatalogo("frente duplicada no registro de motores")
        ids.add(fid)
        funcs=entry.get("entrypoints")
        if not isinstance(funcs,list) or not funcs or len(funcs)!=len(set(funcs)):
            raise ErroCatalogo("nenhuma função ou função repetida")
        if (entry.get("data_dependencies")!=fronts[fid]["data"] or
                entry.get("indicators_planned")!=len(fronts[fid]["indicators"])):
            raise ErroCatalogo("registro de motores diverge da matriz canônica")
        if any(entry.get(k) is not False for k in
            ("inputs_reais_homologados","previsao_homologada","scheduled_enabled","operational_enabled")):
            raise ErroCatalogo("não homologado: gate deve permanecer OFF")
        if entry.get("status")!="CODE_TESTED_SYNTHETIC_ONLY":
            raise ErroCatalogo("estado de maturidade incompatível")
        for path in funcs:
            if not isinstance(path,str) or ":" not in path:
                raise ErroCatalogo("entrypoint inválido")
            mod,fn=path.split(":",1)
            if not mod.startswith("nivon.") or mod.removeprefix("nivon.") not in MODULOS or not fn.isidentifier():
                raise ErroCatalogo("módulo/função fora da allowlist")
            try:
                obj=getattr(importlib.import_module(mod),fn,None)
            except (ImportError,AttributeError) as exc:
                raise ErroCatalogo("não foi possível importar módulo permitido") from exc
            if not callable(obj):
                raise ErroCatalogo("função de motor não existe: "+path)
            count+=1
    if ids!=set(fronts):
        raise ErroCatalogo("faltam motores para: "+",".join(sorted(set(fronts)-ids)))
    return {"frentes":len(ids),"funcoes_vinculadas":count,
            "modelos_operacionais":0,"modelos_preditivos_homologados":0,
            "status":"CODIGO_OFFLINE_COM_TESTES_SINTETICOS"}


if __name__=="__main__":
    from .catalogo_fontes import carregar_catalogo
    mm=carregar_matriz(catalogo=carregar_catalogo())
    print(json.dumps(validar_registro(carregar_registro(),mm),ensure_ascii=False,indent=2))
