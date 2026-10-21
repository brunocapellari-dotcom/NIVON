"""Briefing integrado com fontes, licenças, rotas de frete e entrega opt-in.

O NIVON produz conteúdo determinístico; provedor WhatsApp/Meta é adaptador externo.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite
import re
from .briefing_diario import gerar_texto, ErroBriefing
from .frete_linhas_editoriais import formatar_linha_frete, linha_identificada, CORREDORES
from .politica_frescor_briefing import LIMITES_FRESCURA, validar_frescor_indicador

SECOES = ("BOLSAS", "CAMBIO", "PRECOS", "SAFRA", "PORTOS", "DIESEL",
           "FERTILIZANTES", "CLIMA", "LOGISTICA", "GEOPOLITICA")
assert set(SECOES) == set(LIMITES_FRESCURA)


def montar_briefing(*, noticias: list[dict], fontes: dict,
                    data: str, indicadores: list[dict],
                    fretes: list[dict] | None = None) -> dict:
    """Valores externos sem direitos explícitos são BLOQUEADOS, não exibidos."""
    itens = []
    bloqueios = []
    for registro in indicadores:
        try:
            fid = registro["fonte_id"]
            fonte = fontes[fid]
            if fonte.get("status_direitos") != "APROVADA" or not {
                "LEITURA", "PUBLICACAO_DERIVADA"
            }.issubset(set(fonte.get("operacoes", []))):
                raise ErroBriefing("publicação não autorizada")
            secao = registro["secao"]
            if secao not in SECOES:
                raise ErroBriefing("seção desconhecida")
            titulo = str(registro["titulo"]).strip()
            valor = str(registro["valor"]).strip()
            referencia = str(registro["referencia"]).strip()
            if not titulo or not valor or not referencia:
                raise ErroBriefing("falta valor/referência")
            # O timestamp pertence ao indicador, e não à janela de notícias.
            d = datetime.fromisoformat(referencia.replace("Z", "+00:00"))
            if d.tzinfo is None:
                raise ErroBriefing("indicador sem fuso")
            agora = datetime.fromisoformat(data.replace("Z", "+00:00"))
            if agora.tzinfo is None or d > agora:
                raise ErroBriefing("referência futura ou geração sem fuso")
            # Backstop da PR #13: nem preço fora de janela nem cotação velha,
            # mesmo se origem/licença forem informadas como aprovadas.
            # A vigência do último pregão é conferida SEPARADAMENTE no preflight.
            validar_frescor_indicador(secao=secao, referencia=referencia, gerado_em=data)
            itens.append({
                "secao": secao, "titulo": titulo[:100],
                "valor": valor[:100], "referencia": referencia,
                "fonte": str(registro["fonte"])[:100],
            })
        except (KeyError, TypeError, ValueError, ErroBriefing) as exc:
            bloqueios.append({"tipo": "INDICADOR", "motivo": str(exc)})
    texto, noticias_rejeitadas = gerar_texto(
        noticias, fontes, gerado_em=data, cotacoes=[
            {"titulo": x["titulo"], "valor": x["valor"], "fonte": x["fonte"],
             "referencia": x["referencia"]}
            for x in itens if x["secao"] in {"BOLSAS", "CAMBIO", "PRECOS"}
        ],
    )
    demais = [x for x in itens if x["secao"] not in {"BOLSAS", "CAMBIO", "PRECOS"}]
    bloco = []
    for secao in SECOES:
        grupo = [x for x in demais if x["secao"] == secao]
        if grupo:
            bloco.extend(["", "*" + secao + "*"])
            bloco.extend("• " + x["titulo"] + ": " + x["valor"] +
                         " (ref. " + x["referencia"] + "; " + x["fonte"] + ")"
                         for x in grupo)
    fretes_aceitos = []
    vistos = set()
    agora = datetime.fromisoformat(data.replace("Z", "+00:00"))
    for f in fretes or []:
        try:
            fonte = fontes[f["fonte_id"]]
            if (fonte.get("status_direitos") != "APROVADA"
                    or "PUBLICACAO_DERIVADA" not in fonte.get("operacoes", [])):
                raise PermissionError("frete sem direito de publicação")
            linha = formatar_linha_frete(f)
            referencia = datetime.fromisoformat(f["referencia"].replace("Z", "+00:00"))
            if referencia > agora:
                raise ValueError("frete com referência futura")
            if linha in vistos:
                raise ValueError("republicação de registro individual duplicado")
            vistos.add(linha)
            fretes_aceitos.append(linha)
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            bloqueios.append({"tipo": "FRETE", "motivo": str(exc)})
    if fretes_aceitos:
        bloco.extend(["", "*FRETES ANUNCIADOS — CORREDORES*"])
        bloco.extend(fretes_aceitos)
        bloco.append("Divulgações de transportadoras; não são viagens realizadas.")
    texto_final = texto + (("\n" + "\n".join(bloco)) if bloco else "")
    return {
        "texto": texto_final, "sha256": sha256(texto_final.encode("utf-8")).hexdigest(),
        "indicadores_incluidos": len(itens),
        "fretes_incluidos": len(fretes_aceitos),
        "rejeicoes": bloqueios + noticias_rejeitadas,
        "status": "PREPARADO_SEM_ENVIO",
    }


@dataclass(frozen=True)
class DireitoEntrega:
    destinatario_consentiu: bool = False
    canal_autorizado: bool = False
    custos_aprovados: bool = False
    template_aprovado: bool = False


def solicitar_entrega(briefing: dict, direito: DireitoEntrega, *, remetente=None) -> dict:
    """Interface estreita: sem autorização explícita, não chama remetente.

    O chamador deve persistir chave idempotente e ACK durável antes de liberar
    repetição em nuvem; função não equivale a entrega confirmada.
    """
    if not all((direito.destinatario_consentiu, direito.canal_autorizado,
                direito.custos_aprovados, direito.template_aprovado)):
        return {"status": "BLOQUEADO_ENTREGA", "envio_realizado": False}
    if remetente is None:
        return {"status": "SEM_PROVEDOR_CONFIGURADO", "envio_realizado": False}
    if briefing.get("status") != "PREPARADO_SEM_ENVIO" or not briefing.get("sha256"):
        raise ErroBriefing("briefing não validado")
    recibo = remetente(briefing["texto"], briefing["sha256"])
    if not isinstance(recibo, dict) or not recibo.get("id"):
        raise ErroBriefing("provedor sem recibo de aceitação")
    return {"status": "ACEITO_PELO_PROVEDOR_NAO_ENTREGUE", "id": recibo["id"],
            "envio_realizado": True}
