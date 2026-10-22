"""Coleta autorizada de PTAX do Banco Central via API OData.

Não consulta widgets do Notícias Agrícolas. Não inventa hora de publicação.
Histórico e versões ficam em SQLite local; produção requer storage durável separado.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ORIGEM = "Banco Central do Brasil / PTAX"
DOC_OFICIAL = "https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios"
LICENCA = "ODbL (verificar exigências de atribuição e compartilhamento pela mesma licença)"
URL_BASE = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
MOEDAS = {"USD", "EUR"}
DATA_INICIAL_PUBLICA = {"USD": date(1984, 11, 28), "EUR": date(2002, 1, 2)}
WIDGET_REFERENCIA = 232  # vínculo editorial; NÃO é a fonte de coleta
PAGINA_DIAS = 31


def url_ptax(moeda: str, inicio: date, fim: date) -> str:
    """URLs somente no host oficial; formato de datas documentado pelo BCB."""
    moeda = moeda.upper()
    if moeda not in MOEDAS or inicio > fim:
        raise ValueError("Moeda ou intervalo inválido")
    args = {"@dataInicial": f"'{inicio:%m-%d-%Y}'",
            "@dataFinalCotacao": f"'{fim:%m-%d-%Y}'", "$format": "json", "$top": "5000"}
    if moeda == "USD":
        recurso = "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    else:
        recurso = "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        args["@moeda"] = f"'{moeda}'"
    return URL_BASE + recurso + "?" + urlencode(args)


def obter_json(url: str) -> dict:
    """Transporte limitado ao host e prefixo oficiais; timeout e retries limitados."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "olinda.bcb.gov.br" or not url.startswith(URL_BASE):
        raise ValueError("Host não autorizado")
    ultimo = None
    for tentativa in range(3):
        try:
            req = Request(url, headers={"Accept": "application/json",
                                        "User-Agent": "NIVON-PTAX/0.1 (dados-abertos)"})
            with urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                conteudo = resp.read(8_000_001)
                if len(conteudo) > 8_000_000:
                    raise ValueError("Resposta acima do limite")
                return json.loads(conteudo.decode("utf-8"))
        except (OSError, RuntimeError) as exc:
            ultimo = exc
            if tentativa < 2:
                time.sleep(1 + tentativa * 2)
    raise RuntimeError("Falha ao consultar PTAX") from ultimo


def janelas(inicio: date, fim: date):
    atual = inicio
    while atual <= fim:
        termino = min(fim, atual + timedelta(days=PAGINA_DIAS - 1))
        yield atual, termino
        atual = termino + timedelta(days=1)


def iniciar_banco(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS ptax_observacoes (
        chave TEXT NOT NULL,
        versao TEXT NOT NULL,
        moeda TEXT NOT NULL,
        data_referencia TEXT NOT NULL,
        data_hora_cotacao_origem TEXT NOT NULL,
        tipo_boletim TEXT NOT NULL,
        cotacao_compra TEXT NOT NULL,
        cotacao_venda TEXT NOT NULL,
        unidade TEXT NOT NULL,
        competencia TEXT NOT NULL,
        data_publicacao TEXT,
        data_coleta TEXT NOT NULL,
        ultima_verificacao_em TEXT NOT NULL,
        fonte_original TEXT NOT NULL,
        licenca TEXT NOT NULL,
        PRIMARY KEY(chave, versao)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ptax_data ON ptax_observacoes(moeda, data_referencia)")
    conn.execute("""CREATE TABLE IF NOT EXISTS ptax_execucoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inicio TEXT NOT NULL,
        fim TEXT NOT NULL,
        moeda TEXT NOT NULL,
        coleta_em TEXT NOT NULL,
        registros_recebidos INTEGER NOT NULL,
        novos_ou_revisados INTEGER NOT NULL,
        registros_iguais INTEGER NOT NULL,
        estado TEXT NOT NULL
    )""")


def decimal_positivo(valor) -> str:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str, Decimal)):
        raise ValueError("Cotação numérica inválida")
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as e:
        raise ValueError("Cotação inválida") from e
    if not numero.is_finite() or numero <= 0:
        raise ValueError("Cotação precisa ser finita e positiva")
    return format(numero, "f")


def normalizar(registro: dict, moeda: str, inicio: date, fim: date, coleta_em: str) -> dict:
    if not isinstance(registro, dict):
        raise ValueError("Registro PTAX não é objeto")
    try:
        data_hora = registro["dataHoraCotacao"]
        # O endpoint oficial CotacaoDolarPeriodo NÃO publica tipoBoletim.
        # A distinção precisa estar explícita: não inventar rótulo Fechamento.
        tipo = registro.get("tipoBoletim", "COTACAO_DOLAR_DIARIA" if moeda == "USD" else None)
        compra = decimal_positivo(registro["cotacaoCompra"])
        venda = decimal_positivo(registro["cotacaoVenda"])
    except KeyError as e:
        raise ValueError(f"Campo obrigatório ausente: {e}") from e
    if not isinstance(data_hora, str) or not isinstance(tipo, str) or not tipo.strip():
        raise ValueError("Data/hora ou tipo de boletim inválido")
    try:
        dt = datetime.fromisoformat(data_hora.replace(" ", "T"))
    except ValueError as e:
        raise ValueError("Data/hora PTAX inválida") from e
    if not inicio <= dt.date() <= fim:
        raise ValueError("Data de cotação fora do período requisitado")
    # A API apresenta o horário de COTAÇÃO, não um timestamp de publicação.
    # Não atribuir zona horária onde a fonte não a fornece.
    return {"moeda": moeda, "data_referencia": dt.date().isoformat(),
            "data_hora_cotacao_origem": data_hora,
            "tipo_boletim": tipo, "cotacao_compra": compra, "cotacao_venda": venda,
            "unidade": f"BRL/{moeda}", "competencia": dt.strftime("%Y-%m"),
            "data_publicacao": None, "data_coleta": coleta_em,
            "ultima_verificacao_em": coleta_em, "fonte_original": ORIGEM, "licenca": LICENCA}


def obter_ultimo_dia(conn: sqlite3.Connection, moeda: str) -> date | None:
    iniciar_banco(conn)
    valor = conn.execute("SELECT max(data_referencia) FROM ptax_observacoes WHERE moeda = ?", (moeda,)).fetchone()[0]
    return date.fromisoformat(valor) if valor else None


def janela_incremental(conn: sqlite3.Connection, moeda: str, hoje: date) -> tuple[date, date]:
    anterior = obter_ultimo_dia(conn, moeda)
    if anterior is None:
        return max(DATA_INICIAL_PUBLICA[moeda], hoje - timedelta(days=31)), hoje
    inicio = max(DATA_INICIAL_PUBLICA[moeda], anterior - timedelta(days=3))
    return inicio, min(hoje, inicio + timedelta(days=179))


def sincronizar(banco: Path | str, moeda: str = "USD", *,
                inicio: date | None = None, fim: date | None = None,
                transporte=None, hoje: date | None = None,
                permitir_periodo_longo: bool = False) -> dict:
    moeda = moeda.upper()
    if moeda not in MOEDAS:
        raise ValueError("Moeda não suportada")
    hoje = hoje or date.today()
    if (inicio is None) != (fim is None):
        raise ValueError("Informe início e fim juntos")
    with sqlite3.connect(str(banco)) as conn:
        iniciar_banco(conn)
        if inicio is None:
            inicio, fim = janela_incremental(conn, moeda, hoje)
        if inicio > fim or inicio < DATA_INICIAL_PUBLICA[moeda] or fim > hoje:
            raise ValueError("Período fora da cobertura informada ou no futuro")
        if (fim - inicio).days > 365 and not permitir_periodo_longo:
            raise ValueError("Período > 366 dias exige confirmação explícita")
        agora = datetime.now(timezone.utc).isoformat()
        dados = []
        consultar = transporte or obter_json
        for a, b in janelas(inicio, fim):
            resposta = consultar(url_ptax(moeda, a, b))
            if not isinstance(resposta, dict) or not isinstance(resposta.get("value"), list):
                raise ValueError("Formato de resposta OData inesperado")
            if any(k in resposta for k in ("@odata.nextLink", "odata.nextLink")) or len(resposta["value"]) >= 5000:
                raise ValueError("Paginação OData pendente: não aceitar histórico truncado")
            dados.extend(normalizar(item, moeda, a, b, agora) for item in resposta["value"])
        novos = 0
        campos = ("moeda", "data_referencia", "data_hora_cotacao_origem",
                  "tipo_boletim", "cotacao_compra", "cotacao_venda", "unidade",
                  "competencia", "data_publicacao", "data_coleta",
                  "ultima_verificacao_em", "fonte_original", "licenca")
        for row in dados:
            identificacao = [row[k] for k in ("moeda", "data_referencia",
                                            "data_hora_cotacao_origem", "tipo_boletim")]
            precos = [row["cotacao_compra"], row["cotacao_venda"]]
            chave = hashlib.sha256(json.dumps(identificacao, ensure_ascii=False).encode()).hexdigest()
            versao = hashlib.sha256(json.dumps(precos).encode()).hexdigest()
            valores = [chave, versao] + [row[k] for k in campos]
            sql = ("INSERT OR IGNORE INTO ptax_observacoes (chave,versao,"
                   + ",".join(campos) + ") VALUES (" + ",".join("?" for _ in valores) + ")")
            cur = conn.execute(sql, valores)
            novos += cur.rowcount
            if cur.rowcount == 0:
                conn.execute("UPDATE ptax_observacoes SET ultima_verificacao_em=? "
                             "WHERE chave=? AND versao=?", (agora, chave, versao))
        conn.execute("""INSERT INTO ptax_execucoes
            (inicio, fim, moeda, coleta_em, registros_recebidos, novos_ou_revisados,
             registros_iguais, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (inicio.isoformat(), fim.isoformat(), moeda, agora,
             len(dados), novos, len(dados) - novos,
             "SEM_COTACAO_NO_PERIODO" if not dados else "SUCESSO"))
        return {"moeda": moeda, "inicio": inicio.isoformat(), "fim": fim.isoformat(),
                "recebidos": len(dados), "novos_ou_revisados": novos,
                "repetidos": len(dados) - novos,
                "estado": "SEM_COTACAO_NO_PERIODO" if not dados else "SUCESSO",
                "fonte": ORIGEM, "coleta_em_utc": agora,
                "armazenamento": "SQLite local; NÃO é banco de produção"}


def main() -> None:
    parser = argparse.ArgumentParser(description="NIVON — PTAX oficial, coleta incremental")
    parser.add_argument("--banco", type=Path, required=True, help="SQLite fora do repositório")
    parser.add_argument("--moeda", choices=["USD", "EUR", "AMBAS"], default="AMBAS")
    parser.add_argument("--inicio", type=date.fromisoformat)
    parser.add_argument("--fim", type=date.fromisoformat)
    parser.add_argument("--permitir-periodo-longo", action="store_true")
    args = parser.parse_args()
    for moeda in (["USD", "EUR"] if args.moeda == "AMBAS" else [args.moeda]):
        saida = sincronizar(args.banco, moeda, inicio=args.inicio, fim=args.fim,
                           permitir_periodo_longo=args.permitir_periodo_longo)
        print(json.dumps(saida, ensure_ascii=False))


if __name__ == "__main__":
    main()
