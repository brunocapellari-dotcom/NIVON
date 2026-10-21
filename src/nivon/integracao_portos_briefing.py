"""Ponte tipada line-up nacional -> briefing NIVON (sem rede ou envio).

Uma licença aprovada não transforma um parser não homologado em dado publicável.
Nenhuma informação obtida apenas de catálogo/ETA/HTML antigo é publicada.
Este módulo não altera os contratos de direitos nem concede aprovação.
"""
from __future__ import annotations

from .briefing_composto import montar_briefing
from .catalogo_fontes import carregar_catalogo, validar_catalogo
from .lineup_nacional import carregar_escopo, instante
from .qualidade_lineup import montar_painel_lineup


class ErroPontePortuaria(ValueError):
    pass


def preparar_portos_para_briefing(
    registros: list[dict], licencas: dict, *, gerado_em: str,
    catalogo: dict | None = None, escopo: dict | None = None,
) -> dict:
    """Retorna somente indicadores admissíveis e diagnósticos por porto.

    Os campos de prontidão são provenientes de governança/autorização externa,
    não de título ou dados extraídos da página. O catálogo canônico do repositório
    desativa todos os datasets; com ele nenhuma carga é publicada.
    """
    cat = catalogo if catalogo is not None else carregar_catalogo()
    esc = escopo if escopo is not None else carregar_escopo()
    instante(gerado_em)
    fontes = {f["id"]:f for f in cat["sources"]}
    conjuntos = {d["id"]:d for d in cat["datasets"]}
    portos = {p["id"]:p for p in esc["ports"]}
    recusas = []
    elegiveis = []
    # A entrada pode conter dados do próprio site; nunca lhe conceder direitos.
    for i,r in enumerate(registros):
        try:
            if not isinstance(r,dict):
                raise ErroPontePortuaria("registro não estruturado")
            pid = r.get("porto_id")
            if pid not in portos:
                raise ErroPontePortuaria("porto fora do escopo canônico")
            did = "LINEUP_"+pid
            d = conjuntos.get(did)
            if not d or d.get("source_id") != r.get("fonte_id"):
                raise ErroPontePortuaria("dataset/fonte não associados ao porto")
            if r["fonte_id"] not in fontes:
                raise ErroPontePortuaria("fonte não cadastrada")
            perm = licencas.get(r["fonte_id"])
            if not isinstance(perm,dict) or perm.get("status")!="APROVADA" or not perm.get("evidencia_id"):
                raise ErroPontePortuaria("licença não comprovada")
            if not {"LEITURA","COLETA","PUBLICACAO_DERIVADA"}.issubset(set(perm.get("operacoes",[]))):
                raise ErroPontePortuaria("operações não licenciadas")
            # A autorização do catálogo pode ser liberada apenas após homologação.
            if not (d.get("enabled") is True and
                    d.get("collection_authorized") is True and
                    d.get("commercial_redistribution_authorized") is True and
                    portos[pid].get("parser_homologated") is True):
                raise ErroPontePortuaria("coleta/redistribuição/parser ainda não homologados")
            elegiveis.append(r)
        except (KeyError,TypeError,ValueError,ErroPontePortuaria) as exc:
            recusas.append({"indice":i,"motivo":str(exc)})
    auditado=montar_painel_lineup(elegiveis,licencas,gerado_em=gerado_em)
    contas={f:{"status_direitos":"APROVADA",
                "operacoes":["LEITURA","RESUMO","PUBLICACAO_DERIVADA"],
                "id_aprovacao":licencas[f]["evidencia_id"]}
            for f in sorted({x["fonte_id"] for x in elegiveis})}
    return {"indicadores":auditado["indicadores_briefing"],"fontes":contas,
            "painel":auditado["painel"],
            "rejeicoes":recusas+auditado["rejeicoes"],
            "status":"DADOS_HOMOLOGADOS_PARA_EDICAO" if auditado["painel"]
                     else "DADOS_INDISPONIVEIS_OU_NAO_HOMOLOGADOS",
            "publicacao_executada":False,
            "nota":"Nenhum registro válido não significa porto sem navios."}


def montar_briefing_com_portos(
    *, noticias: list[dict], fontes_noticias: dict,
    indicadores: list[dict], registros_portuarios: list[dict],
    licencas_portuarias: dict, gerado_em: str,
    fretes: list[dict] | None = None, catalogo: dict | None = None,
    escopo: dict | None = None,
) -> dict:
    """Entrega apenas TEXTO PRONTO PARA AUDITORIA, sem transmitir mensagem."""
    ports=preparar_portos_para_briefing(
        registros_portuarios,licencas_portuarias,gerado_em=gerado_em,
        catalogo=catalogo,escopo=escopo,
    )
    fontes=dict(fontes_noticias)
    if set(fontes).intersection(ports["fontes"]):
        raise ErroPontePortuaria("conflito entre fontes de notícias e portos")
    fontes.update(ports["fontes"])
    texto=montar_briefing(
        noticias=noticias,fontes=fontes,data=gerado_em,
        indicadores=[*indicadores,*ports["indicadores"]],fretes=fretes,
    )
    texto["rejeicoes"]=ports["rejeicoes"]+texto["rejeicoes"]
    texto["painel_portuario"]=ports["painel"]
    texto["status_portuario"]=ports["status"]
    texto["status"]="PREPARADO_SEM_ENVIO"
    return texto
