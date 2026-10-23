"""Ponte de cotações para briefing NIVON com gate de direitos comerciais.

Não captura CME/ICE/B3: precisa de fonte licenciada. Não gera preços estimados.
Uma última liquidação pode ter data anterior a 24h; sempre identificar fechamento.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from .lineup_nacional import instante


class ErroMercado(ValueError):
    pass


FONTES = {"CME", "ICE", "B3", "CEPEA", "IMEA"}
TIPOS = {"FECHAMENTO", "AJUSTE", "INDICADOR_FISICO"}
UNIDADES = {"USD/BU", "USD/T", "USD/SHORT_TON", "USC/LB", "USD/CWT",
            "BRL/SC60KG", "BRL/ARROBA", "BRL/L", "BRL/T", "USD/SC60KG"}


def cotacao_para_briefing(item: dict, direito: dict, *, gerado_em: str) -> dict:
    """Aprova somente cotação com direitos verificados para redistribuição."""
    if not isinstance(item, dict) or not isinstance(direito, dict):
        raise ErroMercado("registro ou licença ausente")
    fonte=item.get("fonte")
    if fonte not in FONTES or fonte!=direito.get("fonte"):
        raise ErroMercado("origem de mercado divergente")
    exigidas={"LEITURA", "ARMAZENAMENTO", "PUBLICACAO_DERIVADA", "REDISTRIBUICAO"}
    if direito.get("status")!="APROVADA" or not exigidas.issubset(set(direito.get("operacoes", []))):
        raise ErroMercado("não autorizado para republicar cotação")
    if not direito.get("id_aprovacao"):
        raise ErroMercado("licença sem evidência documental")
    now=instante(gerado_em)
    if date.fromisoformat(direito["valida_ate"]) < now.date():
        raise ErroMercado("licença expirada")
    ref=instante(item.get("referencia_em"))
    if ref>now:
        raise ErroMercado("fechamento futuro")
    if item.get("tipo") not in TIPOS or item.get("unidade") not in UNIDADES:
        raise ErroMercado("tipo/unidade incompatíveis")
    if item.get("tipo") in {"FECHAMENTO","AJUSTE"} and not item.get("contrato"):
        raise ErroMercado("cotação de futuro sem contrato/vencimento")
    source=item.get("fonte_url","")
    url=urlsplit(source)
    if url.scheme!="https" or not url.hostname or url.username or url.password:
        raise ErroMercado("fonte URL insegura")
    try:
        valor=Decimal(str(item["preco"]))
    except (InvalidOperation,KeyError,TypeError) as exc:
        raise ErroMercado("cotação não numérica") from exc
    if not valor.is_finite() or valor<=0:
        raise ErroMercado("preço deve ser finito e positivo")
    produto=item.get("produto")
    if not isinstance(produto,str) or not produto.strip():
        raise ErroMercado("produto não especificado")
    return {"titulo":f"{produto.strip()} {str(item.get('contrato') or '').strip()}".strip(),
            "valor":f"{valor} {item['unidade']}",
            "fonte":fonte,"referencia":ref.date().isoformat(),
            "detalhes_fonte":source,"mercado_tipo":item["tipo"],
            "licenca_id":direito["id_aprovacao"]}
