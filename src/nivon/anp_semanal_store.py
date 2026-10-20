"""Histórico bitemporal OFFLINE da ANP/LPC SEMANAL OFICIAL.

Não confundir com anp_diesel_store: este último usa semana de calendário
INFERIDA a partir do CSV mensal. Este módulo persiste apenas o resumo semanal
oficial ANP da PR #8; publicação da edição é evidência EXTERNA obrigatória.
Dados nunca são considerados aptos à redistribuição por este módulo.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
import sqlite3
from typing import Mapping
from urllib.parse import urlsplit


class ErroANPOficial(ValueError):
    pass


SHA = re.compile(r"^[0-9a-f]{64}$")
UF = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


def _tempo(v: object, campo: str) -> datetime:
    if not isinstance(v, str):
        raise ErroANPOficial(f"{campo} exige timestamp")
    try:
        x = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroANPOficial(f"{campo}: timestamp inválido") from exc
    if x.tzinfo is None or x.utcoffset() is None:
        raise ErroANPOficial(f"{campo}: timezone obrigatório")
    return x.astimezone(timezone.utc)


def _sha(v: object, campo: str) -> str:
    if not isinstance(v, str) or not SHA.fullmatch(v):
        raise ErroANPOficial(f"{campo}: SHA-256 obrigatório")
    return v


def _url(v: object) -> str:
    if not isinstance(v, str):
        raise ErroANPOficial("URL ANP ausente")
    p = urlsplit(v)
    if (p.scheme != "https" or p.hostname != "www.gov.br" or
            p.username or p.password or p.fragment or not p.path.startswith("/anp/")):
        raise ErroANPOficial("origem não é endereço autorizado da ANP")
    return v


def _semana(x: object) -> date:
    if not isinstance(x, str):
        raise ErroANPOficial("data semanal ausente")
    try:
        return date.fromisoformat(x)
    except ValueError as exc:
        raise ErroANPOficial("data semanal inválida") from exc


def _observacoes(resumo: Mapping, publicado: datetime) -> list[dict]:
    if (resumo.get("dataset_id") != "ANP_PRECO_REVENDA_DIESEL" or
        resumo.get("fonte") != "ANP_RESUMO_LPC_SEMANAL" or
        resumo.get("publicavel") is not False):
        raise ErroANPOficial("somente o resumo ANP/LPC semanal não publicável é aceito")
    linhas = resumo.get("observacoes")
    if not isinstance(linhas, list) or not 1 <= len(linhas) <= 20_000:
        raise ErroANPOficial("sem observações oficiais ou amostra excessiva")
    seen = set()
    out = []
    for r in linhas:
        if not isinstance(r, Mapping) or r.get("uf") not in UF:
            raise ErroANPOficial("localidade inválida")
        if r.get("produto") not in {"DIESEL", "DIESEL S10"}:
            raise ErroANPOficial("diesel e diesel S10 separados")
        municipio = r.get("municipio")
        if not isinstance(municipio, str) or municipio != municipio.strip().upper() or not 1 <= len(municipio) <= 120:
            raise ErroANPOficial("município inválido")
        di = _semana(r.get("semana_inicio_oficial"))
        df = _semana(r.get("semana_fim_oficial"))
        if (df-di).days != 6 or df > publicado.date():
            raise ErroANPOficial("semana oficial incoerente com data de publicação")
        if r.get("natureza") != "MEDIA_AMOSTRAL_REVENDA_MUNICIPIO_ANP_SEMANA_OFICIAL":
            raise ErroANPOficial("não é preço médio amostral oficial semanal")
        try:
            if isinstance(r.get("preco_medio_revenda_rs_l"), bool):
                raise InvalidOperation()
            preco = Decimal(str(r.get("preco_medio_revenda_rs_l")))
        except (TypeError, InvalidOperation) as exc:
            raise ErroANPOficial("preço ANP inválido") from exc
        if not preco.is_finite() or not Decimal("0.1") <= preco < Decimal("50"):
            raise ErroANPOficial("preço fora da faixa")
        postos = r.get("postos_pesquisados")
        if type(postos) is not int or not 1 <= postos <= 15000:
            raise ErroANPOficial("número de postos inválido")
        chave = (r["uf"], municipio, r["produto"], di.isoformat())
        if chave in seen:
            raise ErroANPOficial("observação repetida na edição")
        seen.add(chave)
        out.append({
            "uf": r["uf"], "municipio": municipio, "produto": r["produto"],
            "semana_inicio": di.isoformat(), "semana_fim": df.isoformat(),
            "preco_medio": str(preco), "postos": postos,
        })
    return sorted(out, key=lambda x: (x["uf"], x["municipio"], x["produto"], x["semana_inicio"]))


def inicializar_store_anp(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS anp_semanal_edicoes (
      sha TEXT PRIMARY KEY, fonte_url TEXT NOT NULL, classe TEXT NOT NULL,
      data_publicacao TEXT NOT NULL, prova_publicacao_sha TEXT NOT NULL,
      prova_direitos_sha TEXT, resumo_sha TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS anp_semanal_capturas (
      sha TEXT NOT NULL REFERENCES anp_semanal_edicoes(sha),
      data_coleta TEXT NOT NULL, PRIMARY KEY (sha, data_coleta)
    );
    CREATE TABLE IF NOT EXISTS anp_semanal_observacoes (
      sha TEXT NOT NULL REFERENCES anp_semanal_edicoes(sha),
      uf TEXT NOT NULL, municipio TEXT NOT NULL, produto TEXT NOT NULL,
      semana_inicio TEXT NOT NULL, semana_fim TEXT NOT NULL,
      preco_medio TEXT NOT NULL, postos INTEGER NOT NULL,
      PRIMARY KEY (sha, uf, municipio, produto, semana_inicio)
    );
    CREATE INDEX IF NOT EXISTS idx_anp_semanal_periodo
    ON anp_semanal_observacoes (uf, municipio, produto, semana_fim);
    """)


def gravar_edicao_semanal(
    db: sqlite3.Connection, *, resumo: Mapping,
    data_publicacao: str, prova_publicacao_sha: str,
    classe: str = "SINTETICO", prova_direitos_sha: str | None = None,
    direitos_confirmados: bool = False,
) -> dict:
    """Persiste apenas agregado; real exige atestação de direitos independente.

    SHA de prova é referência, NÃO validação automática da prova externa.
    """
    if not isinstance(resumo, Mapping):
        raise ErroANPOficial("resumo inválido")
    pub = _tempo(data_publicacao, "data_publicacao")
    coleta = _tempo(resumo.get("coletado_em"), "data_coleta")
    if pub > coleta:
        raise ErroANPOficial("publicação posterior à captura")
    original = _sha(resumo.get("sha256"), "sha256_arquivo")
    prova_pub = _sha(prova_publicacao_sha, "prova_publicacao_sha")
    origem = _url(resumo.get("url_origem"))
    if classe not in {"SINTETICO", "REAL_AUTORIZADO"}:
        raise ErroANPOficial("classe de edição não suportada")
    if classe == "REAL_AUTORIZADO":
        if direitos_confirmados is not True:
            raise PermissionError("armazenamento real sem direitos homologados")
        prova_direitos = _sha(prova_direitos_sha, "prova_direitos_sha")
    elif prova_direitos_sha is not None or direitos_confirmados:
        raise ErroANPOficial("fixture não recebe direitos de edição real")
    else:
        prova_direitos = None

    linhas = _observacoes(resumo, pub)
    digest = sha256(json.dumps(linhas, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True).encode()).hexdigest()
    db.row_factory = sqlite3.Row
    with db:
        ja = db.execute("SELECT * FROM anp_semanal_edicoes WHERE sha=?",
                        (original,)).fetchone()
        if ja is None:
            db.execute("""INSERT INTO anp_semanal_edicoes
                (sha,fonte_url,classe,data_publicacao,prova_publicacao_sha,
                 prova_direitos_sha,resumo_sha) VALUES (?,?,?,?,?,?,?)""",
                (original, origem, classe, pub.isoformat(), prova_pub,
                 prova_direitos, digest))
            db.executemany("""INSERT INTO anp_semanal_observacoes
                (sha,uf,municipio,produto,semana_inicio,semana_fim,
                 preco_medio,postos) VALUES (?,?,?,?,?,?,?,?)""",
                [(original, x["uf"], x["municipio"], x["produto"],
                  x["semana_inicio"], x["semana_fim"], x["preco_medio"], x["postos"])
                 for x in linhas])
        elif any((
            ja["fonte_url"] != origem, ja["classe"] != classe,
            ja["data_publicacao"] != pub.isoformat(),
            ja["prova_publicacao_sha"] != prova_pub,
            ja["prova_direitos_sha"] != prova_direitos,
            ja["resumo_sha"] != digest,
        )):
            raise ErroANPOficial("mesmo SHA original com edição, provas ou dados conflitantes")
        changes = db.execute("""INSERT OR IGNORE INTO anp_semanal_capturas
            (sha,data_coleta) VALUES (?,?)""", (original, coleta.isoformat())).rowcount
    return {
        "status": "AGREGADO_OFICIAL_ISOLADO",
        "sha256_original": original, "captura_nova": changes == 1,
        "observacoes": len(linhas), "classe": classe,
        "fonte_publicavel": False, "reconstroi_semana": False,
        "data_publicacao": pub.isoformat(), "data_coleta": coleta.isoformat(),
    }


def consultar_preco_semanal(
    db: sqlite3.Connection, *, municipio: str, produto: str,
    uf: str, as_of: str, limite_dias: int = 21,
) -> dict:
    """Leitura PIT: publicação e coleta existentes no momento consultado.

    Múltiplas edições conflitantes da mesma semana produzem INDETERMINADO.
    Apenas séries reais autorizadas podem chegar ao indicador; nunca publica.
    """
    corte = _tempo(as_of, "as_of")
    if (uf not in UF or produto not in {"DIESEL", "DIESEL S10"}
            or not isinstance(municipio, str) or not 1 <= len(municipio) <= 120
            or municipio != municipio.strip().upper()
            or type(limite_dias) is not int or not 1 <= limite_dias <= 90):
        raise ErroANPOficial("chaves de consulta inválidas")
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT o.*,e.sha,e.fonte_url,e.data_publicacao,
               MIN(c.data_coleta) AS primeira_coleta
        FROM anp_semanal_observacoes o
        JOIN anp_semanal_edicoes e ON e.sha=o.sha
        JOIN anp_semanal_capturas c ON c.sha=e.sha
        WHERE e.classe='REAL_AUTORIZADO'
          AND o.uf=? AND o.municipio=? AND o.produto=?
          AND o.semana_fim<=? AND e.data_publicacao<=? AND c.data_coleta<=?
        GROUP BY o.sha,o.uf,o.municipio,o.produto,o.semana_inicio
        ORDER BY o.semana_fim DESC LIMIT 1001
    """, (uf, municipio, produto, corte.date().isoformat(),
          corte.isoformat(), corte.isoformat())).fetchall()
    if not rows:
        return {"status": "SEM_EDICAO_REAL_ASOF", "publicavel": False}
    if len(rows) > 1000:
        return {"status": "HISTORICO_EXCESSIVO", "publicavel": False}
    semana = rows[0]["semana_fim"]
    atual = [r for r in rows if r["semana_fim"] == semana]
    diferentes = {(r["preco_medio"], r["postos"], r["semana_inicio"]) for r in atual}
    if len(diferentes) > 1:
        return {"status": "REVISOES_CONFLITANTES", "publicavel": False,
                "semana_fim": semana, "edicoes": len(atual)}
    if (corte.date()-_semana(semana)).days > limite_dias:
        return {"status": "DADO_VENCIDO", "publicavel": False,
                "semana_fim": semana}
    escolhido = min(atual, key=lambda x: (x["data_publicacao"], x["primeira_coleta"], x["sha"]))
    return {
        "status": "AMOSTRA_HISTORICA_PIT", "publicavel": False,
        "uf": uf, "municipio": municipio, "produto": produto,
        "preco_medio_revenda_brl_l": escolhido["preco_medio"],
        "postos_pesquisados": escolhido["postos"],
        "semana_inicio_oficial": escolhido["semana_inicio"],
        "semana_fim_oficial": escolhido["semana_fim"],
        "data_publicacao": escolhido["data_publicacao"],
        "primeira_coleta": escolhido["primeira_coleta"],
        "sha256": escolhido["sha"], "fonte_url": escolhido["fonte_url"],
        "classe": "ANP_MEDIA_AMOSTRAL_MUNICIPAL_DIESEL_B_NAO_FRETE",
        "observacao": "Não comprova preço pago por transportadora; divulgação externa não autorizada automaticamente",
    }
