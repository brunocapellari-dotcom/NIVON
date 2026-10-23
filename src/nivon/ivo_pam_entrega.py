"""Saída editorial estruturada das coletas PAM para IVO e relatórios.

Reutiliza consulta/painel existentes; nenhuma projeção, média municipal,
resultado mensal ou publicação retroativamente atribuída ao ano civil.
Cada linha mantém fonte, geografia, produto, variável, unidade e SHA.
"""
from __future__ import annotations

import sqlite3

from .ivo_pam_consulta import painel_pam_ivo
from .ivo_pam_alertas import alertas_revisoes_pam
from .sidra_pam import planejar_pam_1612


class ErroEntregaPAM(ValueError):
    pass


def montar_entrega_pam_ivo(*,db:sqlite3.Connection,tarefas:list,
                          radar:dict,limite: int=30)->dict:
    if (not isinstance(db,sqlite3.Connection) or not isinstance(tarefas,list)
            or type(limite) is not int or not 1<=limite<=30
            or not 1<=len(tarefas)<=limite):
        raise ErroEntregaPAM("lote de entrega inválido")
    if (not isinstance(radar,dict) or
            radar.get("estado")!="RADAR_PAM_CALCULADO_SOBRE_CAPTURAS"
            or radar.get("captura_equivale_a_publicacao") is not False):
        raise ErroEntregaPAM("radar de captura obrigatório e não homologado")
    vistos=set()
    rows=[]
    for tarefa in tarefas:
        if not isinstance(tarefa,dict):
            raise ErroEntregaPAM("tarefa com formato inválido")
        try:
            plano=planejar_pam_1612(
                municipio_ibge=tarefa.get("municipio_ibge"),ano=tarefa.get("ano"),
                codigo_produto_c81=tarefa.get("categoria_c81"),
                codigo_variavel=tarefa.get("variavel"))
        except (ValueError,KeyError,TypeError) as exc:
            raise ErroEntregaPAM("identidade PAM da tarefa inválida") from exc
        key=(plano["municipio_ibge"],plano["ano"],
             plano["categoria_c81"],plano["variavel"])
        if key in vistos:
            continue
        vistos.add(key)
        start=max(1974,plano["ano"]-1)
        resumo=painel_pam_ivo(db,municipio_ibge=key[0],produto=key[2],
                             variavel=key[3],ano_inicio=start,ano_fim=key[1])
        atual=resumo["serie_anual"][-1]
        rows.append({
            "municipio_ibge":key[0],"ano_civil":key[1],
            "categoria_c81":key[2],"produto":resumo["produto"],
            "variavel":key[3],"indicador":resumo["indicador"],
            "unidade":resumo["unidade"],"estado":atual["estado"],
            "valor_candidato":atual["valor"],
            "sha256_original":atual["sha256"],
            "ultima_coleta_em":atual["capturado_em"],
            "capturas_acumuladas_desta_celula":atual["capturas"],
            "revisoes_de_valor_registradas":atual["revisoes_de_valor"],
            "comparacao_ano_anterior":(
                {"delta":atual["delta_anual"],
                 "variacao_pct":atual["variacao_pct_anual"]}
                if atual["anos_consecutivos"] else None),
            "rotulo":"ESTATISTICA_PAM_ANUAL_INFORMADA_NAO_CERTIFICADA",
        })
    return {
        "estado":"ENTREGA_ESTRUTURADA_PAM_PARA_IVO",
        "fonte":"IBGE_PAM","calendario":"ANO_CIVIL",
        "linhas":rows,"celulas_unicas":len(rows),
        "alteracoes_materiais_neste_ciclo":radar["alteracoes_relevantes"],
        "eventos_relevantes":radar["eventos"],
        "data_oficial_publicacao_conhecida":False,
        "previsao_gerada":False,
        "frete_medio_municipal_calculado":False,
        "observacao":"Dado anual capturado, não produção mensal ou safra CONAB; revisão é por data de coleta.",
    }
