"""ANTAQ Estatístico Aquaviário: ingestão OFFLINE versionada de ZIPs oficiais.

Não baixa arquivos, não contorna WAF e não declara line-up atual.
Base histórica mensal tem granularidade de CARGA por ATRACAÇÃO, não de navio programado.
Formatos: <ANO>.zip com <ANO>Atracacao.txt/<ANO>Carga.txt; Mercadoria.zip.
A edição é preservada por SHA-256 dos dois ZIPs, evitando sobrescrever revisões.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .lineup_nacional import instante


class ErroAntaq(ValueError):
    pass


MAX_ZIP_BYTES = 240_000_000
MAX_MEMBRO_BYTES = 1_500_000_000
MAX_ARQUIVOS = 30
MAX_CSV_LINHAS = 6_000_000
COLUNAS = {
    "atracacao": {"IDAtracacao", "Porto Atracação", "Terminal",
                   "Data Atracação", "Ano", "Mes", "SGUF"},
    "carga": {"IDCarga", "IDAtracacao", "CDMercadoria", "Sentido",
               "VLPesoCargaBruta"},
    "mercadoria": {"CDMercadoria", "Nomenclatura Simplificada Mercadoria"},
}
MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _carregar_zip(payload: bytes, esperado: str) -> ZipFile:
    if (not isinstance(payload, bytes) or len(payload) > MAX_ZIP_BYTES
            or not payload.startswith(b"PK\x03\x04")):
        raise ErroAntaq("arquivo ZIP ANTAQ inválido ou acima do limite")
    try:
        z = ZipFile(io.BytesIO(payload))
    except BadZipFile as exc:
        raise ErroAntaq("arquivo ZIP corrompido") from exc
    infos = z.infolist()
    if (len(infos) > MAX_ARQUIVOS or
            sum(x.file_size for x in infos) > MAX_ARQUIVOS * MAX_MEMBRO_BYTES or
            any(x.file_size > MAX_MEMBRO_BYTES or x.flag_bits & 1 for x in infos)):
        z.close()
        raise ErroAntaq("ZIP malicioso: expansão, criptografia ou quantidade excessiva")
    if esperado not in z.namelist():
        z.close()
        raise ErroAntaq("arquivo ANTAQ requerido não encontrado: " + esperado)
    if z.getinfo(esperado).file_size > MAX_MEMBRO_BYTES:
        z.close()
        raise ErroAntaq("tabela ANTAQ excede limite")
    return z


@contextmanager
def _tabela(z: ZipFile, nome: str, campos: set[str]):
    with z.open(nome) as data, io.TextIOWrapper(data, encoding="utf-8-sig",
                                               errors="strict", newline="") as texto:
        rdr = csv.DictReader(texto, delimiter=";")
        header = rdr.fieldnames
        if not header:
            raise ErroAntaq("CSV ANTAQ vazio")
        canon = [x.strip() for x in header]
        if len(canon) != len(set(canon)) or not campos.issubset(set(canon)):
            raise ErroAntaq("layout ANTAQ incompatível em " + nome)
        # Remover espaços nas chaves sem reescrever valores.
        def registros():
            for idx, row in enumerate(rdr, start=1):
                if idx > MAX_CSV_LINHAS:
                    raise ErroAntaq("CSV ANTAQ maior que limite operacional")
                if None in row or any(k is None for k in row):
                    raise ErroAntaq("CSV ANTAQ com colunas sobrando")
                yield {k.strip(): v for k, v in row.items()}
        yield registros()


def _codigo(valor: object) -> str:
    s = str(valor or "").strip()
    if not re.fullmatch(r"[0-9A-Za-z-]{1,45}", s):
        raise ErroAntaq("ID ANTAQ faltante ou inválido")
    return s


def _valor_ptbr(valor: object) -> str:
    raw = str(valor or "").strip()
    if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]{3})*(?:,[0-9]+)?", raw):
        raise ErroAntaq("peso ANTAQ não numérico em formato PT-BR")
    try:
        dec = Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ErroAntaq("peso bruto inconsistente") from exc
    if not dec.is_finite() or dec < 0 or dec > Decimal("50000000"):
        raise ErroAntaq("peso bruto fora da faixa esperada")
    return str(dec)


def _mes(text: str) -> int:
    s = str(text or "").strip().lower()
    try:
        n = int(s)
    except ValueError:
        n = MESES.get(s, 0)
    if not 1 <= n <= 12:
        raise ErroAntaq("mês ANTAQ inválido")
    return n


def _data_atracacao(text: str) -> str:
    s = str(text or "").strip()
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, pattern).date().isoformat()
        except ValueError:
            pass
    raise ErroAntaq("data de atracação não corresponde ao formato publicado")


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS antaq_edicoes
                  (edicao TEXT PRIMARY KEY, ano INTEGER NOT NULL, capturado_em TEXT NOT NULL,
                   status TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS antaq_atracacoes
                  (edicao TEXT NOT NULL, ida TEXT NOT NULL, porto TEXT NOT NULL,
                   terminal TEXT, uf TEXT NOT NULL, data_atracacao TEXT NOT NULL,
                   PRIMARY KEY(edicao,ida))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS antaq_mercadorias
                  (edicao TEXT NOT NULL, codigo TEXT NOT NULL, nome TEXT NOT NULL,
                   PRIMARY KEY(edicao,codigo))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS antaq_cargas
                  (edicao TEXT NOT NULL, idc TEXT NOT NULL, ida TEXT NOT NULL,
                   codigo TEXT NOT NULL, sentido TEXT NOT NULL,
                   peso_ton TEXT NOT NULL,
                   PRIMARY KEY(edicao,idc))""")


def importar_arquivos(ano_zip: bytes, mercadoria_zip: bytes, *, ano: int,
                      coletado_em: str, conexao: sqlite3.Connection) -> dict:
    """Importa ZIPs autorizados pré-baixados. Não faz consulta HTTP.

    Exige integridade das chaves de atracação/mercadoria e mantém revisões de ZIP
    por edição SHA. Um CSV com layout inesperado falha e desfaz a transação.
    """
    ts = instante(coletado_em)
    if isinstance(ano, bool) or not isinstance(ano, int) or not 2010 <= ano <= ts.year:
        raise ErroAntaq("ano ANTAQ fora do histórico permitido")
    digest = hashlib.sha256()
    for payload in (ano_zip, mercadoria_zip):
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    edicao = digest.hexdigest()
    if conexao.in_transaction:
        raise ErroAntaq("conexão com transação externa ativa: usar conexão isolada")
    with _carregar_zip(ano_zip, str(ano) + "Atracacao.txt") as a, _carregar_zip(
        mercadoria_zip, "Mercadoria.txt"
    ) as m:
        if str(ano) + "Carga.txt" not in a.namelist():
            raise ErroAntaq("ZIP anual sem arquivo Carga")
        _schema(conexao)
        if conexao.in_transaction:
            conexao.commit()  # schema DDL concluído antes do lote (sem dados).
        conexao.execute("BEGIN")
        try:
            if conexao.execute("SELECT 1 FROM antaq_edicoes WHERE edicao=?", (edicao,)).fetchone():
                conexao.rollback()
                return {"estado": "EDICAO_JA_IMPORTADA", "ano": ano, "edicao_sha256": edicao,
                        "publicavel": False}
            nmerc = natra = ncarga = 0
            with _tabela(m, "Mercadoria.txt", COLUNAS["mercadoria"]) as rows:
                for r in rows:
                    codigo = _codigo(r["CDMercadoria"])
                    nome = (r["Nomenclatura Simplificada Mercadoria"] or "").strip()
                    if not nome or len(nome)>180:
                        raise ErroAntaq("mercadoria não identificada")
                    conexao.execute("INSERT INTO antaq_mercadorias VALUES (?,?,?)",
                                   (edicao, codigo, nome))
                    nmerc += 1
            with _tabela(a, str(ano)+"Atracacao.txt", COLUNAS["atracacao"]) as rows:
                for r in rows:
                    dia = _data_atracacao(r["Data Atracação"])
                    if int(r["Ano"]) != ano or _mes(r["Mes"]) != int(dia[5:7]) or int(dia[:4]) != ano:
                        raise ErroAntaq("ano/mês da atracação divergente")
                    porto = (r["Porto Atracação"] or "").strip()
                    terminal = (r["Terminal"] or "").strip()
                    uf = (r["SGUF"] or "").strip().upper()
                    if not porto or len(porto)>160 or not re.fullmatch("[A-Z]{2}",uf):
                        raise ErroAntaq("porto ou UF inválidos")
                    conexao.execute("INSERT INTO antaq_atracacoes VALUES (?,?,?,?,?,?)",
                                   (edicao,_codigo(r["IDAtracacao"]),porto,terminal,uf,dia))
                    natra += 1
            with _tabela(a, str(ano)+"Carga.txt", COLUNAS["carga"]) as rows:
                for r in rows:
                    sentido = (r["Sentido"] or "").strip()
                    if sentido not in ("Embarcados","Desembarcados"):
                        raise ErroAntaq("sentido da carga desconhecido")
                    ida = _codigo(r["IDAtracacao"])
                    merc = _codigo(r["CDMercadoria"])
                    if not conexao.execute(
                        "SELECT 1 FROM antaq_atracacoes WHERE edicao=? AND ida=?", (edicao, ida)
                    ).fetchone() or not conexao.execute(
                        "SELECT 1 FROM antaq_mercadorias WHERE edicao=? AND codigo=?", (edicao, merc)
                    ).fetchone():
                        raise ErroAntaq("carga sem chave de atracação/mercadoria conciliável")
                    conexao.execute("INSERT INTO antaq_cargas VALUES (?,?,?,?,?,?)",
                                   (edicao,_codigo(r["IDCarga"]),ida,merc,sentido,
                                    _valor_ptbr(r["VLPesoCargaBruta"])))
                    ncarga += 1
            if not nmerc or not natra or not ncarga:
                raise ErroAntaq("tabelas ANTAQ vazias, não criar movimentação zero")
            conexao.execute("INSERT INTO antaq_edicoes VALUES (?,?,?,?)",
                           (edicao,ano,ts.isoformat(),"HISTORICO_OBSERVADO_SEM_LICENCA_PUBLICACAO"))
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
    return {"estado": "IMPORTADO_OFFLINE", "ano": ano, "edicao_sha256": edicao,
            "atracacoes": natra, "cargas": ncarga, "mercadorias": nmerc,
            "publicavel": False, "tipo": "MOVIMENTACAO_REALIZADA_NAO_LINEUP",
            "nota": "Competência do evento não prova atualidade nem licença de redistribuição."}


def resumo_por_porto(conexao: sqlite3.Connection, edicao: str) -> list[dict]:
    if not re.fullmatch(r"[a-f0-9]{64}", str(edicao)):
        raise ErroAntaq("identificador de edição inválido")
    if not conexao.execute("SELECT 1 FROM antaq_edicoes WHERE edicao=?", (edicao,)).fetchone():
        raise ErroAntaq("edição inexistente")
    sql = """SELECT substr(a.data_atracacao,1,7), a.porto, a.uf,
             m.nome, c.sentido, COUNT(DISTINCT a.ida),
             SUM(CAST(c.peso_ton AS REAL)), COUNT(c.idc)
             FROM antaq_cargas c
             JOIN antaq_atracacoes a ON a.edicao=c.edicao AND a.ida=c.ida
             JOIN antaq_mercadorias m ON m.edicao=c.edicao AND m.codigo=c.codigo
             WHERE c.edicao=?
             GROUP BY 1,2,3,4,5 ORDER BY 1,2,4,5"""
    return [
        {"competencia":mes,"porto":porto,"uf":uf,"mercadoria":merc,"sentido":sentido,
         "escalas_distintas":escalas,"toneladas_realizadas":round(float(peso),3),
         "cargas":n,"fonte":"ANTAQ_ESTATISTICO_AQUAVIARIO","edicao_sha256":edicao,
         "natureza":"MOVIMENTACAO_REALIZADA_MENSAL_NAO_LINEUP","publicavel":False}
        for mes,porto,uf,merc,sentido,escalas,peso,n in conexao.execute(sql,(edicao,))
    ]
