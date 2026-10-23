"""ANTT MDF-e/RNTRC: ingestão versionada de exportações agregadas.
Não acessa APIs privadas do Power BI. Importação não autentica origem do CSV.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

PAINEL = "https://www.gov.br/antt/pt-br/assuntos/cargas/dadostrc/movimentacao-de-cargas"
MAX_BYTES = 32 * 1024 * 1024
FIELDS = {
    "competencia": ("competencia", "mes", "mes ano", "periodo", "periodo emissao mdfe"),
    "origem": ("origem", "municipio origem", "rgi origem", "origem municipio", "origem rgi", "codigo origem"),
    "destino": ("destino", "municipio destino", "rgi destino", "destino municipio", "destino rgi", "codigo destino"),
    "toneladas": ("toneladas", "tonelada", "toneladas transportadas", "volume t", "volume toneladas"),
    "ncm": ("ncm", "codigo ncm", "ncm predominante"),
    "categoria": ("categoria transportador", "categoria do transportador", "categoria", "tipo transportador"),
    "mdfes": ("chaves mdfe", "chaves mdf e", "numero mdfe", "n mdfe", "mdfes", "quantidade mdfe"),
    "viagens_min": ("viagens min", "numero de viagens min", "n viagens min", "estimativa viagens min"),
    "tku": ("tku", "toneladas quilometro util"),
}
REQUIRED = ("competencia", "origem", "destino", "toneladas")


class DadosANTTInvalidos(ValueError):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _parse_num(raw: str, *, inteiro: bool = False) -> str | int | None:
    raw = str(raw or "").strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return None
    if not re.fullmatch(r"[+-]?[0-9.,]+", raw):
        raise DadosANTTInvalidos("valor numérico inválido")
    if "." in raw and "," in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        if raw.count(",") > 1:
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        n = Decimal(raw)
    except InvalidOperation as exc:
        raise DadosANTTInvalidos("número inválido") from exc
    if not n.is_finite() or n < 0:
        raise DadosANTTInvalidos("valor negativo/não-finito")
    if inteiro:
        if n != n.to_integral_value():
            raise DadosANTTInvalidos("contagem não-inteira")
        return int(n)
    return format(n, "f")


def _periodo(raw: str) -> str:
    raw = str(raw).strip()
    m = re.fullmatch(r"(20\d\d)-(0[1-9]|1[0-2])(?:-\d{2})?", raw)
    if not m:
        m = re.fullmatch(r"(0[1-9]|1[0-2])/(20\d\d)", raw)
        if not m:
            raise DadosANTTInvalidos("competência deve ser AAAA-MM ou MM/AAAA")
        return f"{m.group(2)}-{m.group(1)}"
    return f"{m.group(1)}-{m.group(2)}"


def _colunas(nomes: list[str]) -> dict[str, str]:
    aliases = {_norm(alias): k for k, al in FIELDS.items() for alias in al}
    result = {}
    for original in nomes:
        k = aliases.get(_norm(original))
        if k:
            if k in result:
                raise DadosANTTInvalidos("colunas equivalentes duplicadas: " + k)
            result[k] = original
    faltam = [x for x in REQUIRED if x not in result]
    if faltam:
        raise DadosANTTInvalidos("colunas obrigatórias ausentes: " + ", ".join(faltam))
    return result


def parse_csv(bruto: bytes, *, nivel: str) -> list[dict]:
    """Matriz OD em um nível geográfico explícito, sem inferir NCM."""
    if nivel not in ("MUNICIPIO", "RGI"):
        raise DadosANTTInvalidos("nível deve ser MUNICIPIO ou RGI")
    if not isinstance(bruto, bytes) or not 1 <= len(bruto) <= MAX_BYTES:
        raise DadosANTTInvalidos("arquivo vazio ou acima do limite")
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DadosANTTInvalidos("CSV deve estar em UTF-8") from exc
    if "\x00" in texto:
        raise DadosANTTInvalidos("CSV contém byte nulo")
    cabecalho = texto.splitlines()[0] if texto.splitlines() else ""
    sep = ";" if cabecalho.count(";") > cabecalho.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=sep, strict=True)
    if not leitor.fieldnames or len(leitor.fieldnames) > 120:
        raise DadosANTTInvalidos("cabeçalho inválido")
    cols = _colunas(leitor.fieldnames)
    saida, chaves = [], set()
    for linha in leitor:
        if len(saida) >= 250_000 or None in linha:
            raise DadosANTTInvalidos("linhas excessivas ou malformadas")
        competencia = _periodo(linha[cols["competencia"]])
        origem = str(linha[cols["origem"]] or "").strip()
        destino = str(linha[cols["destino"]] or "").strip()
        if len(origem) < 2 or len(destino) < 2 or _norm(origem) in ("total", "todos") or _norm(destino) in ("total", "todos"):
            raise DadosANTTInvalidos("origem/destino vazios ou totalizadores")
        if len(origem) > 120 or len(destino) > 120:
            raise DadosANTTInvalidos("localidade muito longa")
        ncm = str(linha.get(cols.get("ncm", ""), "") or "").strip() or None
        if ncm is not None and not re.fullmatch(r"\d{2,8}", ncm):
            raise DadosANTTInvalidos("NCM inválido; não aceitar textos ou totais")
        categoria = str(linha.get(cols.get("categoria", ""), "") or "").strip().upper() or None
        if categoria is not None and categoria not in ("TAC", "ETC", "CTC", "ETC EQUIPARADA A TAC"):
            raise DadosANTTInvalidos("categoria inválida")
        row = dict(
            competencia=competencia, origem=origem, destino=destino, nivel=nivel,
            ncm=ncm, categoria=categoria,
            toneladas=_parse_num(linha[cols["toneladas"]]),
            mdfes=_parse_num(linha.get(cols.get("mdfes", ""), ""), inteiro=True),
            viagens_min=_parse_num(linha.get(cols.get("viagens_min", ""), ""), inteiro=True),
            tku=_parse_num(linha.get(cols.get("tku", ""), "")),
        )
        if row["toneladas"] is None:
            raise DadosANTTInvalidos("toneladas não informadas")
        chave = tuple(row[k] for k in ("competencia", "origem", "destino", "nivel", "ncm", "categoria"))
        if chave in chaves:
            raise DadosANTTInvalidos("duplicata da mesma dimensão; não somar")
        chaves.add(chave)
        saida.append(row)
    if not saida:
        raise DadosANTTInvalidos("arquivo sem observações")
    if len({x["ncm"] is None for x in saida}) > 1 or len({x["categoria"] is None for x in saida}) > 1:
        raise DadosANTTInvalidos("mistura de detalhe e total no mesmo lote")
    return saida


def preparar_bd(bd: sqlite3.Connection) -> None:
    bd.executescript("""
    CREATE TABLE IF NOT EXISTS antt_mdfe_lotes (
      id INTEGER PRIMARY KEY, recorte TEXT NOT NULL, sha256 TEXT NOT NULL,
      arquivo TEXT NOT NULL, coletado_em TEXT NOT NULL, fonte TEXT NOT NULL,
      nivel TEXT NOT NULL, linhas INTEGER NOT NULL, ativo INTEGER NOT NULL,
      UNIQUE(recorte, sha256));
    CREATE TABLE IF NOT EXISTS antt_mdfe_od (
      lote_id INTEGER NOT NULL REFERENCES antt_mdfe_lotes(id),
      competencia TEXT NOT NULL, origem TEXT NOT NULL, destino TEXT NOT NULL,
      nivel TEXT NOT NULL, ncm TEXT, categoria TEXT,
      toneladas TEXT NOT NULL, mdfes INTEGER, viagens_min INTEGER, tku TEXT);
    CREATE INDEX IF NOT EXISTS ix_mdfe_od_filtro
      ON antt_mdfe_od(lote_id, competencia, origem, destino, ncm);
    CREATE UNIQUE INDEX IF NOT EXISTS ix_mdfe_lote_ativo
      ON antt_mdfe_lotes(recorte) WHERE ativo = 1;
    """)


def importar(banco: str | Path, bruto: bytes, *, arquivo: str, recorte: str,
             nivel: str, fonte: str = PAINEL, coletado_em: str | None = None) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{3,100}", recorte):
        raise DadosANTTInvalidos("recorte deve ser ID estável, sem espaços")
    if fonte != PAINEL and not fonte.startswith("https://dados.antt.gov.br/"):
        raise DadosANTTInvalidos("fonte oficial não reconhecida")
    if len(str(arquivo)) > 500:
        raise DadosANTTInvalidos("nome de arquivo inválido")
    rows = parse_csv(bruto, nivel=nivel)
    sha = hashlib.sha256(bruto).hexdigest()
    instante = coletado_em or datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(instante.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise DadosANTTInvalidos("coleta exige fuso horário")
    with sqlite3.connect(banco, timeout=30) as db:
        db.execute("PRAGMA foreign_keys = ON")
        preparar_bd(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        existente = db.execute("SELECT id, ativo FROM antt_mdfe_lotes WHERE recorte=? AND sha256=?",
                               (recorte, sha)).fetchone()
        if existente:
            db.execute("UPDATE antt_mdfe_lotes SET ativo=0 WHERE recorte=?", (recorte,))
            db.execute("UPDATE antt_mdfe_lotes SET ativo=1 WHERE id=?", (existente[0],))
            lote_id, estado = existente[0], "REUTILIZADO_SEM_DUPLICAR"
        else:
            db.execute("UPDATE antt_mdfe_lotes SET ativo=0 WHERE recorte=?", (recorte,))
            cur = db.execute(
                "INSERT INTO antt_mdfe_lotes (recorte,sha256,arquivo,coletado_em,fonte,nivel,linhas,ativo) "
                "VALUES (?,?,?,?,?,?,?,1)", (recorte, sha, arquivo, instante, fonte, nivel, len(rows)))
            lote_id = cur.lastrowid
            db.executemany(
                """INSERT INTO antt_mdfe_od
                (lote_id,competencia,origem,destino,nivel,ncm,categoria,toneladas,mdfes,viagens_min,tku)
                VALUES (:lote_id,:competencia,:origem,:destino,:nivel,:ncm,:categoria,:toneladas,:mdfes,:viagens_min,:tku)""",
                [{**r, "lote_id": lote_id} for r in rows])
            estado = "NOVA_REVISAO_ARMAZENADA"
        db.commit()
    return {
        "estado": estado, "recorte": recorte, "lote_id": lote_id, "linhas": len(rows),
        "sha256": sha, "nivel": nivel,
        "competencia_inicial": min(r["competencia"] for r in rows),
        "competencia_final": max(r["competencia"] for r in rows),
        "qualidade": "IMPORTADO_NAO_HOMOLOGADO",
        "observacao": "CSV ainda requer prova de origem; NCM amostral, não total do transporte",
    }


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def baixar_csv_oficial(url: str, *, opener=None) -> bytes:
    """GET limitado apenas para URL CSV previamente identificada da ANTT."""
    u = urlsplit(url)
    if (
        u.scheme != "https" or u.hostname != "dados.antt.gov.br"
        or u.username or u.password or u.query or u.fragment
        or u.port not in (None, 443)
        or not re.fullmatch(r"/((tr/)?dataset)/[^/]+/resource/[^/]+/download/[^/]+\.csv", u.path, re.I)
    ):
        raise DadosANTTInvalidos("URL CSV oficial ANTT não homologada")
    req = Request(url, headers={
        "Accept": "text/csv,application/csv",
        "User-Agent": "NIVON/0.1 pesquisa nao comercial",
    })
    with (opener or build_opener(_SemRedirecionamento())).open(req, timeout=25) as response:
        mime = str(response.headers.get("Content-Type", "")).split(";")[0].lower().strip()
        if response.status != 200 or response.geturl() != url or mime not in ("text/csv", "application/csv", "text/plain"):
            raise DadosANTTInvalidos("resposta não é CSV direto oficial")
        conteudo = response.read(MAX_BYTES + 1)
        if not 0 < len(conteudo) <= MAX_BYTES:
            raise DadosANTTInvalidos("CSV vazio ou acima do limite")
        return conteudo


def resumo(banco: str | Path, recorte: str, competencia: str) -> dict:
    with sqlite3.connect(banco) as db:
        preparar_bd(db)
        lote = db.execute(
            "SELECT id,coletado_em,linhas FROM antt_mdfe_lotes WHERE recorte=? AND ativo=1",
            (recorte,)).fetchone()
        if not lote:
            return {"estado": "SEM_DADOS", "recorte": recorte}
        linhas = db.execute(
            "SELECT toneladas, ncm, mdfes FROM antt_mdfe_od WHERE lote_id=? AND competencia=?",
            (lote[0], _periodo(competencia))).fetchall()
        if not linhas:
            return {"estado": "COMPETENCIA_AUSENTE", "recorte": recorte, "competencia": competencia}
        return {
            "estado": "RECORTE_IMPORTADO_NAO_HOMOLOGADO", "recorte": recorte,
            "competencia": competencia,
            "toneladas_no_recorte": format(sum(Decimal(x[0]) for x in linhas), "f"),
            "mdfes_no_recorte": sum(x[2] for x in linhas) if all(x[2] is not None for x in linhas) else None,
            "amostra_ncm": any(x[1] is not None for x in linhas),
            "linhas": len(linhas), "coletado_em": lote[1],
        }
