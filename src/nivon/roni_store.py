"""Pipeline RONI de lotes locais: parser -> RAW imutável -> SQLite -> revisões.

Sem HTTP, scheduler, publicação ou promoção preditiva. Fontes externas devem
ser fornecidas por canal autorizado. Data de observação real é a da primeira
ingestão NIVON, NÃO a data histórica declarada de publicação de cada estação.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import sqlite3
import tempfile

from .noaa_roni import ErroRONI, importar_roni_ascii, classificar_episodios_roni

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS roni_snapshots (
 sha256 TEXT PRIMARY KEY, capturado_em_utc TEXT NOT NULL,
 visto_nivon_em_utc TEXT NOT NULL, classe TEXT NOT NULL,
 primeiro_mes TEXT NOT NULL, ultimo_mes TEXT NOT NULL,
 quantidade INTEGER NOT NULL, eventos INTEGER NOT NULL,
 arquivo TEXT NOT NULL UNIQUE, estado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roni_visto ON roni_snapshots(classe,visto_nivon_em_utc);
CREATE TABLE IF NOT EXISTS roni_valores (
 sha256 TEXT NOT NULL REFERENCES roni_snapshots(sha256),
 competencia TEXT NOT NULL, temporada TEXT NOT NULL,
 anomalia REAL NOT NULL, PRIMARY KEY(sha256,competencia)
);
CREATE TABLE IF NOT EXISTS roni_capturas (
 sha256 TEXT NOT NULL REFERENCES roni_snapshots(sha256),
 capturado_em_utc TEXT NOT NULL, visto_nivon_em_utc TEXT NOT NULL,
 PRIMARY KEY(sha256,visto_nivon_em_utc)
);
"""


def _tempo(value, label):
    if not isinstance(value, str) or "T" not in value:
        raise ErroRONI(label + ": timestamp com fuso obrigatório")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroRONI(label + ": timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroRONI(label + ": timezone obrigatório")
    return dt.astimezone(timezone.utc)


def _safe_dir(root):
    p = Path(root)
    if p.is_symlink() or (p.exists() and not p.is_dir()):
        raise ErroRONI("diretório RAW irregular ou symlink")
    if not p.exists():
        p.mkdir(parents=True, mode=0o700)
    if p.is_symlink():
        raise ErroRONI("diretório RAW symlink")
    return p.resolve()


def abrir_arquivo_roni(caminho=":memory:"):
    """Banco SQLite independente; persiste ao usar arquivo .sqlite local."""
    if caminho != ":memory:" and Path(caminho).is_symlink():
        raise ErroRONI("banco de dados não deve ser symlink")
    db = sqlite3.connect(str(caminho), timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    return db


def _guard_raw(root, digest, raw=None):
    path = root / (digest + ".ascii")
    if path.is_symlink():
        raise ErroRONI("snapshot RAW symlink proibido")
    if path.exists():
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ErroRONI("snapshot RAW existente foi modificado")
        if raw is not None and path.read_bytes() != raw:
            raise ErroRONI("SHA colidiu com bytes diferentes")
    elif raw is None:
        raise ErroRONI("snapshot RAW ausente do arquivo persistido")
    else:
        fd, temp_name = tempfile.mkstemp(prefix=".roni-", suffix=".tmp", dir=root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Só destinos derivados do SHA; não sobrescrever arquivos existentes.
            # link() é atômico e falha se snapshot surgir em corrida concorrente.
            try:
                os.link(temp_name, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != raw:
                    raise ErroRONI("concorrência conflitante no arquivo RAW")
        finally:
            os.unlink(temp_name)
    return path


def _ultimo(db, tipo):
    return db.execute(
        "SELECT * FROM roni_snapshots WHERE classe=? "
        "ORDER BY visto_nivon_em_utc DESC, sha256 DESC LIMIT 1", (tipo,)
    ).fetchone()


def _valores(db, digest):
    return {x["competencia"]: float(x["anomalia"])
            for x in db.execute(
                "SELECT competencia,anomalia FROM roni_valores WHERE sha256=?",
                (digest,))}


def executar_lote_roni(
    db, *, raw_dir, raw, coletado_em, classe="SINTETICO",
    instante_registro=None,
):
    """Executa UM arquivo local inteiro, persiste/deduplica e compara edições.

    instante_registro é injetável APENAS em testes SINTETICO; dados reais usam
    hora UTC do processo, impedindo que 'coletado_em' retroativo reescreva as-of.
    Entradas reais recebidas de arquivo são EXTERNO_NAO_HOMOLOGADO.
    """
    if classe not in ("SINTETICO", "EXTERNO_NAO_HOMOLOGADO"):
        raise ErroRONI("classe de dado RONI desconhecida")
    if classe != "SINTETICO" and instante_registro is not None:
        raise ErroRONI("horário de primeiro registro real não pode ser injetado")
    registro = (_tempo(instante_registro, "registro") if instante_registro is not None
                else datetime.now(timezone.utc))
    capturado = _tempo(coletado_em, "coleta")
    if capturado > registro:
        raise ErroRONI("coleta declarada depois do registro NIVON")
    if not isinstance(db, sqlite3.Connection):
        raise ErroRONI("banco SQLite obrigatório")
    parsed = importar_roni_ascii(raw=raw, coletado_em=coletado_em)
    digest = parsed["sha256"]
    last = _ultimo(db, classe)
    if last and registro.isoformat() < last["visto_nivon_em_utc"]:
        raise ErroRONI("primeiro registro retroativo: preservar sequência de capturas")
    old_values = _valores(db, last["sha256"]) if last else {}
    new_values = {x["competencia_centro"]: x["anomalia_roni_c"]
                  for x in parsed["registros"]}
    if last and set(old_values) - set(new_values):
        raise ErroRONI("arquivo RONI truncou competências já conhecidas")
    revisions = [
        x for x in new_values if x in old_values and new_values[x] != old_values[x]
    ]
    additions = [x for x in new_values if x not in old_values]
    root = _safe_dir(raw_dir)
    archive = _guard_raw(root, digest, raw)
    existing = db.execute(
        "SELECT * FROM roni_snapshots WHERE sha256=?", (digest,)
    ).fetchone()
    if existing is not None and existing["classe"] != classe:
        raise ErroRONI("mesmo RAW classificado em contextos incompatíveis")
    status = ("SEM_MUDANCA" if existing else
              "PRIMEIRA_EDICAO" if last is None else
              "NOVA_EDICAO_COM_REVISÕES" if revisions else
              "NOVA_EDICAO_SEM_REVISÕES")
    events = classificar_episodios_roni(parsed)["eventos"]
    with db:
        if existing is None:
            db.execute(
                "INSERT INTO roni_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",
                (digest, capturado.isoformat(), registro.isoformat(), classe,
                 parsed["centro_primeiro"], parsed["centro_ultimo"],
                 parsed["quantidade"], len(events), archive.name,
                 "NAO_HOMOLOGADO"))
            db.executemany(
                "INSERT INTO roni_valores VALUES (?,?,?,?)",
                [(digest, r["competencia_centro"], r["temporada"],
                  r["anomalia_roni_c"]) for r in parsed["registros"]])
        db.execute(
            "INSERT OR IGNORE INTO roni_capturas VALUES (?,?,?)",
            (digest, capturado.isoformat(), registro.isoformat()))
    return {
        "estado": status, "sha256": digest, "tipo": classe,
        "quantidade_temporadas": parsed["quantidade"],
        "competencia_primeira": parsed["centro_primeiro"],
        "competencia_ultima": parsed["centro_ultimo"],
        "competencias_novas": len(additions) if existing is None else 0,
        "competencias_revisadas": len(revisions) if existing is None else 0,
        "primeiro_registro_nivon": existing["visto_nivon_em_utc"]
        if existing else registro.isoformat(),
        "capturas_registradas": db.execute(
            "SELECT COUNT(*) FROM roni_capturas WHERE sha256=?", (digest,)
        ).fetchone()[0],
        "numero_episodios_retrospectivos": len(events),
        "origem_institucional_autenticada": False,
        "disponibilidade_passada_certificada": False,
        "pode_treinar_asof": False,
        "homologado": False,
        "publicacao_individual": None,
    }


def consultar_arquivo_roni(db, *, raw_dir, corte_em, classe="SINTETICO"):
    """Snapshot fisicamente arquivado na data de PRIMEIRA OBSERVAÇÃO NIVON.

    Não representa quando a NOAA publicou meses anteriores. Toda edição
    histórica coletada hoje só é conhecida pelo NIVON a partir de hoje.
    """
    if classe not in ("SINTETICO", "EXTERNO_NAO_HOMOLOGADO"):
        raise ErroRONI("classe desconhecida")
    corte = _tempo(corte_em, "corte")
    row = db.execute(
        "SELECT * FROM roni_snapshots WHERE classe=? AND visto_nivon_em_utc<=? "
        "ORDER BY visto_nivon_em_utc DESC, sha256 DESC LIMIT 1",
        (classe, corte.isoformat())
    ).fetchone()
    if row is None:
        return {"estado": "SEM_SNAPSHOT_CONHECIDO_ASOF", "snapshot_sha256": None,
                "homologado": False, "pode_treinar_asof": False}
    root = _safe_dir(raw_dir)
    _guard_raw(root, row["sha256"])
    return {
        "estado": "SNAPSHOT_LOCAL_CONHECIDO_NAO_HOMOLOGADO",
        "snapshot_sha256": row["sha256"],
        "primeiro_registro_nivon": row["visto_nivon_em_utc"],
        "arquivo_verificado": True,
        "quantidade_temporadas": row["quantidade"],
        "ultimo_mes": row["ultimo_mes"],
        "numero_episodios_retrospectivos": row["eventos"],
        "homologado": False, "pode_treinar_asof": False,
        "disponibilidade_historica_noaa_comprovada": False,
    }


def panorama_local_roni(db, *, raw_dir, classe="SINTETICO"):
    """Resumo executivo offline de histórico, sem copiar séries nem publicar."""
    last = _ultimo(db, classe)
    if not last:
        return {"estado": "VAZIO", "total_edicoes": 0,
                "homologado": False}
    _guard_raw(_safe_dir(raw_dir), last["sha256"])
    count = db.execute("SELECT COUNT(*) FROM roni_snapshots WHERE classe=?",
                       (classe,)).fetchone()[0]
    return {
        "estado": "SERIE_HISTORICA_LOCAL",
        "total_edicoes": count, "sha256_mais_recente": last["sha256"],
        "competencia_ultima": last["ultimo_mes"],
        "quantidade_temporadas": last["quantidade"],
        "total_capturas": db.execute(
            "SELECT COUNT(*) FROM roni_capturas WHERE sha256 IN "
            "(SELECT sha256 FROM roni_snapshots WHERE classe=?)",
            (classe,)).fetchone()[0],
        "ultima_primeira_observacao_nivon": last["visto_nivon_em_utc"],
        "historico_retrospectivo_nao_point_in_time": True,
        "homologado": False, "pode_ativar_coleta": False,
    }
