"""Auditoria OFFLINE de dois storages incompatíveis do CONAB semanal.

Não migra, publica, coleta ou presume que sha256_json (payload normalizado)
equivale a nivon_snapshots.sha256 (bytes brutos). Somente a coincidência de
chave, URL, horário da coleta e valores é comparável; nem isso prova o RAW.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from .progresso_conab_historico import _CAMPOS, _UFS, _CHAVE

_EXPECTED = frozenset(_CAMPOS - {"coleta"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX = 20000
_URL_HOSTS = frozenset({"www.gov.br", "www.conab.gov.br", "conab.gov.br"})
_PUBLICACAO = ("publicacao", "publicado_utc")


class ErroConciliacaoConab(ValueError):
    pass


def _timestamp(v: str) -> datetime:
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("fuso ausente")
    except (AttributeError, ValueError) as exc:
        raise ErroConciliacaoConab("timestamp inválido ou sem fuso") from exc
    return dt.astimezone(timezone.utc)


def _json_pares_unicos(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ErroConciliacaoConab("chaves JSON duplicadas")
        out[k] = v
    return out


def _campos(db: sqlite3.Connection, table: str, expected: set[str]) -> None:
    actual = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    if not expected <= actual:
        raise ErroConciliacaoConab(f"schema ausente ou incompatível: {table}")


def _verificar_esquemas(legacy: sqlite3.Connection, canonical: sqlite3.Connection):
    for db, tables in (
        (legacy, {
            "progresso_edicoes": {"id","fonte_url","sha256_json","publicado_utc","observado_semana","numero_linhas"},
            "progresso_coletas": {"edicao_id","coletado_utc"},
            "progresso_observacoes": {"edicao_id","cultura","safra","operacao","uf","semana","registro_json"},
        }),
        (canonical, {
            "nivon_snapshots": {"id","dataset_id","fonte_id","sha256","tipo","publicacao"},
            "nivon_coletas": {"snapshot_id","coletado_utc"},
            "nivon_conab_progresso": {"snapshot_id","chave","observacao_json"},
        }),
    ):
        for name, cols in tables.items():
            _campos(db, name, cols)


def _url(url: str) -> str:
    if not isinstance(url, str):
        raise ErroConciliacaoConab("URL fonte inválida")
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname not in _URL_HOSTS
            or u.username or u.password or u.port not in (None,443)
            or u.fragment or u.query):
        raise ErroConciliacaoConab("URL não oficial/ambígua na observação")
    return url


def _semana(v: str) -> str:
    try:
        d = date.fromisoformat(v)
    except (TypeError, ValueError) as exc:
        raise ErroConciliacaoConab("competência semanal inválida") from exc
    if d.isoformat() != v:
        raise ErroConciliacaoConab("competência deve ser data ISO")
    return v


def _normalizar_registro(raw: str) -> tuple[tuple[str, ...], str, dict]:
    try:
        r = json.loads(raw, object_pairs_hook=_json_pares_unicos)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ErroConciliacaoConab("JSON normalizado inválido") from exc
    if not isinstance(r, dict) or set(r) != _EXPECTED:
        raise ErroConciliacaoConab("contrato da observação CONAB divergente")
    if (r["source_id"] != "CONAB" or r["dataset_id"] != "CONAB_PROGRESSO_SEMANAL"
            or r["observational_kind"] != "INFORMADO"):
        raise ErroConciliacaoConab("origem/classe de evidência divergente")
    for k in ("cultura", "safra"):
        if not isinstance(r[k], str) or not r[k].strip():
            raise ErroConciliacaoConab("chave de progresso incompleta")
    if r["operacao"] not in {"Semeadura","Colheita"} or r["uf"] not in (_UFS | {"MEDIA_ESTADOS"}):
        raise ErroConciliacaoConab("operação/UF não catalogadas")
    if r["referencia"] != r["competencia"]:
        raise ErroConciliacaoConab("referência difere da competência")
    _semana(r["competencia"])
    for k in ("pct_semana_atual", "pct_ano_anterior", "pct_semana_anterior","pct_media_5_anos"):
        x = r[k]
        if x is None and k != "pct_semana_atual":
            continue
        if type(x) not in (float,int) or not math.isfinite(x) or not 0 <= x <= 1:
            raise ErroConciliacaoConab("percentual não finito ou fora de escala")
    if r["uf"] == "MEDIA_ESTADOS":
        if type(r["n_estados"]) is not int or not 1 <= r["n_estados"] <= 27:
            raise ErroConciliacaoConab("média de estados sem cobertura")
    elif r["n_estados"] is not None:
        raise ErroConciliacaoConab("n_estados inesperado para UF")
    url = _url(r["source_url"])
    if r["publicacao"] is not None:
        r["publicacao"] = _timestamp(r["publicacao"]).isoformat()
    key = tuple(r[k] for k in _CHAVE)
    semantic = json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)
    return key, semantic, r


def _coletar(db: sqlite3.Connection, store: str, corte: datetime,
             corte_publicacao: datetime | None, limit: int):
    if store == "LEGADO":
        query = """SELECT e.id,e.fonte_url,e.sha256_json,e.publicado_utc,
                          e.observado_semana,e.numero_linhas,c.coletado_utc,
                          o.cultura,o.safra,o.operacao,o.uf,o.semana,o.registro_json
                   FROM progresso_edicoes e
                   JOIN progresso_coletas c ON c.edicao_id=e.id
                   JOIN progresso_observacoes o ON o.edicao_id=e.id
                   ORDER BY e.id,c.coletado_utc,o.cultura,o.safra,o.uf,o.semana
                   LIMIT ?"""
    else:
        query = """SELECT s.id,s.dataset_id,s.fonte_id,s.sha256,s.tipo,s.publicacao,
                          c.coletado_utc,p.chave,p.observacao_json
                   FROM nivon_snapshots s
                   JOIN nivon_coletas c ON c.snapshot_id=s.id
                   JOIN nivon_conab_progresso p ON p.snapshot_id=s.id
                   WHERE s.dataset_id='CONAB_PROGRESSO_SEMANAL'
                   ORDER BY s.id,c.coletado_utc,p.chave LIMIT ?"""
    rows = db.execute(query, (limit+1,)).fetchall()
    if len(rows) > limit:
        raise ErroConciliacaoConab("histórico maior que limite; paginar antes de conciliar")
    result = {}
    excluded = Counter()
    revisions = set()
    totals = Counter()
    for row in rows:
        sid = row[0]
        stamp = _timestamp(row[6])
        if stamp > corte:
            excluded["APOS_CORTE_COLETA"] += 1
            continue
        if store == "LEGADO":
            _, source, edition_sha, ed_pub, week, n_rows, _, cultura,safra,op,uf,sem,raw = row
            if not isinstance(edition_sha, str) or not _SHA.fullmatch(edition_sha):
                raise ErroConciliacaoConab("hash do JSON legado inválido")
            key, semantic, item = _normalizar_registro(raw)
            if (key != (cultura,safra,op,uf,sem) or item["source_url"] != source
                    or sem != week or not isinstance(n_rows,int) or n_rows < 1):
                raise ErroConciliacaoConab("inconsistência entre colunas e JSON legado")
            published = _timestamp(ed_pub) if ed_pub is not None else None
            if (published is None) != (item["publicacao"] is None):
                raise ErroConciliacaoConab("publicação no legado não reconcilia com JSON")
            if published is not None and published.isoformat() != item["publicacao"]:
                raise ErroConciliacaoConab("timestamp legado diverge do JSON")
        else:
            _,dataset,source,raw_sha,tipo,pub_date,_,chave,raw = row
            if dataset != "CONAB_PROGRESSO_SEMANAL" or source != "CONAB":
                raise ErroConciliacaoConab("fonte inválida no ledger")
            if tipo not in ("SINTETICO","REAL_AUTORIZADO") or not _SHA.fullmatch(str(raw_sha)):
                raise ErroConciliacaoConab("SHA/tipo inválido no ledger")
            key, semantic, item = _normalizar_registro(raw)
            try:
                chk = json.loads(chave)
            except (TypeError, ValueError) as exc:
                raise ErroConciliacaoConab("chave canônica não é JSON") from exc
            if chk != list(key):
                raise ErroConciliacaoConab("chave indexada difere da observação")
            published = _timestamp(item["publicacao"]) if item["publicacao"] else None
            if (published is None) != (pub_date is None):
                raise ErroConciliacaoConab("publicação canônica e JSON divergentes")
            if published is not None and pub_date != published.date().isoformat():
                raise ErroConciliacaoConab("data de publicação canônica diverge do JSON")
        if published is not None and published > stamp:
            raise ErroConciliacaoConab("publicação posterior à coleta")
        if corte_publicacao is not None and (published is None or published > corte_publicacao):
            excluded["SEM_PUBLICACAO_COMPROVADA_ATE_CORTE"] += 1
            continue
        group = (item["source_url"], key, stamp.isoformat())
        if group in result:
            # Uma mesma chave de negócio + captura não pode representar dois vintages.
            raise ErroConciliacaoConab("captura/chave duplicada no mesmo armazenamento")
        result[group] = {"semantic":semantic, "source_hash_type":
                         "NORMALIZED_JSON" if store=="LEGADO" else "RAW_FILE_CLAIMED",
                         "tipo": "NAO_DECLARADO_NO_LEGADO" if store=="LEGADO" else tipo}
        revisions.add((item["source_url"],key))
        totals["LINHAS_COMPARADAS"] += 1
    return result, excluded, revisions, totals



def _auditar_integridade_bancos(legado: sqlite3.Connection,
                               canonico: sqlite3.Connection, limite: int) -> int:
    """Valida integridade das edições legadas sem confundir hash JSON com RAW.

    A checagem é histórica e read-only: todas as edições/linhas precisam
    estar acessíveis dentro do limite para não gerar falsa confiança.
    """
    verificacoes = (
        (legado, """SELECT COUNT(*) FROM progresso_edicoes e
                    WHERE NOT EXISTS (SELECT 1 FROM progresso_coletas c WHERE c.edicao_id=e.id)"""),
        (legado, """SELECT COUNT(*) FROM progresso_observacoes o
                    LEFT JOIN progresso_edicoes e ON e.id=o.edicao_id
                    WHERE e.id IS NULL"""),
        (canonico, """SELECT COUNT(*) FROM nivon_snapshots s
                     WHERE s.dataset_id='CONAB_PROGRESSO_SEMANAL'
                       AND NOT EXISTS (SELECT 1 FROM nivon_coletas c WHERE c.snapshot_id=s.id)"""),
        (canonico, """SELECT COUNT(*) FROM nivon_conab_progresso p
                     LEFT JOIN nivon_snapshots s ON s.id=p.snapshot_id
                     WHERE s.id IS NULL OR s.dataset_id!='CONAB_PROGRESSO_SEMANAL'"""),
    )
    for db, sql in verificacoes:
        if db.execute(sql).fetchone()[0]:
            raise ErroConciliacaoConab("edição, observação ou captura órfã no histórico")
    rows = legado.execute("""SELECT e.id,e.sha256_json,e.numero_linhas,o.registro_json
            FROM progresso_edicoes e
            LEFT JOIN progresso_observacoes o ON o.edicao_id=e.id
            ORDER BY e.id,o.cultura,o.safra,o.operacao,o.uf,o.semana LIMIT ?""",
            (limite+1,)).fetchall()
    if len(rows)>limite:
        raise ErroConciliacaoConab("excesso de observações legadas: auditoria exige paginação")
    groups = {}
    for ed_id, sha, qtd, raw in rows:
        if (not isinstance(sha,str) or not _SHA.fullmatch(sha)
                or type(qtd) is not int or qtd <= 0 or raw is None):
            raise ErroConciliacaoConab("edição legada inválida")
        key, _, _ = _normalizar_registro(raw)
        try:
            original=json.loads(raw,object_pairs_hook=_json_pares_unicos)
        except (TypeError, ValueError) as exc:
            raise ErroConciliacaoConab("JSON legado inválido") from exc
        item=groups.setdefault(ed_id,{"sha":sha,"qtd":qtd,"rows":[],"keys":set()})
        if (item["sha"],item["qtd"]) != (sha,qtd) or key in item["keys"]:
            raise ErroConciliacaoConab("chaves/conteúdo inconsistentes na edição legada")
        item["keys"].add(key)
        item["rows"].append(original)
    for item in groups.values():
        if len(item["rows"]) != item["qtd"]:
            raise ErroConciliacaoConab("contagem de observações legadas não coincide com edição")
        dados=sorted(item["rows"],key=lambda r:tuple(r[k] for k in _CHAVE))
        digest=hashlib.sha256(json.dumps(dados,ensure_ascii=False,sort_keys=True,
                   separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
        if digest != item["sha"]:
            raise ErroConciliacaoConab("SHA do JSON legado não confere com observações persistidas")
    return len(groups)


def conciliar_stores_conab(legado: sqlite3.Connection, canonico: sqlite3.Connection,
                           *, corte_coleta: str, corte_publicacao: str | None = None,
                           limite: int = _MAX) -> dict:
    """Compara apenas capturas com a mesma identidade, sem fundir nenhuma."""
    if type(limite) is not int or not 1 <= limite <= _MAX:
        raise ErroConciliacaoConab("limite precisa ser inteiro até 20000")
    cutoff = _timestamp(corte_coleta)
    pubcut = _timestamp(corte_publicacao) if corte_publicacao is not None else None
    _verificar_esquemas(legado, canonico)
    leg_edicoes_verificadas = _auditar_integridade_bancos(legado, canonico, limite)
    a, excl_a, keys_a, ct_a = _coletar(legado, "LEGADO", cutoff, pubcut, limite)
    b, excl_b, keys_b, ct_b = _coletar(canonico, "CANONICO", cutoff, pubcut, limite)
    tally = Counter()
    examples = []
    for key in sorted(set(a) | set(b)):
        left, right = a.get(key), b.get(key)
        if left is None:
            phase = "SOMENTE_CANONICO_NESTA_CAPTURA"
        elif right is None:
            phase = "SOMENTE_LEGADO_NESTA_CAPTURA"
        elif left["semantic"] == right["semantic"]:
            phase = "VALORES_IGUAIS_NA_MESMA_CAPTURA_SEM_PROVA_RAW"
        else:
            phase = "DIVERGENCIA_VALORES_MESMA_CAPTURA"
        tally[phase] += 1
        if len(examples) < 30:
            source_url, k, stamp = key
            examples.append({
                "chave": list(k), "coleta_utc": stamp, "situacao": phase,
                "origem_url": source_url,
            })
    no_both = bool(keys_a & keys_b) and not any(
        x in tally for x in ("VALORES_IGUAIS_NA_MESMA_CAPTURA_SEM_PROVA_RAW",
                             "DIVERGENCIA_VALORES_MESMA_CAPTURA"))
    if not a and not b:
        status = "SEM_REGISTROS_NO_RECORTE_NAO_EQUIVALE_A_ZERO_NA_FONTE"
    elif tally["DIVERGENCIA_VALORES_MESMA_CAPTURA"]:
        status = "BLOQUEADO_DIVERGENCIA_SEMANTICA"
    elif no_both:
        status = "SEM_CAPTURAS_PAREADAS_HISTORICO_NAO_CONCILIADO"
    else:
        status = "COMPARACAO_PARCIAL_SEM_HOMOLOGACAO"
    return {
        "dataset_id": "CONAB_PROGRESSO_SEMANAL",
        "estado": status,
        "corte_coleta_utc": cutoff.isoformat(),
        "corte_publicacao_utc": pubcut.isoformat() if pubcut else None,
        "linhas_legado_comparadas": ct_a["LINHAS_COMPARADAS"],
        "edicoes_legadas_hash_json_recalculado": leg_edicoes_verificadas,
        "linhas_canonico_comparadas": ct_b["LINHAS_COMPARADAS"],
        "excluidas_legado": dict(sorted(excl_a.items())),
        "excluidas_canonico": dict(sorted(excl_b.items())),
        "contagem_por_situacao": dict(sorted(tally.items())),
        "mesmas_chaves_sem_mesma_captura": no_both,
        "exemplos_max_30": examples,
        "hashes_diferentes_semanticas": {
            "progresso_edicoes.sha256_json": "HASH_JSON_NORMALIZADO",
            "nivon_snapshots.sha256": "HASH_BYTES_BRUTOS_DECLARADO",
        },
        "migration_allowed": False,
        "publicacao_autorizada": False,
        "origem_raw_comprovada": False,
        "nota": "Coincidência de valores não prova identidade de arquivo, direitos ou publicação histórica.",
    }


def _abrir_readonly(path: str) -> sqlite3.Connection:
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ErroConciliacaoConab("arquivo SQLite deve existir e não ser symlink")
    uri = "file:" + quote(str(p.resolve()), safe="/") + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
    except sqlite3.Error as exc:
        raise ErroConciliacaoConab("não foi possível abrir banco somente leitura") from exc
    return db


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Comparador offline legado/canônico CONAB; nunca migra")
    p.add_argument("--legado", required=True)
    p.add_argument("--canonico", required=True)
    p.add_argument("--corte-coleta", required=True)
    p.add_argument("--corte-publicacao")
    p.add_argument("--resumo", action="store_true")
    args = p.parse_args(argv)
    opened = []
    try:
        for path in (args.legado, args.canonico):
            d = _abrir_readonly(path)
            opened.append(d)
        result = conciliar_stores_conab(
            opened[0],opened[1],corte_coleta=args.corte_coleta,
            corte_publicacao=args.corte_publicacao,
        )
        if args.resumo:
            result.pop("exemplos_max_30")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (sqlite3.Error, OSError, ErroConciliacaoConab) as exc:
        p.error(str(exc))
    finally:
        for db in opened:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
