"""Políticas de rótulos IVO associadas ao catálogo canônico de fontes NIVON.

Não libera datasets nem modifica os direitos das fontes. Produz backlog
estruturado e fail-closed para aprovação humana posterior.
"""
from __future__ import annotations

import json
from pathlib import Path


class ErroPoliticas(ValueError):
    pass


STATUS_PENDENTES = frozenset({
    "BLOQUEADO_LABEL_REALIZADO",
    "REVISAO_METODOLOGICA_NECESSARIA",
    "VALIDACAO_ESTACAO_E_DIREITOS_PENDENTE",
    "VALIDACAO_METODOLOGIA_E_DIREITOS_PENDENTE",
})


def carregar_politicas(path: str | Path | None = None) -> dict:
    root=Path(__file__).resolve().parents[2]
    caminho=Path(path) if path is not None else root/"config"/"ivo_politicas_rotulos.v1.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def auditar_politicas_rotulos(catalogo: dict, politicas: dict) -> dict:
    if not isinstance(catalogo,dict) or not isinstance(catalogo.get("datasets"),list):
        raise ErroPoliticas("catálogo de datasets inválido")
    if not isinstance(politicas,dict) or politicas.get("schema_version")!="1.0.0":
        raise ErroPoliticas("versão de políticas desconhecida")
    if (politicas.get("automatic_approval") is not False or
        politicas.get("real_data_training_enabled") is not False or
        politicas.get("training_right_is_not_implied_by_collection") is not True):
        raise ErroPoliticas("política tentou promover dados reais sem aprovação")
    regras=politicas.get("source_policies")
    if not isinstance(regras,list) or not regras or len(regras)>200:
        raise ErroPoliticas("lista de políticas inválida")
    datasets={}
    for source in catalogo["datasets"]:
        if not isinstance(source,dict) or not isinstance(source.get("id"),str):
            raise ErroPoliticas("dataset inválido")
        if source["id"] in datasets:
            raise ErroPoliticas("dataset duplicado")
        datasets[source["id"]]=source
    ids=set()
    resumo=[]
    for item in regras:
        if not isinstance(item,dict):
            raise ErroPoliticas("regra inválida")
        id=item.get("id")
        if not isinstance(id,str) or id in ids or id not in datasets:
            raise ErroPoliticas("regra duplicada ou fonte ausente do catálogo")
        ids.add(id)
        dataset=datasets[id]
        if (dataset.get("source_id") != item.get("source_id") or
            item.get("status") not in STATUS_PENDENTES or
            any(not isinstance(item.get(k),str) or not item[k].strip()
                for k in ("role","candidate_target","validation"))):
            raise ErroPoliticas("regra diverge do catálogo ou não identifica limitações")
        falta=[
            "PARSER_E_FONTE_EM_PRODUCAO" if dataset.get("enabled") is not True else None,
            "DIREITO_DE_COLETA" if dataset.get("collection_authorized") is not True else None,
            "DIREITO_DE_TREINAMENTO" if dataset.get("training_authorized") is not True else None,
            "LABEL_EVIDENCIADO_E_AUDITADO",
            "AUDITORIA_INDEPENDENTE_E_HOMOLOGACAO",
        ]
        resumo.append({
            "dataset_id":id,"fonte_id":item["source_id"],
            "papel":item["role"],"alvo":item["candidate_target"],
            "estado":item["status"],
            "pendencias":[f for f in falta if f is not None],
            "treinamento_real_habilitado":False,
        })
    return {
        "estado":"NENHUMA_FONTE_AUTORIZADA_AUTOMATICAMENTE",
        "fontes_catalogadas":len(resumo),
        "fontes_prontas_para_treino_real":0,
        "fontes_aguardando_homologacao":len(resumo),
        "detalhes":sorted(resumo,key=lambda x:x["dataset_id"]),
        "aviso":"Lista de prioridade não é autorização de licença ou comprovação de label realizado.",
    }
