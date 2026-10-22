"""NIVON: validação em memória de preços agrobr CEPEA e IMEA.

Não faz scraping, não baixa séries, não grava dados no Neon nem cria agendamentos.
A política de direitos é verificada ANTES de permitir operação de coleta.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json

FONTES = {
    "cepea": {
        "licenca": "CC BY-NC 4.0 (conforme documentação agrobr; validar escopo original)",
        "permite_armazenamento_nc": True,
        "habilitado_automaticamente": False,
        "origem_obrigatoria": "cepea",
    },
    "imea": {
        "licenca": "ZONA_CINZA; confirmar formalmente direitos sobre séries públicas",
        "permite_armazenamento_nc": False,
        "habilitado_automaticamente": False,
        "origem_obrigatoria": "imea",
    },
}
CULTURAS = {"soja", "soja_parana", "milho", "boi", "cafe", "cafe_robusta", "algodao",
            "acucar", "etanol_hidratado", "etanol_anidro"}
CADEIAS = {"soja", "milho", "algodao", "bovinocultura"}
NA = {"noticias_agricolas", "notícias agrícolas", "noticias agricolas"}


class DadosNaoHomologados(PermissionError):
    """Bloqueio metodológico, de licença ou de origem do provedor."""


def permissao_consulta(fonte: str, *, aceite_nc: bool = False,
                      autorizacao_imea: str | None = None) -> None:
    """Não confundir capacidade técnica com consentimento de uso dos dados."""
    if fonte not in FONTES:
        raise ValueError("Fonte desconhecida")
    if fonte == "cepea":
        if not aceite_nc:
            raise DadosNaoHomologados("Confirmar utilização estritamente não comercial e atribuição CEPEA")
    elif not autorizacao_imea or len(autorizacao_imea.strip()) < 8:
        raise DadosNaoHomologados("IMEA: uso de coleta/armazenamento exige direito documentado")


def decimal_preco(valor) -> str:
    if isinstance(valor, bool) or valor is None:
        raise ValueError("Cotação inválida")
    try:
        v = Decimal(str(valor))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Cotação não é decimal") from exc
    if not v.is_finite() or v <= 0:
        raise ValueError("Preço zero, negativo ou não finito: quarentena")
    return format(v, "f")


def data_primaria(valor) -> str:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if not isinstance(valor, str):
        raise ValueError("Data de referência ausente")
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError as exc:
        raise ValueError("Data de referência inválida") from exc


def tem_anomalias(valor) -> bool:
    if valor is None or valor == "":
        return False
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except (ValueError, TypeError):
            return True
    return bool(valor)


def validar_cepea(registros: list[dict], *, aceite_nc: bool,
                  fontes_meta: list[str] | None = None,
                  data_coleta: datetime | None = None) -> dict:
    """Extrai candidatos para persistência. Rejeita fallback Notícias Agrícolas."""
    permissao_consulta("cepea", aceite_nc=aceite_nc)
    if not isinstance(registros, list):
        raise TypeError("Esperado DataFrame convertido para registros")
    if fontes_meta and any(str(f).lower() in NA for f in fontes_meta):
        raise DadosNaoHomologados("MetaInfo indica Notícias Agrícolas; não atribuir ao CEPEA")
    now = data_coleta or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Coleta sem fuso horário explícito")
    candidatos, quarentena = [], []
    for row in registros:
        if not isinstance(row, dict):
            quarentena.append("NOT_RECORD")
            continue
        fonte = str(row.get("fonte") or "").lower().strip()
        if fonte != "cepea":
            quarentena.append("FONTE_NAO_CEPEA")
            continue
        try:
            product = str(row["produto"]).strip().lower()
            if product not in CULTURAS:
                raise ValueError("PRODUTO_DESCONHECIDO")
            referencia = data_primaria(row["data"])
            if referencia > now.date().isoformat():
                raise ValueError("DATA_FUTURA")
            if tem_anomalias(row.get("anomalies")):
                raise ValueError("ANOMALIA_FONTE")
            valor = decimal_preco(row["valor"])
            unidade = str(row["unidade"]).strip()
            if not unidade or unidade.lower() == "nan":
                raise ValueError("UNIDADE_INVALIDA")
            praca = str(row["praca"]).strip() if row.get("praca") is not None else ""
            candidatos.append({
                "origem": "cepea", "produto": product, "praca": praca or None,
                "valor": valor, "unidade": unidade,
                "data_referencia": referencia, "data_publicacao": None,
                "data_coleta": now.isoformat(), "competencia": referencia[:7],
                "classificacao": "INFORMADO", "licenca": FONTES["cepea"]["licenca"],
                "widget_origem": None, "proveniencia": "agrobr:cepea",
            })
        except (KeyError, ValueError, TypeError) as exc:
            quarentena.append(str(exc).split(":")[0][:70])
    return {"candidatos": candidatos, "quarentena": quarentena,
            "contagem": len(candidatos), "rejeitados": len(quarentena)}


def inspecionar_imea(registros: list[dict], *, autorizacao_imea: str | None = None) -> dict:
    """Auditoria estrutural: jamais considera data_publicacao como data de preço."""
    permissao_consulta("imea", autorizacao_imea=autorizacao_imea)
    aceitos, quarentena = [], []
    duplicatas = set()
    for r in registros:
        if not isinstance(r, dict):
            quarentena.append("NOT_RECORD")
            continue
        indicador = str(r.get("indicador") or "").lower().strip()
        cadeia = str(r.get("cadeia") or "").lower().strip()
        if cadeia not in CADEIAS or not indicador:
            quarentena.append("CADEIA_OU_INDICADOR")
            continue
        if "semente" in indicador and cadeia == "soja":
            quarentena.append("SEMENTE_NAO_PRECO_GRAO")
            continue
        try:
            valor = decimal_preco(r.get("valor"))
        except ValueError:
            quarentena.append("PRECO_NAO_POSITIVO_OU_AUSENTE")
            continue
        indicador_id = str(r.get("indicador_id") or "").strip()
        localidade = str(r.get("localidade") or "").strip()
        unidade = str(r.get("unidade") or "").strip()
        publicacao = r.get("data_publicacao")
        safra = str(r.get("safra") or "").strip()
        if not indicador_id or not localidade or not unidade:
            quarentena.append("CHAVE_INCOMPLETA")
            continue
        key = (indicador_id, localidade, str(publicacao), safra, unidade, valor)
        if key in duplicatas:
            quarentena.append("DUPLICATA_EXATA")
            continue
        duplicatas.add(key)
        # O agrobr descreve data_publicacao e não atesta data_referencia por linha.
        # Bloquear a promoção à série de tendências até resolver esta ambiguidade.
        aceitos.append({
            "origem": "imea", "cadeia": cadeia, "indicador_id": indicador_id,
            "indicador": r["indicador"], "praca": localidade, "safra": safra or None,
            "unidade": unidade, "valor": valor,
            "data_publicacao": str(publicacao) if publicacao is not None else None,
            "data_referencia": None, "estado": "AGUARDA_DATA_REFERENCIA",
            "autorizacao": autorizacao_imea,
        })
    return {"candidatos_quarentenados": aceitos,
            "quarentena": quarentena, "contagem": len(aceitos),
            "publicaveis_tendencia": 0}


async def consultar_cepea_para_validacao(produto: str, *, aceite_nc: bool,
                                         inicio: str | None = None,
                                         fim: str | None = None) -> dict:
    """Consulta explícita, só CEPEA; nunca grava base ou publica valores automaticamente."""
    permissao_consulta("cepea", aceite_nc=aceite_nc)
    if produto not in CULTURAS:
        raise ValueError("Produto não homologado")
    try:
        from agrobr import cepea
    except ImportError as exc:
        raise RuntimeError("agrobr não instalado; instalar em ambiente isolado") from exc
    df, meta = await cepea.indicador(produto, inicio=inicio, fim=fim, return_meta=True)
    sources = getattr(meta, "data_sources", None) or []
    if isinstance(sources, dict):
        sources = list(sources.keys())
    if isinstance(sources, str):
        sources = [sources]
    results = validar_cepea(df.to_dict(orient="records"), aceite_nc=aceite_nc,
                             fontes_meta=sources)
    # Evitar devolver os valores para logs públicos acidentais
    return {"produto": produto, "linhas_aprovadas_em_memoria": results["contagem"],
            "linhas_em_quarentena": results["rejeitados"], "armazenado": False,
            "sources_reported": sorted(str(s) for s in sources)}


def estado_fontes() -> dict:
    return {"cepea": {"consulta_explicita": True, "gravacao_automatica": False},
            "imea": {"consulta_automatica": False, "gravacao_automatica": False,
                     "motivo": "direitos e data de referencia nao homologados"}}
