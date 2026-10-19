"""Normalização offline da API OData PTAX — Banco Central do Brasil.

Não busca a API. Preserva cada boletim sem misturar compra/venda, paridade e
hora da observação com publicação/coleta. `CotacaoMoedaPeriodo` pode ter
vários boletins por dia; não tratá-los como única cotação de fechamento.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit


class ErroPTAX(ValueError):
    pass


FUSO_BCB = ZoneInfo("America/Sao_Paulo")


def _real(valor, campo):
    if type(valor) not in (int, float) or not isfinite(float(valor)) or valor <= 0:
        raise ErroPTAX(campo + " deve ser número positivo e finito")
    return float(valor)


def _coleta(instante):
    if not isinstance(instante, str):
        raise ErroPTAX("data de coleta obrigatória")
    try:
        d = datetime.fromisoformat(instante.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPTAX("data de coleta ISO inválida") from exc
    if d.tzinfo is None:
        raise ErroPTAX("coleta sem fuso horário")
    return d.astimezone(timezone.utc).isoformat()


def normalizar_ptax_odata(payload: dict, *, moeda: str, coletado_em: str,
                          consulta_url: str) -> dict:
    if moeda not in ("USD", "EUR"):
        raise ErroPTAX("moeda fora das séries homologadas neste adaptador")
    p = urlsplit(consulta_url)
    if (p.scheme != "https" or p.hostname != "olinda.bcb.gov.br"
            or p.username or p.password or p.fragment
            or "/servico/PTAX/versao/v1/odata/" not in p.path):
        raise ErroPTAX("URL não corresponde ao serviço oficial PTAX")
    capturado = _coleta(coletado_em)
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise ErroPTAX("resposta OData precisa conter 'value' lista")
    if len(payload["value"]) > 2000:
        raise ErroPTAX("resposta excede janela de ingestão máxima")
    resultado = []
    vistos = set()
    for item in payload["value"]:
        if not isinstance(item, dict):
            raise ErroPTAX("registro não é objeto")
        try:
            horario = datetime.fromisoformat(str(item["dataHoraCotacao"]).replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError) as exc:
            raise ErroPTAX("dataHoraCotacao inválida") from exc
        if horario.tzinfo is None:
            horario = horario.replace(tzinfo=FUSO_BCB)
        horario_iso = horario.astimezone(timezone.utc).isoformat()
        tipo = item.get("tipoBoletim")
        # Campos de tipo podem não estar presentes em determinadas operações.
        if tipo is not None and (not isinstance(tipo, str) or not tipo.strip()):
            raise ErroPTAX("tipo de boletim inválido")
        chave = (horario_iso, tipo)
        if chave in vistos:
            raise ErroPTAX("boletim duplicado com mesma identidade temporal")
        vistos.add(chave)
        compra = _real(item.get("cotacaoCompra"), "cotacaoCompra")
        venda = _real(item.get("cotacaoVenda"), "cotacaoVenda")
        if venda < compra:
            raise ErroPTAX("venda menor que compra")
        paridade_compra = item.get("paridadeCompra")
        paridade_venda = item.get("paridadeVenda")
        if (paridade_compra is None) != (paridade_venda is None):
            raise ErroPTAX("paridades parcialmente ausentes")
        resultado.append({
            "moeda": moeda,
            "referencia_data_hora_utc": horario_iso,
            "competencia": horario.astimezone(FUSO_BCB).date().isoformat(),
            "tipo_boletim": tipo,
            "cotacao_compra_brl_por_moeda": compra,
            "cotacao_venda_brl_por_moeda": venda,
            "paridade_compra": (_real(paridade_compra, "paridadeCompra")
                                if paridade_compra is not None else None),
            "paridade_venda": (_real(paridade_venda, "paridadeVenda")
                               if paridade_venda is not None else None),
            "fonte_id": "BCB_PTAX",
            "referencia": horario_iso,
            "publicacao": None,
            "coleta": capturado,
            "origem_url": consulta_url,
            "classificacao": "INFORMADO_BCB_COTACAO",
        })
    if not resultado:
        raise ErroPTAX("resposta vazia não representa cotação zero")
    resultado.sort(key=lambda x: (x["referencia_data_hora_utc"], x["tipo_boletim"] or ""))
    return {
        "fonte_id": "BCB_PTAX",
        "moeda": moeda,
        "observacoes": resultado,
        "numero_de_boletins": len(resultado),
        "uso": "COTACAO_PTAX_INFORMADA_NAO_PRECO_DE_COMMODITY",
        "coleta_em": capturado,
        "consulta_url": consulta_url,
    }
