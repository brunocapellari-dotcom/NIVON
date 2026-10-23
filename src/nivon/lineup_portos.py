"""NIVON: leitura offline de line-ups, controles de qualidade e inferencia AIS.

Sem chamadas de rede, credenciais ou coleta agendada. Dados de terceiros nao
sao redistribuidos neste repositorio; nao confundir programacao com realizado.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Iterable, Mapping, Sequence

FONTES = {
    "suape": {
        "porto": "SUAPE", "origem": "AUTORIDADE_PORTUARIA",
        "url": "https://www.suape.pe.gov.br/pt/operacoes/porto-em-tempo-real/movimento-diario-de-navios-novo-rest",
        "modo": "HTML_PUBLICO", "prioridade": "P0",
    },
    "imbituba": {
        "porto": "IMBITUBA", "origem": "AUTORIDADE_PORTUARIA",
        "url": "https://portodeimbituba.com.br/",
        "modo": "HTML_PUBLICO", "prioridade": "P0",
    },
    "ponta_madeira": {
        "porto": "PONTA_DA_MADEIRA", "origem": "VALE_GPV",
        "url": "https://vale.com/pt/logistica",
        "modo": "IMPORTACAO_AUTORIZADA", "prioridade": "P0",
    },
    "santarem_cdp": {
        "porto": "SANTAREM", "origem": "CDP_DIVERGENCIAS_CONHECIDAS",
        "url": "https://www.cdp.com.br/programacao-de-navios-do-porto-de-santarem/",
        "modo": "HTML_PUBLICO_RECONCILIACAO", "prioridade": "P0",
    },
    "vila_conde_cdp": {
        "porto": "VILA_DO_CONDE", "origem": "CDP_DIVERGENCIAS_CONHECIDAS",
        "url": "https://www.cdp.com.br/programacao-de-navio-do-porto-de-vila-do-conde/",
        "modo": "HTML_PUBLICO_RECONCILIACAO", "prioridade": "P0",
    },
    "itacoatiara_publico": {
        "porto": "ITACOATIARA", "origem": "PORTO_PUBLICO",
        "url": None, "modo": "FONTE_OFICIAL_A_IDENTIFICAR", "prioridade": "P0",
    },
    "itacoatiara_amaggi": {
        "porto": "ITACOATIARA_AMAGGI", "origem": "AIS_NIVON",
        "url": None, "modo": "INFERENCIA_AIS_GEOFENCE", "prioridade": "P0",
    },
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _campo(row: Mapping[str, str], *aliases: str) -> str:
    normalized = {_norm(k): str(v or "").strip() for k, v in row.items()}
    for alias in aliases:
        if _norm(alias) in normalized:
            return normalized[_norm(alias)]
    return ""


def _status(raw: str) -> str:
    value = _norm(raw)
    if "desatracad" in value or "saida" == value:
        return "DESATRACADO_INFORMADO"
    if "atracad" in value:
        return "ATRACADO_INFORMADO"
    if "funde" in value:
        return "FUNDEADO_INFORMADO"
    if "esperad" in value or "programad" in value:
        return "ESPERADO_PROGRAMADO"
    return "STATUS_NAO_DETERMINADO"


def _toneladas(raw: str) -> str | None:
    value = str(raw or "").strip().replace(" ", "")
    if not value or not re.fullmatch(r"\d[\d.,]*", value):
        return None
    # 45.525,25 (BR), 45525.250 (decimal pagina de Imbituba), 45,525.25 (EN)
    if "," in value and "." in value:
        decimal_sep = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if decimal_sep == "," else ",", "")
        if decimal_sep == ",":
            value = value.replace(",", ".")
    elif value.count(",") == 1:
        value = value.replace(",", ".")
    elif value.count(".") > 1:
        value = value.replace(".", "")
    try:
        n = Decimal(value)
        if n < 0:
            return None
        return str(n)
    except InvalidOperation:
        return None


class _HtmlTabelas(HTMLParser):
    """Extrai tabelas e o ultimo titulo anterior, sem executar JavaScript."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabelas: list[tuple[str, list[list[str]]]] = []
        self._heading = ""
        self._heading_depth = 0
        self._heading_buffer: list[str] = []
        self._tables: list[dict] = []
        self._cell_depth = 0
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_depth += 1
            self._heading_buffer = []
        if tag == "table":
            self._tables.append({"heading": self._heading, "rows": [], "row": None})
        elif tag == "tr" and self._tables:
            self._tables[-1]["row"] = []
        elif tag in {"th", "td"} and self._tables and self._tables[-1]["row"] is not None:
            self._cell_depth += 1
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._heading_depth:
            self._heading_buffer.append(data)
        if self._cell_depth:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell_depth and self._tables:
            self._cell_depth -= 1
            if self._cell_depth == 0 and self._tables[-1]["row"] is not None:
                self._tables[-1]["row"].append(" ".join(" ".join(self._cell_text).split()))
        elif tag == "tr" and self._tables:
            frame = self._tables[-1]
            if frame["row"]:
                frame["rows"].append(frame["row"])
            frame["row"] = None
        elif tag == "table" and self._tables:
            frame = self._tables.pop()
            self.tabelas.append((frame["heading"], frame["rows"]))
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._heading_depth:
            self._heading_depth -= 1
            if self._heading_depth == 0:
                self._heading = " ".join(" ".join(self._heading_buffer).split())


def extrair_lineup_html(html: str, fonte: str, *, coletado_em: str) -> list[dict]:
    """Importa HTML recebido por meio permitido, sem buscar paginas na rede.

    So tabelas com colunas de navio e situacao ou berco entram no resultado.
    'data_referencia' vem da tabela; 'coletado_em' nao e data operacional.
    """
    if fonte not in {"suape", "imbituba", "santarem_cdp", "vila_conde_cdp"}:
        raise ValueError("fonte sem parser HTML")
    datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    parser = _HtmlTabelas()
    parser.feed(html)
    records: list[dict] = []
    for heading, rows in parser.tabelas:
        if not rows:
            continue
        header_index = -1
        for i, cols in enumerate(rows[:5]):
            names = [_norm(x) for x in cols]
            if any("navio" in x or "embarcacao" in x for x in names) and any(
                "status" in x or "situacao" in x or "berco" in x or "carga" in x for x in names
            ):
                header_index = i
                break
        if header_index < 0:
            continue
        headers = rows[header_index]
        for cols in rows[header_index + 1:]:
            if len(cols) < len(headers):
                continue
            row = dict(zip(headers, cols))
            navio = _campo(row, "NAVIO", "NOME DA EMBARCAÇÃO")
            if not navio or _norm(navio) in {"navio", "vessel", "a definir", "a confirmar", "teste"}:
                continue
            raw_status = _campo(row, "STATUS") or _campo(row, "SITUAÇÃO") or heading
            status = _status(raw_status)
            flags = []
            if status == "STATUS_NAO_DETERMINADO":
                flags.append("STATUS_A_RECONCILIAR")
            if fonte in {"santarem_cdp", "vila_conde_cdp"}:
                flags.append("CDP_REQUER_RECONCILIACAO")
            value = _toneladas(_campo(row, "TONELADAS", "QUANTIDADE(T)", "QUANTIDADE T"))
            record = {
                "fonte": fonte,
                "porto": FONTES[fonte]["porto"],
                "navio": navio,
                "imo": _campo(row, "IMO/INSCRIÇÃO DA CAPITANIA", "IMO") or None,
                "duv": _campo(row, "DUV", "DOCUMENTO UNICO VIRTUAL") or None,
                "status": status,
                "berco": _campo(row, "BERÇO", "BERÇO DE ATRACAÇÃO") or None,
                "produto_informado": _campo(row, "CARGA", "TIPO DO PRODUTO") or None,
                "toneladas_informadas": value,
                "data_referencia": _campo(row, "DATA", "ATRACAÇÃO", "CHEGADA", "ETA (HORA ESTIMADA DE CHEGADA)") or None,
                "coletado_em": coletado_em,
                "natureza": "INFORMADO_PELA_FONTE",
                "realizado_confirmado": False,
                "flags_qualidade": flags,
            }
            records.append(record)
    return records


def verificar_cdp(registros: Sequence[Mapping], *, corte: str, max_defasagem_dias: int = 30) -> dict:
    """Reprova dados antigos ou sem referencia; nao afirma divergencia sem comparador."""
    d = datetime.fromisoformat(corte).date()
    flags: list[str] = []
    if not registros:
        return {"estado": "SEM_REGISTROS_VALIDOS", "flags": ["SEM_REGISTROS_VALIDOS"]}
    datas = []
    for item in registros:
        raw = str(item.get("data_referencia") or "").strip().split(" ")[0]
        if not raw:
            flags.append("DATA_OPERACIONAL_AUSENTE")
            continue
        try:
            dt = datetime.strptime(raw, "%d/%m/%Y").date()
        except ValueError:
            try:
                dt = datetime.fromisoformat(raw).date()
            except ValueError:
                flags.append("DATA_OPERACIONAL_INVALIDA")
                continue
        datas.append(dt)
    if datas and max(datas) < d - timedelta(days=max_defasagem_dias):
        flags.append("PROGRAMACAO_DESATUALIZADA")
    if not datas:
        flags.append("NENHUMA_DATA_OPERACIONAL_VALIDA")
    return {"estado": "PENDENTE_RECONCILIACAO" if flags else "EXIGE_COMPARACAO_INDEPENDENTE",
            "flags": sorted(set(flags))}


def importar_gpv_csv(texto_csv: str, *, acesso_autorizado: bool, coletado_em: str) -> list[dict]:
    """Apenas arquivos GPV de acesso licito. Nao automatiza login Vale."""
    if not acesso_autorizado:
        raise PermissionError("GPV requer acesso autorizado e termos de uso verificados")
    datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    leitor = csv.DictReader(io.StringIO(texto_csv))
    if not leitor.fieldnames:
        raise ValueError("CSV GPV sem cabecalho")
    saida = []
    for row in leitor:
        navio = _campo(row, "NAVIO", "VESSEL", "NOME DO NAVIO")
        if not navio:
            continue
        saida.append({
            "fonte": "ponta_madeira", "porto": "PONTA_DA_MADEIRA",
            "navio": navio, "imo": _campo(row, "IMO") or None,
            "berco": _campo(row, "BERÇO", "BERTH") or None,
            "status": _status(_campo(row, "STATUS", "SITUAÇÃO")),
            "produto_informado": _campo(row, "CARGA", "PRODUTO") or None,
            "toneladas_informadas": _toneladas(_campo(row, "TONELADAS", "QUANTIDADE T")),
            "data_referencia": _campo(row, "ETA", "ATRACAÇÃO") or None,
            "coletado_em": coletado_em,
            "natureza": "INFORMADO_PELA_FONTE", "realizado_confirmado": False,
            "flags_qualidade": ["VALE_GPV_IMPORTACAO_AUTORIZADA", "NAO_CONFIRMA_REALIZADO"],
        })
    return saida


def _dentro_poligono(lat: float, lon: float, poligono: Sequence[tuple[float, float]]) -> bool:
    if len(poligono) < 3:
        raise ValueError("geocerca sem 3 vertices")
    inside = False
    j = len(poligono) - 1
    for i in range(len(poligono)):
        yi, xi = poligono[i]
        yj, xj = poligono[j]
        if (yi > lat) != (yj > lat):
            at = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < at:
                inside = not inside
        j = i
    return inside


def inferir_presenca_amaggi(eventos: Iterable[Mapping], *, geocerca_terminal: Sequence[tuple[float, float]],
                           min_pontos: int = 3, min_permanencia_minutos: int = 60) -> list[dict]:
    """Inferencia AIS do terminal Amaggi; nunca confirma carga ou operacao.

    Geocerca precisa ser levantada e auditada externamente; sem geocerca
    cadastrada nao ha inferencia. Ponto isolado ou AIS intermitente nao basta.
    """
    por_navio: dict[str, list[tuple[datetime, Mapping]]] = {}
    for evento in eventos:
        imo = str(evento.get("imo") or "").strip()
        mmsi = str(evento.get("mmsi") or "").strip()
        if not re.fullmatch(r"\d{7}", imo) and not re.fullmatch(r"\d{9}", mmsi):
            continue
        try:
            lat, lon = float(evento["latitude"]), float(evento["longitude"])
            momento = datetime.fromisoformat(str(evento["timestamp"]).replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        if momento.tzinfo is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if _dentro_poligono(lat, lon, geocerca_terminal):
            chave = "IMO:" + imo if re.fullmatch(r"\d{7}", imo) else "MMSI:" + mmsi
            por_navio.setdefault(chave, []).append((momento.astimezone(timezone.utc), evento))
    resultados = []
    for chave, pontos in por_navio.items():
        pontos.sort(key=lambda x: x[0])
        distintos = {momento for momento, _ in pontos}
        duracao = (pontos[-1][0] - pontos[0][0]).total_seconds() / 60
        if len(distintos) < min_pontos or duracao < min_permanencia_minutos:
            continue
        resultados.append({
            "fonte": "itacoatiara_amaggi", "porto": "ITACOATIARA_AMAGGI",
            "imo": chave[4:] if chave.startswith("IMO:") else None,
            "mmsi": chave[5:] if chave.startswith("MMSI:") else None,
            "navio": None, "status": "PRESENCA_TERMINAL_PROVAVEL",
            "primeira_posicao": pontos[0][0].isoformat(),
            "ultima_posicao": pontos[-1][0].isoformat(),
            "pontos_ais": len(distintos), "permanencia_minutos_observada": round(duracao, 1),
            "natureza": "INFERIDO_AIS", "realizado_confirmado": False,
            "produto_informado": None, "toneladas_informadas": None,
            "flags_qualidade": ["GEOFENCE_PRECISA_AUDITORIA", "SEM_COMPROVACAO_DE_CARREGAMENTO"],
        })
    return resultados
