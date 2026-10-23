"""NIVON: referencias ANTAQ 2025 e leitura do CSV de producao OD ANTT/SIADE.

Nao executa rede ou grava no banco durante import. TKU ferroviario bruto
permanece pendente de conciliacao contra as series anuais oficiais.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ErroTransporte(ValueError):
    pass


_CKAN = "https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/resource/"
_ARQUIVOS_ANTT = {
    2025: _CKAN + "d7263808-bd77-4153-9910-49e041d73b21/download/producao_origem_destino_2025.csv",
    2026: _CKAN + "c2854ec9-1cc5-4554-a1ae-96c5f37b5df6/download/producao_origem_destino_2026.csv",
}
CAMPOS_ANTT = ("Mes_Ano", "Ferrovia", "Mercadoria_ANTT", "Estacao_Origem",
               "UF_Origem", "Estacao_Destino", "UF_Destino", "TU", "TKU")
FONTE_ANTT_HISTORICO = "https://www.gov.br/antt/pt-br/assuntos/ferrovias/dados-de-producao-do-transporte-de-carga-origem-destino"
FONTE_ANTAQ_ANUARIO = "https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/Anuario2025.pdf"
FONTE_ANTAQ_TKU = "https://www.gov.br/antaq/pt-br/central-de-conteudos/estudos-e-pesquisas-da-antaq-1/20260816_Relatorio_TKU_2025_V2___PAULO_PERNI___NAO_DIAGRAMADO.pdf"
FONTE_MPOR_VIAS = "https://www.gov.br/portos-e-aeroportos/pt-br/assuntos/noticias/2026/05/mpor-faz-balanco-do-primeiro-bienio-da-secretaria-nacional-de-hidrovias-e-navegacao"


@dataclass(frozen=True)
class MetadadosFonte:
    origem: str
    arquivo_sha256: str
    referencia_maxima: str | None
    registros: int
    estado: str
    observacao: str


def link_antt(ano: int) -> str:
    if type(ano) is not int or ano not in _ARQUIVOS_ANTT:
        raise ErroTransporte("ano ANTT sem URL CSV oficialmente verificada")
    return _ARQUIVOS_ANTT[ano]


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def baixar_antt(ano: int, *, habilitar_rede: bool = False, transporte=None, timeout: int = 20) -> bytes:
    """Download somente sob opt-in, com host fixo, sem seguir redirects."""
    url = link_antt(ano)
    if not habilitar_rede:
        raise PermissionError("download ANTT exige habilitar_rede=True")
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ErroTransporte("timeout fora da faixa permitida")
    req = Request(url, method="GET", headers={"Accept": "text/csv", "User-Agent": "NIVON-dados-publicos/1"})
    opener = transporte or build_opener(_SemRedirecionamento)
    try:
        with opener.open(req, timeout=timeout) as resp:
            if getattr(resp, "status", None) != 200:
                raise ErroTransporte("ANTT nao retornou status HTTP 200")
            raw = resp.read(16_000_001)
    except ErroTransporte:
        raise
    except Exception:
        raise ErroTransporte("download ANTT nao verificado") from None
    if not 1 <= len(raw) <= 16_000_000:
        raise ErroTransporte("CSV ANTT fora do tamanho permitido")
    return raw


def _numero(valor: str) -> Decimal:
    s = valor.strip().replace("\u00a0", "")
    if not s or s.startswith("+") or "e" in s.lower():
        raise ErroTransporte("TU/TKU ausente ou formato nao aprovado")
    if "," in s:
        if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:\.\d{3})+),\d+", s):
            raise ErroTransporte("TU/TKU decimal brasileiro ambiguo")
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
        # No SIADE o ponto separa milhares: 33.420 = 33420 t.
        s = s.replace(".", "")
    elif not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        raise ErroTransporte("TU/TKU numerico invalido")
    try:
        x = Decimal(s)
    except InvalidOperation as exc:
        raise ErroTransporte("TU/TKU invalido") from exc
    if not x.is_finite() or x < 0:
        raise ErroTransporte("TU/TKU negativo ou nao finito")
    return x


def _competencia(valor: str, ano: int) -> str:
    """SIADE documenta MM_AA; aceitar tambem variacoes ISO se houver."""
    v = valor.strip()
    m = re.fullmatch(r"(20\d{2})[-/](0?[1-9]|1[0-2])", v)
    if m:
        y, mes = int(m[1]), int(m[2])
    else:
        m = re.fullmatch(r"(20\d{2})(0[1-9]|1[0-2])", v)
        if m:
            y, mes = int(m[1]), int(m[2])
        else:
            m = re.fullmatch(r"(0?[1-9]|1[0-2])[-/_](20\d{2}|\d{2})", v)
            if not m:
                raise ErroTransporte("Mes_Ano nao reconhecido; validar arquivo real")
            mes, y = int(m[1]), int(m[2])
            if y < 100:
                y += 2000
    if y != ano:
        raise ErroTransporte("competencia fora do ano declarado")
    return f"{y:04d}-{mes:02d}"

def interpretar_csv_antt(raw: bytes, *, ano: int, coleta_utc: str,
                         fonte_url: str | None = None) -> tuple[list[dict], MetadadosFonte]:
    """Importa CSV OD; fonte_url validada permite recursos anteriores a 2025."""
    if fonte_url is None:
        link = link_antt(ano)
    else:
        from urllib.parse import urlsplit
        part = urlsplit(fonte_url)
        pat = r"/dataset/438a5184-09db-49a3-88c8-0bad418b4409/resource/[0-9a-f-]{36}/download/producao_origem_destino_(20[0-9]{2})\.csv"
        m = re.fullmatch(pat, part.path)
        if (part.scheme != "https" or part.netloc != "dados.antt.gov.br"
                or part.query or part.fragment or not m or int(m[1]) != ano):
            raise ErroTransporte("fonte_url anual ANTT invalida")
        link = fonte_url
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 16_000_000:
        raise ErroTransporte("CSV ausente ou excede limite")
    if not isinstance(coleta_utc, str) or not re.fullmatch(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ", coleta_utc):
        raise ErroTransporte("coleta_utc deve ser ISO UTC")
    # A base SIADE pode usar codificacao legada. O schema valida o decode.
    for codec in ("utf-8-sig", "cp1252"):
        try:
            txt = raw.decode(codec)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErroTransporte("CSV ANTT com codificacao desconhecida")
    if "\x00" in txt:
        raise ErroTransporte("CSV contem byte nulo")
    separador = ";" if txt.splitlines()[0].count(";") >= 8 else ","
    reader = csv.DictReader(io.StringIO(txt), delimiter=separador)
    cabecalho = tuple((x or "").strip() for x in (reader.fieldnames or []))
    if len(set(cabecalho)) != len(cabecalho) or set(cabecalho) != set(CAMPOS_ANTT):
        raise ErroTransporte("schema ANTT inesperado")
    saida = []
    ultimo_mes = None
    for linha in reader:
        if len(saida) >= 200_000 or None in linha:
            raise ErroTransporte("linha CSV inesperada")
        linha = {str(k).strip(): (str(v).strip() if v is not None else "") for k,v in linha.items()}
        if not all(linha.get(c) for c in CAMPOS_ANTT):
            raise ErroTransporte("campo obrigatorio vazio")
        mes = _competencia(linha["Mes_Ano"], ano)
        uf_o, uf_d = linha["UF_Origem"].upper(), linha["UF_Destino"].upper()
        if not (re.fullmatch(r"[A-Z]{2}", uf_o) and re.fullmatch(r"[A-Z]{2}", uf_d)):
            raise ErroTransporte("UF OD invalida")
        tu, tku = _numero(linha["TU"]), _numero(linha["TKU"])
        anomalia_tu_tku = (tu == 0) != (tku == 0)
        # Fontes historicas podem ter medidas divergentes; preservar como
        # observado declarado e sinalizar, sem fabricar valor ou interromper toda a serie.
        saida.append({
            "fonte": "ANTT_SIADE_ORIGEM_DESTINO", "ano": ano, "competencia": mes,
            "ferrovia": linha["Ferrovia"], "mercadoria": linha["Mercadoria_ANTT"],
            "estacao_origem": linha["Estacao_Origem"], "uf_origem": uf_o,
            "estacao_destino": linha["Estacao_Destino"], "uf_destino": uf_d,
            "toneladas_uteis": str(tu), "tku_raw": str(tku),
            "unidade_tku_confirmada": False, "anomalia_tu_tku": anomalia_tu_tku,
            "natureza_tu": "OBSERVADO_DECLARADO",
            "natureza_tku": "OBSERVADO_DECLARADO_A_CONCILIAR",
            "data_coleta_utc": coleta_utc, "fonte_url": link,
        })
        if ultimo_mes is None or mes > ultimo_mes:
            ultimo_mes = mes
    if not saida:
        raise ErroTransporte("CSV sem registros")
    return saida, MetadadosFonte(
        origem=link, arquivo_sha256=hashlib.sha256(raw).hexdigest(),
        referencia_maxima=ultimo_mes, registros=len(saida),
        estado="PARSEADO_NAO_HOMOLOGADO",
        observacao="conciliar TU/TKU com anuarios ANTT antes de publicar",
    )


# Indicadores de 2025 publicados por orgaos oficiais. NAO e ingestao SDP em tempo real.
# Os dois recortes de toneladas sao SOBREPOSTOS e nao podem ser somados.
RESUMOS_ANTAQ_2025 = (
    {"recorte": "NAVEGACAO_INTERIOR_ESTRITA", "metrica": "TONELADAS",
     "valor": "91300000", "precisao": "APROXIMADA_1_CASA_MILHAO",
     "natureza": "OBSERVADO_AGREGADO", "fonte": FONTE_ANTAQ_ANUARIO},
    {"recorte": "TODAS_VIAS_INTERIORES", "metrica": "TONELADAS",
     "valor": "145000000", "precisao": "APROXIMADA_MILHAO",
     "natureza": "OBSERVADO_AGREGADO", "fonte": FONTE_MPOR_VIAS},
    {"recorte": "NAVEGACAO_INTERIOR_ESTRITA", "metrica": "TKU",
     "valor": "42703889135", "precisao": "RELATORIO",
     "natureza": "ESTIMADO_ANTAQ", "fonte": FONTE_ANTAQ_TKU},
)
TKU_INTERIOR_2025 = {
    "BAIXO_AMAZONAS": 12623154067, "MADEIRA": 12806337334,
    "TAPAJOS": 4761179933, "PARAGUAI": 4496006213,
    "BAIXO_TOCANTINS": 2392831077, "AMAZONAS": 2151824329,
    "PARANA_TIETE": 1415051088,
}


def conferir_tku_hidrovias_2025() -> dict:
    total = 42_703_889_135
    if sum(TKU_INTERIOR_2025.values()) > total:
        raise ErroTransporte("subset de hidrovias excede o total ANTAQ")
    return {
        "ano": 2025, "metrica": "TKU", "natureza": "ESTIMADO_ANTAQ",
        "tku_total": total, "tku_por_hidrovia_subconjunto": TKU_INTERIOR_2025.copy(),
        "tku_demais": total - sum(TKU_INTERIOR_2025.values()),
        "fonte": FONTE_ANTAQ_TKU,
        "metodologia": "cargas SDP x distancias estimadas ANTAQ",
    }
