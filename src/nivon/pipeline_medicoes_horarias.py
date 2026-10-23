"""NIVON: pipeline offline unificado de medições INMET horárias / ANA adotadas.

Garante rastreabilidade dos bytes RAW, separação de natureza e suporte temporal,
vintages pela primeira ingestão no NIVON e atomicidade de 1-40 arquivos por
ciclo. Não executa rede nem agenda coletores. Nunca promove hora de chuva
a acumulado diário ou telemetria ANA a vazão média diária.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from .inmet_horario_qc import extrair_horarios_inmet
from .ana_hidrowebservice import normalizar_adotada
from .transacoes_sqlite import savepoint_atomico

TIPOS = frozenset({"INMET_HORARIO_CSV", "ANA_ADOTADA_JSON"})
CLASSES = frozenset({"SINTETICO", "EXTERNO_NAO_HOMOLOGADO"})
MAX_RAW = {"INMET_HORARIO_CSV": 8_000_000, "ANA_ADOTADA_JSON": 2_000_000}
_HASH = re.compile(r"[0-9a-f]{64}\Z")

_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS medidas_edicoes (
 sha256 TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, formato TEXT NOT NULL,
 estacao_id TEXT NOT NULL, ano INTEGER, zona TEXT, classe TEXT NOT NULL,
 fonte_coletado_utc TEXT NOT NULL, visto_nivon_utc TEXT NOT NULL,
 publicado_utc TEXT, arquivo TEXT NOT NULL UNIQUE,
 registros INTEGER NOT NULL, estado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS medidas_registros (
 sha256 TEXT NOT NULL REFERENCES medidas_edicoes(sha256),
 medido_utc TEXT NOT NULL, metrica TEXT NOT NULL,
 valor REAL NOT NULL, unidade TEXT NOT NULL,
 qualidade_origem TEXT NOT NULL, suporte_temporal TEXT NOT NULL,
 PRIMARY KEY(sha256,medido_utc,metrica));
CREATE TABLE IF NOT EXISTS medidas_capturas (
 sha256 TEXT NOT NULL REFERENCES medidas_edicoes(sha256),
 visto_nivon_utc TEXT NOT NULL,
 PRIMARY KEY(sha256,visto_nivon_utc));
CREATE INDEX IF NOT EXISTS idx_medidas_tempo ON medidas_registros(medido_utc,metrica);
CREATE INDEX IF NOT EXISTS idx_medidas_estacao ON medidas_edicoes(dataset_id,estacao_id,visto_nivon_utc);
"""


class ErroPipelineAmbiental(ValueError):
    pass


def _tempo(texto, nome):
    if not isinstance(texto, str) or "T" not in texto:
        raise ErroPipelineAmbiental(nome + ": ISO com timezone obrigatório")
    try:
        t = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPipelineAmbiental(nome + ": data inválida") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroPipelineAmbiental(nome + ": timezone ausente")
    return t.astimezone(timezone.utc)


def _pasta(pasta, *, criar):
    path = Path(pasta)
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ErroPipelineAmbiental("diretório RAW irregular")
    if not path.exists():
        if not criar:
            raise ErroPipelineAmbiental("arquivo RAW não localizado")
        path.mkdir(parents=True, mode=0o700)
    if path.is_symlink():
        raise ErroPipelineAmbiental("diretório RAW symlink proibido")
    return path.resolve()


def _raw(pasta, digest, *, data=None):
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ErroPipelineAmbiental("identificador hash inválido")
    path = pasta / (digest + ".raw")
    if path.is_symlink():
        raise ErroPipelineAmbiental("RAW symlink proibido")
    if path.exists():
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ErroPipelineAmbiental("RAW adulterado no acervo")
        if data is not None and path.read_bytes() != data:
            raise ErroPipelineAmbiental("arquivo RAW conflita com hash existente")
    elif data is None:
        raise ErroPipelineAmbiental("RAW ausente no acervo")
    else:
        fd, temp_name = tempfile.mkstemp(prefix=".amb-", dir=pasta)
        try:
            with os.fdopen(fd, "wb") as fp:
                fp.write(data)
                fp.flush()
                os.fsync(fp.fileno())
            try:
                os.link(temp_name, path)
            except FileExistsError:
                if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                    raise ErroPipelineAmbiental("colisão ou conflito RAW")
        finally:
            Path(temp_name).unlink(missing_ok=True)
    return path


def abrir_banco_medicoes(caminho=":memory:"):
    if caminho != ":memory:" and Path(caminho).is_symlink():
        raise ErroPipelineAmbiental("SQLite symlink não permitido")
    db = sqlite3.connect(str(caminho), timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    return db


def preparar_arquivo_medicoes(*, formato, raw, estacao_id, coletado_em,
                             ano=None, zona=None, classe="SINTETICO",
                             observado_nivon_em=None):
    """Normaliza em memória. Em dados externos o relógio é SEMPRE do processo."""
    if formato not in TIPOS or classe not in CLASSES:
        raise ErroPipelineAmbiental("formato ou classe de edição inválida")
    if not isinstance(raw, bytes) or not 12 <= len(raw) <= MAX_RAW[formato]:
        raise ErroPipelineAmbiental("tamanho ou conteúdo de RAW inválido")
    if classe != "SINTETICO" and observado_nivon_em is not None:
        raise ErroPipelineAmbiental("data de registro real não pode ser injetada")
    captura = _tempo(coletado_em, "coleta declarada")
    visto = (_tempo(observado_nivon_em, "observação NIVON")
             if observado_nivon_em is not None else datetime.now(timezone.utc))
    if captura > visto:
        raise ErroPipelineAmbiental("coleta futura em relação ao NIVON")
    digest = sha256(raw).hexdigest()
    if formato == "INMET_HORARIO_CSV":
        pacote = extrair_horarios_inmet(
            csv_bytes=raw, estacao_esperada=estacao_id, ano_esperado=ano)
        dataset = "INMET_ESTACOES"
        registros = []
        for row in pacote["observacoes"]:
            stamp = f'{row["data_utc"]}T{row["hora_utc"]:02d}:00:00+00:00'
            if row["chuva_hora_mm"] is not None:
                registros.append((stamp, "CHUVA_HORA_MM", row["chuva_hora_mm"],
                                  "MM", "BRUTO_SEM_QC", "HORA_ROTULADA_SEM_CONVENCAO"))
            if row["temp_ar_bulbo_seco_c"] is not None:
                registros.append((stamp, "TEMP_BULBO_HORA_C",
                                  row["temp_ar_bulbo_seco_c"], "CELSIUS",
                                  "BRUTO_SEM_QC", "AMOSTRA_HORARIA"))
    else:
        if ano is not None:
            raise ErroPipelineAmbiental("ANA não possui ano de CSV")
        pacote = normalizar_adotada(
            raw, estacao=estacao_id, zona_estacao=zona,
            coletado_em=coletado_em, origem_sha256=digest)
        dataset = "ANA_HIDRO"
        registros = [
            (row["data_hora_medicao_utc"], row["variavel"], row["valor"],
             row["unidade"], row["qualidade"],
             "INSTANTANEO_OU_INTERVALO_API_NAO_HOMOLOGADO")
            for row in pacote
        ]
    if not registros:
        raise ErroPipelineAmbiental("arquivo não possui medidas utilizáveis")
    unique = {(r[0],r[1]) for r in registros}
    if len(unique) != len(registros):
        raise ErroPipelineAmbiental("medições com mesmo instante e métrica")
    if any(_tempo(row[0], "medição") > captura for row in registros):
        raise ErroPipelineAmbiental("medição reportada depois da captura declarada")
    return {
        "raw": raw, "sha256": digest, "formato": formato,
        "dataset_id": dataset, "estacao_id": estacao_id,
        "ano": ano, "zona": zona, "classe": classe,
        "fonte_coletado_utc": captura.isoformat(),
        "visto_nivon_utc": visto.isoformat(),
        "publicado_utc": None, "registros": registros,
        "completude_qc_homologada": False, "fuso_validado_externamente": False,
    }


def _ultima_captura(db, dataset, station, tipo):
    return db.execute(
        "SELECT MAX(c.visto_nivon_utc) FROM medidas_capturas c "
        "JOIN medidas_edicoes e ON e.sha256=c.sha256 "
        "WHERE e.dataset_id=? AND e.estacao_id=? AND e.classe=?",
        (dataset, station, tipo)
    ).fetchone()[0]


def importar_ciclo_medicoes(db, *, raw_dir, edicoes):
    """Um ciclo com N arquivos previamente analisados; rollback DB e novos RAW."""
    if not isinstance(db, sqlite3.Connection) or not isinstance(edicoes, list) or not 1<=len(edicoes)<=40:
        raise ErroPipelineAmbiental("ciclo exige banco e 1–40 edições")
    for e in edicoes:
        if not isinstance(e, dict) or not isinstance(e.get("raw"),bytes) or sha256(e["raw"]).hexdigest()!=e.get("sha256"):
            raise ErroPipelineAmbiental("edição alterada após preflight")
    folder = _pasta(raw_dir, criar=True)
    prior_paths = {p.name for p in folder.glob("*.raw")}
    events = []
    try:
        with savepoint_atomico(db):
            for item in edicoes:
                dataset, station, sha = item["dataset_id"], item["estacao_id"], item["sha256"]
                when = item["visto_nivon_utc"]
                last = _ultima_captura(db, dataset, station, item["classe"])
                if last is not None and when < last:
                    raise ErroPipelineAmbiental("captura com relógio retroativo")
                existing = db.execute(
                    "SELECT * FROM medidas_edicoes WHERE sha256=?", (sha,)
                ).fetchone()
                if existing is not None:
                    identity = ("dataset_id","formato","estacao_id","ano","zona","classe","fonte_coletado_utc")
                    if any(existing[k] != item[k] for k in identity):
                        raise ErroPipelineAmbiental("mesmo RAW com metadados de outra origem")
                    old = [(r["medido_utc"],r["metrica"],r["valor"],r["unidade"],
                            r["qualidade_origem"],r["suporte_temporal"]) for r in db.execute(
                        "SELECT * FROM medidas_registros WHERE sha256=? ORDER BY medido_utc,metrica",
                        (sha,))]
                    fresh = sorted(item["registros"],key=lambda r:(r[0],r[1]))
                    if old != fresh:
                        raise ErroPipelineAmbiental("mesmo RAW com normalização contraditória")
                if db.execute("SELECT 1 FROM medidas_capturas WHERE sha256=? AND visto_nivon_utc=?", (sha,when)).fetchone():
                    events.append({"sha256":sha,"dataset_id":dataset,"estado":"REPLAY_SEM_MUDANCA",
                                   "medidas":len(item["registros"])})
                    continue
                if db.execute(
                    "SELECT 1 FROM medidas_capturas c JOIN medidas_edicoes e ON e.sha256=c.sha256 "
                    "WHERE c.visto_nivon_utc=? AND e.dataset_id=? AND e.estacao_id=? AND e.classe=? "
                    "AND c.sha256!=? LIMIT 1", (when,dataset,station,item["classe"],sha)
                ).fetchone():
                    raise ErroPipelineAmbiental("capturas conflitantes de estação no mesmo instante")
                archive = _raw(folder,sha,data=item["raw"])
                if existing is None:
                    db.execute("INSERT INTO medidas_edicoes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sha,dataset,item["formato"],station,item["ano"],item["zona"],
                         item["classe"],item["fonte_coletado_utc"],when,
                         None,archive.name,len(item["registros"]),"NAO_HOMOLOGADO"))
                    db.executemany("INSERT INTO medidas_registros VALUES (?,?,?,?,?,?,?)",
                        [(sha,*row) for row in item["registros"]])
                db.execute("INSERT INTO medidas_capturas VALUES (?,?)",(sha,when))
                events.append({
                    "sha256":sha,"dataset_id":dataset,
                    "estado":"NOVA_EDICAO" if existing is None else "NOVA_CAPTURA_EDICAO_EXISTENTE",
                    "medidas":len(item["registros"]),
                })
            audited = auditar_acervo_medicoes(db,raw_dir=folder)
    except BaseException:
        live={r[0]+".raw" for r in db.execute("SELECT sha256 FROM medidas_edicoes")}
        for p in folder.glob("*.raw"):
            if p.name not in prior_paths and p.name not in live and p.is_file() and not p.is_symlink():
                p.unlink()
        raise
    return {
        "estado":"CICLO_INMET_ANA_ATOMICO_LOCAL",
        "arquivos_processados":len(events), "edicoes":events,
        "auditoria":audited, "http":0, "operacional":False,
        "agendado":False,"modelo_preditivo_homologado":False,
    }


def consultar_medicoes_asof(db, *, raw_dir, dataset_id, estacao_id, metrica,
                           inicio_utc, fim_utc, corte_nivon, classe="SINTETICO"):
    """Consulta somente snapshots OBSERVADOS localmente até a data de corte."""
    if dataset_id not in ("INMET_ESTACOES","ANA_HIDRO") or classe not in CLASSES:
        raise ErroPipelineAmbiental("dataset/classe inválidos")
    start,end,cut=(_tempo(x,n) for x,n in (
        (inicio_utc,"início"),(fim_utc,"fim"),(corte_nivon,"corte")))
    if end < start or (end-start).days > 3660:
        raise ErroPipelineAmbiental("intervalo de consulta incorreto")
    rows=db.execute(
        "SELECT r.*,e.dataset_id,e.estacao_id,e.classe,e.publicado_utc, "
        "c.visto_nivon_utc FROM medidas_registros r "
        "JOIN medidas_edicoes e ON e.sha256=r.sha256 "
        "JOIN medidas_capturas c ON c.sha256=r.sha256 "
        "WHERE e.dataset_id=? AND e.estacao_id=? AND e.classe=? "
        "AND r.metrica=? AND r.medido_utc BETWEEN ? AND ? "
        "AND c.visto_nivon_utc<=? ORDER BY r.medido_utc,c.visto_nivon_utc DESC",
        (dataset_id,estacao_id,classe,metrica,start.isoformat(),
         end.isoformat(),cut.isoformat())
    ).fetchall()
    distinct, recorded = {}, set()
    for x in rows:
        if x["medido_utc"] in recorded:
            continue
        recorded.add(x["medido_utc"])
        _raw(_pasta(raw_dir,criar=False),x["sha256"])
        distinct[x["medido_utc"]]={
            "dataset_id":dataset_id,"estacao_id":estacao_id,
            "instante_utc":x["medido_utc"],"metrica":metrica,
            "valor":x["valor"],"unidade":x["unidade"],
            "qualidade_origem":x["qualidade_origem"],
            "suporte_temporal":x["suporte_temporal"],
            "raw_sha256":x["sha256"],
            "primeira_observacao_ciclo_utc":x["visto_nivon_utc"],
            "publicacao_da_medida_comprovada":False,
            "qc_externo_homologado":False,
            "disponibilidade_passada_certificada":False,
        }
    return [distinct[k] for k in sorted(distinct)]


def auditar_acervo_medicoes(db, *, raw_dir):
    """Reprocessa todos os arquivos originais e confronta cada medida armazenada."""
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
        raise ErroPipelineAmbiental("integridade SQLite comprometida")
    versions = db.execute("SELECT * FROM medidas_edicoes ORDER BY sha256").fetchall()
    if not versions:
        return {"estado":"ACERVO_VAZIO","edicoes_auditadas":0,"homologado":False}
    folder=_pasta(raw_dir,criar=False)
    total=0
    seen=set()
    for version in versions:
        sha=version["sha256"]
        archive=_raw(folder,sha)
        if archive.name!=version["arquivo"]:
            raise ErroPipelineAmbiental("caminho RAW não corresponde à edição")
        seen.add(archive.name)
        valid=preparar_arquivo_medicoes(
            formato=version["formato"],raw=archive.read_bytes(),
            estacao_id=version["estacao_id"],ano=version["ano"],
            zona=version["zona"],classe="SINTETICO",
            coletado_em=version["fonte_coletado_utc"],
            observado_nivon_em=version["visto_nivon_utc"])
        stored = [tuple(y) for y in db.execute(
            "SELECT medido_utc,metrica,valor,unidade,qualidade_origem,suporte_temporal "
            "FROM medidas_registros WHERE sha256=? ORDER BY medido_utc,metrica",(sha,))]
        if (valid["sha256"] != sha or valid["dataset_id"] != version["dataset_id"]
            or sorted(valid["registros"],key=lambda x:(x[0],x[1])) != stored
            or len(stored) != version["registros"]):
            raise ErroPipelineAmbiental("índice/medidas divergem dos bytes originais")
        total+=len(stored)
    if {p.name for p in folder.glob("*.raw")} - seen:
        raise ErroPipelineAmbiental("RAW órfão deve ser reconciliado")
    return {
        "estado":"ACERVO_INMET_ANA_VERIFICADO_TECNICAMENTE",
        "edicoes_auditadas":len(versions),
        "medidas_auditadas":total,
        "capturas_auditadas":db.execute("SELECT COUNT(*) FROM medidas_capturas").fetchone()[0],
        "integridade_raw":True,"integridade_sqlite":True,
        "publicacao_fonte_autenticada":False,
        "qc_homologado":False,
        "modelo_preditivo_homologado":False,"homologado":False,
    }
