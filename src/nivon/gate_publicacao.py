"""Gate determinístico de prontidão editorial antes de autorizar qualquer envio.

Não faz envio nem confia em sinalizadores fornecidos por RSS ou LLM.
"""
from __future__ import annotations

from datetime import timedelta
from .lineup_nacional import instante

BLOCOS_OBRIGATORIOS=("CHICAGO","MERCADO_FISICO","CAMBIO","ENERGIA","FRETES","NOTICIAS")


def avaliar_prontidao_edicao(edicao: dict, *, gerado_em: str,
                             cobertura: dict[str,dict],
                             destinos_opt_in: int = 0,
                             canal_homologado: bool = False,
                             aprovacao_editorial: bool = False) -> dict:
    """Retorna motivos explícitos de bloqueio; nunca altera a edição."""
    motivos=[]
    agora=instante(gerado_em)
    if not isinstance(edicao,dict) or edicao.get("estado")!="EDICAO_OFFLINE_PREPARADA_SEM_ENVIO":
        motivos.append("EDICAO_NAO_PREPARADA")
    if not isinstance(cobertura,dict):
        motivos.append("COBERTURA_AUSENTE")
        cobertura={}
    for bloco in BLOCOS_OBRIGATORIOS:
        registro=cobertura.get(bloco)
        if not isinstance(registro,dict) or registro.get("estado")!="VALIDADO":
            motivos.append("BLOCO_NAO_VALIDADO:"+bloco)
            continue
        if registro.get("fonte_verificada") is not True or registro.get("direitos_aprovados") is not True:
            motivos.append("PROVENIENCIA_OU_DIREITOS:"+bloco)
        try:
            referencia=instante(registro["referencia_em"])
            if referencia>agora or agora-referencia>timedelta(hours=72):
                motivos.append("REFERENCIA_DESATUALIZADA:"+bloco)
        except (KeyError,ValueError,TypeError):
            motivos.append("REFERENCIA_INVALIDA:"+bloco)
    if not isinstance(destinos_opt_in,int) or isinstance(destinos_opt_in,bool) or destinos_opt_in<1:
        motivos.append("SEM_DESTINATARIOS_COM_CONSENTIMENTO")
    if canal_homologado is not True:
        motivos.append("CANAL_WHATSAPP_NAO_HOMOLOGADO")
    if aprovacao_editorial is not True:
        motivos.append("APROVACAO_EDITORIAL_AUSENTE")
    if not isinstance(edicao,dict) or edicao.get("enviado") is not False:
        motivos.append("ESTADO_DE_ENVIO_INCONSISTENTE")
    return {"pronto_para_envio":not motivos,
            "motivos":motivos,
            "politica":"FAIL_CLOSED",
            "observacao":"Prontidão declarativa; não prova execução, licença ou opt-in externo."}
