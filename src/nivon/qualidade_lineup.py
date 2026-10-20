"""Validação de atualidade e direitos antes de inserir line-up no briefing.

Não faz HTTP. Não interpreta hora de COLETA como hora de PUBLICAÇÃO.
Não afirma 0 navios quando dados falham. Não duplica escala entre edições.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlsplit

from .lineup_nacional import instante

ESTADOS = frozenset({"ESPERADO", "PROGRAMADO", "AO_LARGO", "ATRACADO",
                     "OPERANDO", "DESPACHADO", "CONCLUIDO"})
OPERACOES_REQUERIDAS = frozenset({"LEITURA", "COLETA", "PUBLICACAO_DERIVADA"})


class ErroQualidadeLineup(ValueError):
    pass


def montar_painel_lineup(registros: list[dict], licencas: dict,
                        *, gerado_em: str, idade_maxima_horas: int = 48) -> dict:
    """Resumo orientado à publicação, porém publicação depende de direitos verificados.

    Só uma escala (DUV) por porto, produto e situação em cada edição.
    Volumes não são somados sem ID de lote, unidade e evidência explícitos.
    """
    agora = instante(gerado_em)
    if isinstance(idade_maxima_horas, bool) or not isinstance(idade_maxima_horas,int) or not 1<=idade_maxima_horas<=72:
        raise ErroQualidadeLineup("janela de atualidade fora do limite")
    if not isinstance(registros,list) or len(registros)>100000:
        raise ErroQualidadeLineup("line-up com registros excessivos")
    grupos=defaultdict(lambda:{"escalas":set(),"status":defaultdict(set),
                               "toneladas_por_lote":{},"fontes":set(),"referencias":[]})
    rejeicoes=[]
    eventos_vistos=set()
    for i,r in enumerate(registros):
        try:
            if not isinstance(r,dict):
                raise ErroQualidadeLineup("registro não estruturado")
            fid=r.get("fonte_id")
            direito=licencas.get(fid)
            if not isinstance(direito,dict) or direito.get("status")!="APROVADA":
                raise ErroQualidadeLineup("fonte sem direitos homologados")
            if not OPERACOES_REQUERIDAS <= set(direito.get("operacoes", [])):
                raise ErroQualidadeLineup("licença insuficiente para derivado")
            if not direito.get("evidencia_id"):
                raise ErroQualidadeLineup("direitos sem comprovação")
            porto,produto,status=(str(r.get(k) or "").strip().upper()
                                  for k in ("porto_id","produto","situacao"))
            if not porto or not produto or status not in ESTADOS:
                raise ErroQualidadeLineup("porto/produto/situação inválidos")
            duv=str(r.get("duv") or "").strip()
            if not duv:
                raise ErroQualidadeLineup("escala sem DUV não integra contagem")
            fonteurl=str(r.get("fonte_url") or "")
            parsed=urlsplit(fonteurl)
            if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
                raise ErroQualidadeLineup("origem HTTPS não verificada")
            pub=instante(r.get("publicado_em"))
            ref=instante(r.get("referencia_em"))
            coleta=instante(r.get("coletado_em"))
            if pub > coleta or coleta > agora or ref > agora:
                raise ErroQualidadeLineup("sequência temporal impossível")
            if ref < agora - timedelta(hours=idade_maxima_horas):
                raise ErroQualidadeLineup("linha de navio antiga")
            if pub < agora - timedelta(hours=idade_maxima_horas):
                raise ErroQualidadeLineup("documento antigo")
            if r.get("apto_briefing") is False:
                raise ErroQualidadeLineup("parser de origem não homologado")
            # Evidência operacional não deve ser promovida para carga realizada.
            if status in {"OPERANDO","CONCLUIDO"} and r.get("classe_evidencia") != "EVENTO_FISICO_VERIFICADO":
                raise ErroQualidadeLineup("operação sem evento físico documentado")
            key=(porto,produto,duv,status)
            if key in eventos_vistos:
                raise ErroQualidadeLineup("linha duplicada já contabilizada")
            vol=r.get("toneladas_programadas")
            lote=str(r.get("lote_id") or "").strip()
            if vol is not None:
                if (not isinstance(vol,(float,int)) or isinstance(vol,bool)
                    or not 0<=vol<=1000000 or not lote
                    or r.get("unidade_confirmada")!="T"
                    or r.get("classe_evidencia")!="LINEUP_INFORMADO"):
                    raise ErroQualidadeLineup("volume sem lote, unidade T ou evidência de programação")
            eventos_vistos.add(key)
            g=grupos[(porto,produto)]
            g["escalas"].add(duv)
            g["status"][status].add(duv)
            g["fontes"].add(fid)
            g["referencias"].append(ref)
            if vol is not None:
                lote_key=(duv,lote)
                if lote_key in g["toneladas_por_lote"]:
                    raise ErroQualidadeLineup("volume por lote duplicado")
                g["toneladas_por_lote"][lote_key]=vol
        except (KeyError,TypeError,ValueError,ErroQualidadeLineup) as exc:
            rejeicoes.append({"indice":i,"motivo":str(exc)})
    painel=[]
    indicadores=[]
    for (porto,produto),g in sorted(grupos.items()):
        status_counts={s:len(escalas) for s,escalas in sorted(g["status"].items())}
        referencia=max(g["referencias"]).isoformat()
        item={"porto_id":porto,"produto":produto,
              "escalas_distintas":len(g["escalas"]),"status_informados":status_counts,
              "toneladas_programadas_com_lote":round(sum(g["toneladas_por_lote"].values()),3)
                if g["toneladas_por_lote"] else None,
              "fontes":sorted(g["fontes"]),"referencia_em":referencia,
              "nota":"Programação não equivale a embarque realizado"}
        painel.append(item)
        status_text="; ".join(f"{s}: {n}" for s,n in status_counts.items())
        indicadores.append({"fonte_id":sorted(g["fontes"])[0],
                           "secao":"PORTOS", "titulo":f"{porto} — {produto}",
                           "valor":status_text, "referencia":referencia,
                           "fonte":"Autoridade portuária (line-up informado)"})
    return {"painel":painel,"indicadores_briefing":indicadores,
            "rejeicoes":rejeicoes,"status":"DADOS_ELEGIVEIS_COM_DIREITOS_OU_INDISPONIVEIS",
            "observacao":"Nenhuma entrada não validada é interpretada como 0 navios"}
