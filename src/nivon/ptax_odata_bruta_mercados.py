"""BCB PTAX/OData: parsing fiel de bytes JSON, sem rede nem publicação.

Contrato de período USD/EUR conforme planejador interno e documentação
de dados abertos BCB. Evita float, separa referência intradiária e coleta,
não inventa data de publicação, histórico original de previsão nem licença.
Dados do JSON são informados; autenticidade do servidor exige transporte
confiável e evidência externa de coleta, fora deste módulo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Mapping
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

from .ptax_plano import BASE
from .qualidade_mercados import _momento


class ErroPTAXBruto(ValueError):
    """Arquivo bruto ou contrato temporal de PTAX inválido."""


FUSO = ZoneInfo("America/Sao_Paulo")
MAX_BYTES = 2_000_000
MAX_LINHAS = 500
CAMPOS_LINHA = frozenset({
    "cotacaoCompra", "cotacaoVenda", "dataHoraCotacao", "tipoBoletim",
    "paridadeCompra", "paridadeVenda",
})
CAMPOS_ROOT = frozenset({"@odata.context", "value"})
TIPOS_VALIDOS = frozenset({
    "Fechamento", "Abertura", "Intermediário", "Intermediario",
})
DOCUMENTACAO = "https://dadosabertos.bcb.gov.br/pt_BR/dataset/dolar-americano-usd-todos-os-boletins-diarios"


def _parse_json(raw: bytes) -> dict:
    if (not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES or
            raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw):
        raise ErroPTAXBruto("arquivo JSON bruto ausente/inválido/excessivo")

    def sem_repeticao(pares):
        obj = {}
        for k, v in pares:
            if k in obj:
                raise ErroPTAXBruto("chave JSON duplicada")
            obj[k] = v
        return obj

    def nao_finito(v):
        raise ErroPTAXBruto("número não finito em JSON")

    try:
        d = json.loads(raw.decode("utf-8", errors="strict"),
                       parse_float=Decimal, parse_int=Decimal,
                       parse_constant=nao_finito,
                       object_pairs_hook=sem_repeticao)
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ErroPTAXBruto):
            raise
        raise ErroPTAXBruto("JSON bruto inválido") from exc
    if not isinstance(d, dict) or not set(d) <= CAMPOS_ROOT or "value" not in d:
        raise ErroPTAXBruto("envelope OData inesperado/incompleto")
    if (not isinstance(d["value"], list) or not d["value"]
            or len(d["value"]) >= MAX_LINHAS):
        raise ErroPTAXBruto("lote OData vazio/possivelmente truncado")
    if "@odata.context" in d and not isinstance(d["@odata.context"], str):
        raise ErroPTAXBruto("metadados OData inválidos")
    return d


def _consulta(url: str, moeda: str) -> tuple[date, date]:
    if moeda not in ("USD", "EUR"):
        raise ErroPTAXBruto("moeda USD/EUR obrigatória")
    if not isinstance(url, str) or len(url) > 1200:
        raise ErroPTAXBruto("URL de consulta inválida")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "olinda.bcb.gov.br"
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        raise ErroPTAXBruto("endpoint PTAX não oficial")
    expected_path = (
        "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        if moeda == "USD" else
        "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    )
    if parsed.path != urlsplit(BASE).path + expected_path:
        raise ErroPTAXBruto("operação OData não permitida")
    try:
        args = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ErroPTAXBruto("parâmetros OData inválidos") from exc
    keys = {"@dataInicial", "@dataFinalCotacao", "$top", "$format"}
    if moeda == "EUR":
        keys.add("@moeda")
    if set(args) != keys or any(len(v) != 1 for v in args.values()):
        raise ErroPTAXBruto("parâmetros OData extras, duplicados ou ausentes")
    if args["$format"][0] != "json" or args["$top"][0] != "500":
        raise ErroPTAXBruto("formato ou limite OData incompatível")
    if moeda == "EUR" and args["@moeda"][0] != "'EUR'":
        raise ErroPTAXBruto("moeda OData divergente")
    def data_param(k: str) -> date:
        valor = args[k][0]
        if (len(valor) != 12 or valor[0] != "'" or valor[-1] != "'"):
            raise ErroPTAXBruto("literal OData de data inválido")
        try:
            d = datetime.strptime(valor[1:-1], "%m-%d-%Y").date()
        except ValueError as exc:
            raise ErroPTAXBruto("data de consulta inválida") from exc
        if d.strftime("%m-%d-%Y") != valor[1:-1]:
            raise ErroPTAXBruto("data de consulta não canônica")
        return d
    a, b = data_param("@dataInicial"), data_param("@dataFinalCotacao")
    if a > b or (b-a).days > 19:
        raise ErroPTAXBruto("intervalo de consulta excedido ou invertido")
    return a, b


def _preco(v: object, campo: str) -> str:
    if type(v) is not Decimal or not v.is_finite() or v <= 0:
        raise ErroPTAXBruto(f"{campo}: preço decimal numérico positivo obrigatório")
    if len(v.as_tuple().digits) > 16 or v.adjusted() > 10 or v.adjusted() < -10:
        raise ErroPTAXBruto(f"{campo}: magnitude ou precisão inválida")
    return str(v)


def _data_hora(v: object) -> datetime:
    if not isinstance(v, str) or len(v) > 40:
        raise ErroPTAXBruto("dataHoraCotacao inválida")
    try:
        d = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ErroPTAXBruto("dataHoraCotacao inválida") from exc
    if d.tzinfo is not None:
        raise ErroPTAXBruto("BCB dataHoraCotacao: offset inesperado no contrato")
    local = d.replace(tzinfo=FUSO)
    if (local.utcoffset() is None or
            local.astimezone(timezone.utc).astimezone(FUSO).replace(
                tzinfo=None) != d):
        raise ErroPTAXBruto("dataHoraCotacao: horário civil local inexistente")
    return local


def verificar_ptax_odata_bruta(
    arquivo_original: bytes, *, consulta_url: str, moeda: str,
    coletado_em: str, as_of: str, raw_sha256_esperado: str,
) -> dict:
    """Confere snapshot OData e preserva preços/boletins em Decimal textual.

    raw_sha256_esperado é digest declarado por outra camada; sozinho não
    autentica origem nem garante que a captura ocorreu no instante alegado.
    """
    inicio, fim = _consulta(consulta_url, moeda)
    try:
        coleta = _momento(coletado_em, "coletado_em")
        corte = _momento(as_of, "as_of")
    except ValueError as exc:
        raise ErroPTAXBruto("coleta/as_of com fuso obrigatório") from exc
    if coleta > corte:
        raise ErroPTAXBruto("captura posterior ao corte temporal")
    if (not isinstance(raw_sha256_esperado, str)
            or len(raw_sha256_esperado) != 64 or
            any(c not in "0123456789abcdef" for c in raw_sha256_esperado)):
        raise ErroPTAXBruto("SHA256 externo inválido")
    if sha256(arquivo_original).hexdigest() != raw_sha256_esperado:
        raise ErroPTAXBruto("SHA256 bruto diferente do esperado")
    data = _parse_json(arquivo_original)
    registro = []
    vistos = set()
    for pos, row in enumerate(data["value"]):
        if not isinstance(row, dict) or not ({"cotacaoCompra", "cotacaoVenda", "dataHoraCotacao"} <= set(row)
                    <= CAMPOS_LINHA):
            raise ErroPTAXBruto("schema de cotação PTAX inesperado")
        local = _data_hora(row["dataHoraCotacao"])
        if not inicio <= local.date() <= fim:
            raise ErroPTAXBruto("boletim fora do intervalo solicitado")
        instante = local.astimezone(timezone.utc)
        if instante > coleta:
            raise ErroPTAXBruto("hora da cotação depois da captura")
        tipo = row.get("tipoBoletim")
        if tipo is not None and (not isinstance(tipo, str) or tipo not in TIPOS_VALIDOS):
            raise ErroPTAXBruto("tipo de boletim não reconhecido")
        identidade = (local.isoformat(), tipo)
        if identidade in vistos:
            raise ErroPTAXBruto("boletim PTAX duplicado")
        vistos.add(identidade)
        compra = _preco(row["cotacaoCompra"], "compra")
        venda = _preco(row["cotacaoVenda"], "venda")
        if Decimal(compra) > Decimal(venda):
            raise ErroPTAXBruto("compra maior que venda")
        pc, pv = row.get("paridadeCompra"), row.get("paridadeVenda")
        if (pc is None) != (pv is None):
            raise ErroPTAXBruto("paridadeCompra/paridadeVenda incompletas")
        paridade = ({"compra": _preco(pc, "paridadeCompra"),
                     "venda": _preco(pv, "paridadeVenda")}
                    if pc is not None else None)
        # Posicao JSON Pointer: toda linha original "value[i]" foi lida
        # diretamente do arquivo bruto, sem uma transformação intermediária.
        registro.append({
            "fonte_id": "BCB_PTAX",
            "moeda": moeda, "tipo_boletim": tipo,
            "boletim_fechamento_confirmado": tipo == "Fechamento",
            "data_referencia": local.date().isoformat(),
            "referencia_em": local.isoformat(),
            "coletado_em": coleta.isoformat(),
            "publicacao_em": None,
            "cotacao_compra_decimal": compra,
            "cotacao_venda_decimal": venda,
            "unidade": "BRL/" + moeda,
            "paridades": paridade,
            "ponteiro_json": f"/value/{pos}",
            "raw_sha256": raw_sha256_esperado,
        })
    registro.sort(key=lambda x: (x["referencia_em"], x["tipo_boletim"] or ""))
    return {
        "status": "PTAX_ODATA_RAW_CONFERIDO_OFFLINE",
        "fonte_id": "BCB_PTAX",
        "fonte_catalogo_url": DOCUMENTACAO,
        "licenca_catalogo": "ODbL",
        "moeda": moeda,
        "inicio": inicio.isoformat(), "fim": fim.isoformat(),
        "raw_sha256": raw_sha256_esperado,
        "boletins": registro,
        "boletins_distintos": len(registro),
        "publicacao_independente_comprovada": False,
        "horario_coleta_independente_comprovado": False,
        "origem_http_autenticada": False,
        "direitos_redistribuicao_homologados": False,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
        "probabilidades_calibradas": None,
    }
