"""PTAX BCB: aquisição HTTPS controlada, validação e indicador para briefing.

Distingue Fechamento de Abertura/Intermediário/Fechamento Interbancário.
ODbL exige atribuição e revisão das obrigações de redistribuição/derivados.
Nenhuma fonte real é habilitada por padrão e nada é enviado ao WhatsApp.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from .bcb_ptax import normalizar_ptax_odata
from .coleta_web import FonteWeb, adquirir_fonte
from .lineup_nacional import instante
from .ptax_plano import planejar_consultas_ptax

PAGINA_LICENCA = "https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios"
LICENCA = "ODbL-1.0"


class ErroPTAXBriefing(ValueError):
    pass


def _validar_plano(plano: dict) -> None:
    if not isinstance(plano,dict) or plano.get("dataset_id")!="BCB_PTAX":
        raise ErroPTAXBriefing("consulta PTAX não é dataset canônico")
    try:
        inicio=date.fromisoformat(plano["inicio"])
        fim=date.fromisoformat(plano["fim"])
        dias=(fim-inicio).days+1
        esperado=planejar_consultas_ptax(moeda=plano["moeda"],
                                        inicio=plano["inicio"],fim=plano["fim"],
                                        dias_janela=dias)
    except (KeyError, TypeError, ValueError) as exc:
        raise ErroPTAXBriefing("plano PTAX inválido") from exc
    if len(esperado)!=1 or plano!=esperado[0]:
        raise ErroPTAXBriefing("endpoint ou parâmetros PTAX divergentes do planejador")


def adquirir_ptax_autorizado(plano: dict, *, dataset: dict,
                           direitos: dict, coletado_em: str, abridor=None) -> dict:
    """Acesso real exige gates do catálogo + direito documental; não altera cadastro."""
    _validar_plano(plano)
    if not isinstance(dataset,dict) or dataset.get("id")!="BCB_PTAX":
        raise ErroPTAXBriefing("dataset não corresponde à PTAX")
    if not (dataset.get("enabled") is True and
            dataset.get("collection_authorized") is True):
        raise PermissionError("PTAX bloqueada no catálogo: coleta não homologada")
    if not isinstance(direitos,dict) or direitos.get("status")!="APROVADA" or not {
        "LEITURA","COLETA","ARMAZENAMENTO",
    }.issubset(set(direitos.get("operacoes",[]))) or not direitos.get("evidencia_id"):
        raise PermissionError("direitos de coleta PTAX ausentes")
    if direitos.get("licenca")!=LICENCA:
        raise PermissionError("licença ODbL não registrada")
    coleta=instante(coletado_em)
    fonte=FonteWeb(
        fonte_id="BCB_PTAX",url=plano["url"],dominio_autorizado="olinda.bcb.gov.br",
        formato="JSON",status_direitos="APROVADA",
        operacoes_permitidas=frozenset({"COLETA"}),limite_bytes=2_000_000,
    )
    resp=adquirir_fonte(fonte,abridor=abridor,instante=coleta)
    if resp["url"]!=plano["url"] or resp["fonte_id"]!="BCB_PTAX":
        raise ErroPTAXBriefing("snapshot não pertence à consulta")
    return resp


def normalizar_snapshot_ptax(snapshot: dict, plano: dict) -> dict:
    """Snapshot JSON já coletado, com hash e plano rígido, sem inferir publicação."""
    _validar_plano(plano)
    if (not isinstance(snapshot,dict) or snapshot.get("fonte_id")!="BCB_PTAX"
        or snapshot.get("url")!=plano["url"] or snapshot.get("mime")!="application/json"):
        raise ErroPTAXBriefing("snapshot PTAX com origem/MIME incompatível")
    payload=snapshot.get("conteudo")
    if not isinstance(payload,bytes) or not payload or len(payload)>2_000_000:
        raise ErroPTAXBriefing("payload ausente ou excessivo")
    sha=hashlib.sha256(payload).hexdigest()
    if sha!=snapshot.get("sha256"):
        raise ErroPTAXBriefing("hash de aquisição alterado")
    def no_duplicate(pairs):
        d={}
        for k,v in pairs:
            if k in d:
                raise ErroPTAXBriefing("JSON de dados abertos com chave duplicada")
            d[k]=v
        return d
    try:
        body=json.loads(payload.decode("utf-8-sig"),object_pairs_hook=no_duplicate)
    except ErroPTAXBriefing:
        raise
    except (ValueError,UnicodeError) as exc:
        raise ErroPTAXBriefing("resposta PTAX não é JSON válido") from exc
    norm=normalizar_ptax_odata(body,moeda=plano["moeda"],
                              coletado_em=snapshot["capturado_em"],
                              consulta_url=plano["url"])
    inicio,fim=date.fromisoformat(plano["inicio"]),date.fromisoformat(plano["fim"])
    captura=instante(snapshot["capturado_em"])
    for row in norm["observacoes"]:
        ref=instante(row["referencia"])
        if not inicio<=date.fromisoformat(row["competencia"])<=fim:
            raise ErroPTAXBriefing("observação fora da janela de consulta")
        if ref>captura:
            raise ErroPTAXBriefing("boletim posterior à coleta")
    return {"observacoes":norm["observacoes"],"moeda":plano["moeda"],
            "sha256":sha,"coletado_em":captura.isoformat(),
            "tipo":"DADO_OFICIAL_PTAX_NAO_VALIDADO_PARA_REDISTRIBUICAO"}


def construir_indicador_ptax(dados: dict, *, gerado_em: str,
                             dataset: dict, direitos: dict,
                             atraso_maximo_dias: int = 5) -> dict:
    """Usa SOMENTE boletim Fechamento; sem fechamento, NÃO publica indicador."""
    agora=instante(gerado_em)
    if type(atraso_maximo_dias) is not int or not 1<=atraso_maximo_dias<=7:
        raise ErroPTAXBriefing("prazo máximo inválido")
    if (not isinstance(dataset,dict) or dataset.get("id")!="BCB_PTAX"
        or dataset.get("enabled") is not True
        or dataset.get("collection_authorized") is not True
        or dataset.get("commercial_redistribution_authorized") is not True):
        raise PermissionError("dataset PTAX não homologado para publicar derivado")
    if (not isinstance(direitos,dict) or direitos.get("status")!="APROVADA" or
        direitos.get("licenca")!=LICENCA or
        not direitos.get("evidencia_id") or
        not direitos.get("attribution_reviewed") or
        not direitos.get("share_alike_reviewed") or
        not {"LEITURA","ARMAZENAMENTO","PUBLICACAO_DERIVADA",
             "REDISTRIBUICAO"}.issubset(set(direitos.get("operacoes",[])))):
        raise PermissionError("ODbL/atribuição/obrigações comerciais não homologadas")
    if not isinstance(dados,dict) or dados.get("moeda") not in ("USD","EUR"):
        raise ErroPTAXBriefing("observações de câmbio não suportadas")
    capturado=instante(dados.get("coletado_em"))
    if capturado>agora:
        raise ErroPTAXBriefing("coleta no futuro")
    rows=dados.get("observacoes")
    if not isinstance(rows,list) or not rows:
        raise ErroPTAXBriefing("nenhum boletim confirmado")
    fechamentos={}
    for row in rows:
        if row.get("moeda")!=dados["moeda"] or row.get("fonte_id")!="BCB_PTAX":
            raise ErroPTAXBriefing("moeda ou origem inconsistente")
        ref=instante(row.get("referencia"))
        if ref>capturado or ref>agora:
            raise ErroPTAXBriefing("observação no futuro")
        if row.get("tipo_boletim")!="Fechamento":
            continue
        dia=row.get("competencia")
        if dia in fechamentos:
            raise ErroPTAXBriefing("dois fechamentos no mesmo dia, revisar")
        fechamentos[dia]=row
    if not fechamentos:
        raise ErroPTAXBriefing("BCB não retornou boletim Fechamento; não usar intradiário")
    fechamento=fechamentos[max(fechamentos)]
    d=date.fromisoformat(fechamento["competencia"])
    data_brasilia=agora.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    if d < data_brasilia-timedelta(days=atraso_maximo_dias):
        raise ErroPTAXBriefing("último fechamento antigo: mostrar indisponível")
    venda=Decimal(str(fechamento["cotacao_venda_brl_por_moeda"]))
    compra=Decimal(str(fechamento["cotacao_compra_brl_por_moeda"]))
    if not (venda.is_finite() and compra.is_finite() and venda>=compra>0):
        raise ErroPTAXBriefing("compra/venda PTAX inválida")
    moeda=dados["moeda"]
    texto=f"R$ {venda:.4f}/{moeda} (venda, PTAX fechamento; R$/{moeda})"
    return {
        "indicador":{"fonte_id":"BCB_PTAX","secao":"CAMBIO",
                     "grupo":"CAMBIO",
                     "titulo":f"{moeda}/BRL — PTAX fechamento","valor":texto,
                     "valor_num":str(venda),"unidade":f"R$/{moeda}",
                     "competencia":fechamento["competencia"],
                     "natureza":"OBSERVADO",
                     "referencia":fechamento["referencia"],
                     "coletado_em":dados["coletado_em"],
                     "sha256_origem":dados["sha256"],
                     "sessao_fechamento":fechamento["competencia"],
                     # Último boletim encontrado no RAW != última sessão oficial concluída.
                     "ultima_sessao_concluida":None,
                     "fechamento_confirmado":False,
                     # Endpoint OData não expõe timestamp de publicação deste boletim.
                     "publicado_em":None,
                     "fonte":"Banco Central do Brasil (PTAX, ODbL)"},
        "fonte_briefing":{"BCB_PTAX":{"status_direitos":"APROVADA",
                          "operacoes":["LEITURA","PUBLICACAO_DERIVADA"],
                          "id_aprovacao":direitos["evidencia_id"]}},
        "evidencia":{"snapshot_sha256":dados.get("sha256"),
                    "fechamento_competencia":d.isoformat(),
                    "cotacao_compra":str(compra),"cotacao_venda":str(venda),
                    "licenca":LICENCA,"licenca_url":PAGINA_LICENCA,
                    "evidencia_direitos":direitos["evidencia_id"],
                    "natureza":"PTAX_FECHAMENTO_NAO_DOLAR_SPOT"},
    }
